"""Delivery. §5.5.1.

Both idempotent by construction: send_documents writes to a deterministic path
so a retry overwrites rather than duplicating, and notify keys its records so a
retry does not double-send. Neither sends real email or SMS.

`notify` is ONE activity with three callers — the terminal notification, the
§9.2 SLA reminder and the §9.2 escalation — distinguished by `recipients`,
rather than three near-identical activities.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

from temporalio import activity

from python import config
from python.models.delivery import (NotifyRequest, NotifyResult,
                                    SendDocumentsRequest, SendDocumentsResult)


@activity.defn(name="send_documents")
async def send_documents(req: SendDocumentsRequest) -> SendDocumentsResult:
    """Write the welcome pack and return a reference to it, never its content.

    The path is derived from `client_key` + `client_id`, so the retry Task 14
    may trigger overwrites the same file instead of producing a second packet.
    """
    outbox = config.settings().outbox_dir
    rel = f"{req.client_key}/{req.client_id}.txt"
    path = outbox / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    body = [
        f"WELCOME PACK — {req.legal_name}",
        f"Client ID: {req.client_id}",
        "",
        "Your business account has been opened. Enclosed:",
        "  - Account agreement",
        "  - Signature card",
        "  - Treasury services schedule",
        "",
        "Application on file:",
        json.dumps(req.application.model_dump(mode="json"), indent=2),
    ]
    await asyncio.to_thread(_write_atomically, path, "\n".join(body))
    activity.logger.info("wrote welcome pack to %s", rel)
    return SendDocumentsResult(packet_uri=rel, page_count=1)


@activity.defn(name="notify")
async def notify(req: NotifyRequest) -> NotifyResult:
    """Append a notification record the console renders. §5.5.1, §9.2.

    The record is keyed by `(client_key, outcome, recipients, detail)`. A
    Temporal retry reproduces every one of those verbatim, so a retry appends
    nothing; the §9.2 reminders, which differ only in `detail` (the attempt and
    how long the review has been pending), stay distinct.
    """
    record = req.model_dump(mode="json")
    await asyncio.to_thread(_append_notification, record,
                            [req.client_key, req.outcome,
                             sorted(req.recipients), req.detail])
    activity.logger.info("notified %s: %s", req.recipients, req.detail)
    return NotifyResult(delivered_to=list(req.recipients))


def _write_atomically(path: Path, text: str) -> None:
    """Write via a temp file in the same directory, then rename.

    `write_text` truncates first and writes second, so a worker killed between
    the two leaves a half-written file behind. `os.replace` is atomic on POSIX
    and on Windows: a reader sees either the old file or the new one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _read_log(log_path: Path) -> list[dict]:
    """The notification log, or an empty one if it cannot be read.

    A truncated or hand-edited `notifications.json` must not be able to stop
    the demo: every terminal status goes through `notify`, so an unhandled
    decode error here retries forever on the default policy and NO workflow
    ever reaches a terminal status -- a corrupt outbox file presenting as the
    whole system hanging. The bad file is kept, renamed, rather than deleted:
    it is evidence, and it is not what anyone is looking at.
    """
    if not log_path.exists():
        return []
    try:
        log = json.loads(log_path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError):
        log = None
    if not isinstance(log, list):
        broken = log_path.with_suffix(".json.corrupt")
        os.replace(log_path, broken)
        activity.logger.warning(
            "%s was unreadable; moved it to %s and started a new log",
            log_path, broken)
        return []
    return log


def _append_notification(record: dict, key: list) -> None:
    log_path = config.settings().outbox_dir / "notifications.json"
    log = _read_log(log_path)
    if any([r.get("client_key"), r.get("outcome"),
            sorted(r.get("recipients", [])), r.get("detail")] == key
           for r in log if isinstance(r, dict)):
        return
    log.append(record)
    _write_atomically(log_path, json.dumps(log, indent=2))
