"""Document ingestion. §5.2.

Represents step 1 of the business process, which is why it lives in the
workflow rather than in the gateway (§7): the workflow must contain the whole
process, a failed copy must retry under policy, and the timeline needs its
opening labelled step.

The working directory is **per attempt**. That is what lets a rejected attempt
pick up documents the client supplied late — ingest re-runs on every attempt
(§7) — without disturbing the previous attempt's refs, which remain valid for
replay.

What crosses the activity boundary is a `DocumentManifest` of refs: doc id,
kind, store-relative uri, hash and page count. Never content (§8.1, §8.2).
"""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

from pypdf import PdfReader
from temporalio import activity
from temporalio.exceptions import ApplicationError

from python import config
from python.models.documents import DocumentManifest, DocumentRef, IngestRequest

# §5.2 — the five documents of a business onboarding set, and the kind each
# maps to. Insertion order is the manifest's order, so a manifest is stable
# across attempts and diffable in the Temporal UI.
KIND_BY_STEM: dict[str, str] = {
    "articles-of-incorporation": "articles_of_incorporation",
    "business-license": "business_license",
    "ein-letter": "ein_letter",
    "w9": "w9",
    "ownership-declaration": "ownership_declaration",
}

# The repo root, so the source set resolves the same whether the worker was
# started from the repo root, from a service directory, or by a supervisor.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _documents_dir() -> Path:
    """`documents/` at the repo root, overridable for tests via DOCUMENTS_DIR."""
    override = os.environ.get("DOCUMENTS_DIR")
    return Path(override) if override else _REPO_ROOT / "documents"


@activity.defn(name="ingest_documents")
async def ingest_documents(req: IngestRequest) -> DocumentManifest:
    # §17.1. Five documents' worth of pacing, so step 1 is legible on a call.
    # First, not last, so the activity shows Running while it "works".
    await config.demo_pause(2)
    source = _documents_dir() / req.client_key
    if not source.is_dir():
        # §10.2, §19.7: a document that is not there will not appear because we
        # asked again. Non-retryable, classified here rather than at the call
        # site, so the attempt is spent and the reject loop can carry on.
        raise ApplicationError(
            f"no document set for client {req.client_key!r} at {source}",
            type="DocumentSetMissing", non_retryable=True)

    store = config.settings().document_store
    working = store / req.client_key / str(req.attempt)
    working.mkdir(parents=True, exist_ok=True)

    refs: list[DocumentRef] = []
    for stem, kind in KIND_BY_STEM.items():
        src = source / f"{stem}.pdf"
        if not src.is_file():
            raise ApplicationError(
                f"document {stem}.pdf missing from {source}",
                type="DocumentMissing", non_retryable=True)

        # copy2 overwrites, so a Temporal retry of this activity reproduces the
        # same working directory rather than duplicating or colliding.
        dest = working / src.name
        shutil.copy2(src, dest)
        digest = hashlib.sha256(dest.read_bytes()).hexdigest()

        try:
            page_count = len(PdfReader(dest).pages)
        except Exception as exc:  # noqa: BLE001 — classified, then re-raised
            # §10.2 lists "file missing / unreadable" as non-retryable: a
            # corrupt PDF is corrupt on every attempt.
            raise ApplicationError(
                f"document {stem}.pdf is unreadable: {exc}",
                type="DocumentUnreadable", non_retryable=True) from exc

        refs.append(DocumentRef(
            doc_id=stem,
            kind=kind,
            uri=dest.relative_to(store).as_posix(),
            sha256=digest,
            page_count=page_count))

    activity.logger.info("ingested %d documents for %s attempt %d",
                         len(refs), req.client_key, req.attempt)
    return DocumentManifest(refs=refs)
