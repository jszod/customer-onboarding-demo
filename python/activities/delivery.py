"""Delivery. §5.5.1.

Both idempotent by construction: send_documents writes to a deterministic path
so a retry overwrites rather than duplicating, and notify keys its records so a
retry does not double-send. Neither sends real email or SMS.

`notify` is ONE activity with three callers — the terminal notification, the
§9.2 SLA reminder and the §9.2 escalation — distinguished by `recipients`,
rather than three near-identical activities.
"""
from __future__ import annotations

import json

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
    path.write_text("\n".join(body))
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
    outbox = config.settings().outbox_dir
    outbox.mkdir(parents=True, exist_ok=True)
    log_path = outbox / "notifications.json"
    log = json.loads(log_path.read_text()) if log_path.exists() else []

    key = [req.client_key, req.outcome, sorted(req.recipients), req.detail]
    if not any([r["client_key"], r["outcome"], sorted(r["recipients"]),
                r["detail"]] == key for r in log):
        log.append(req.model_dump(mode="json"))
        log_path.write_text(json.dumps(log, indent=2))
    activity.logger.info("notified %s: %s", req.recipients, req.detail)
    return NotifyResult(delivered_to=list(req.recipients))
