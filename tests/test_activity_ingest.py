"""`ingest_documents` unit tests. §5.2, §8.2, §10.2, §19.7.

Everything here runs in `ActivityEnvironment` — in-process, no Temporal server
— and against a temporary `DOCUMENT_STORE`, never the repo's real `.store/`.

`assert_copies_and_hashes()` and `assert_missing_file_is_non_retryable()` are
module-level, zero-argument, and raise on failure so that the manifest scenario
`T-ACT-01` can delegate into them while the manifest name stays authoritative
(§16.8).
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from python.activities.ingest import ingest_documents
from python.models.documents import IngestRequest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = REPO_ROOT / "documents"
STEMS = ("articles-of-incorporation", "business-license", "ein-letter", "w9",
         "ownership-declaration")
KINDS = {"articles_of_incorporation", "business_license", "ein_letter", "w9",
         "ownership_declaration"}


@contextmanager
def _env(**values: str):
    """Set env vars for the duration of one activity run and restore after.

    The store must never leak into another test's run — a stale DOCUMENT_STORE
    pointing at a deleted temp directory is a confusing failure two modules
    later.
    """
    previous = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, was in previous.items():
            if was is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = was


def _run(req: IngestRequest, store: Path, documents: Path | None = None):
    with _env(DOCUMENT_STORE=str(store),
              DOCUMENTS_DIR=str(documents or DOCUMENTS)):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(
                ActivityEnvironment().run(ingest_documents, req))
        finally:
            loop.close()


# --- the two functions T-ACT-01 delegates into (zero-arg, raise on failure) ---

def assert_copies_and_hashes() -> None:
    """§5.2 — copies into a per-attempt working dir, hashes, returns refs."""
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp)
        manifest = _run(IngestRequest(client_key="acme-corp", attempt=1), store)

        assert len(manifest.refs) == 5, manifest
        assert {r.kind for r in manifest.refs} == KINDS
        assert {r.doc_id for r in manifest.refs} == set(STEMS)

        for ref in manifest.refs:
            assert len(ref.sha256) == 64, ref
            assert ref.page_count >= 1, ref
            copied = store / ref.uri
            assert copied.exists(), f"{ref.uri} not written under the store"
            assert not Path(ref.uri).is_absolute(), "uri must be store-relative"
            assert Path(ref.uri).parts[:2] == ("acme-corp", "1"), \
                f"uri must be per-attempt: {ref.uri}"
            # The copy is byte-identical to the committed source document.
            source = DOCUMENTS / "acme-corp" / f"{ref.doc_id}.pdf"
            assert copied.read_bytes() == source.read_bytes(), ref.doc_id


def assert_missing_file_is_non_retryable() -> None:
    """§19.7, §10.2 — a document that is not there is not worth retrying.

    Both shapes: no document set at all, and a set that is missing one of the
    five documents. Classification lives inside the activity, so merely calling
    it produces the right retry behaviour.
    """
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp) / "store"

        with pytest.raises(ApplicationError) as ei:
            _run(IngestRequest(client_key="does-not-exist", attempt=1), store)
        assert ei.value.non_retryable is True, ei.value

        partial = Path(tmp) / "documents" / "acme-corp"
        partial.mkdir(parents=True)
        for stem in STEMS[:-1]:
            shutil.copy2(DOCUMENTS / "acme-corp" / f"{stem}.pdf",
                         partial / f"{stem}.pdf")

        with pytest.raises(ApplicationError) as ei:
            _run(IngestRequest(client_key="acme-corp", attempt=1), store,
                 documents=partial.parent)
        assert ei.value.non_retryable is True, ei.value
        assert "ownership-declaration" in str(ei.value)


# --- pytest surface: the helpers above plus the per-attempt properties -------

def test_copies_and_hashes():
    assert_copies_and_hashes()


def test_missing_file_is_non_retryable():
    assert_missing_file_is_non_retryable()


def test_attempt_two_gets_its_own_directory(tmp_path):
    """§5.2 — per-attempt working dir, so a rejected attempt can pick up new
    documents while the prior attempt's refs stay valid for replay."""
    one = _run(IngestRequest(client_key="acme-corp", attempt=1), tmp_path)
    two = _run(IngestRequest(client_key="acme-corp", attempt=2), tmp_path)
    assert {r.uri for r in one.refs}.isdisjoint({r.uri for r in two.refs})
    for ref in one.refs:
        assert (tmp_path / ref.uri).exists(), "attempt 1 refs stay resolvable"


def test_hash_is_stable_across_attempts(tmp_path):
    one = _run(IngestRequest(client_key="acme-corp", attempt=1), tmp_path)
    two = _run(IngestRequest(client_key="acme-corp", attempt=2), tmp_path)
    by_kind = {r.kind: r.sha256 for r in one.refs}
    assert all(by_kind[r.kind] == r.sha256 for r in two.refs)


def test_rerun_of_the_same_attempt_is_idempotent(tmp_path):
    """Temporal re-executes activities on retry; a retry must overwrite rather
    than duplicate or fail on the existing directory."""
    first = _run(IngestRequest(client_key="acme-corp", attempt=1), tmp_path)
    second = _run(IngestRequest(client_key="acme-corp", attempt=1), tmp_path)
    assert [r.model_dump() for r in first.refs] == \
           [r.model_dump() for r in second.refs]
    assert len(list((tmp_path / "acme-corp" / "1").glob("*.pdf"))) == 5


def test_manifest_carries_refs_not_content(tmp_path):
    """§8.2 — document content never enters workflow history."""
    manifest = _run(IngestRequest(client_key="acme-corp", attempt=1), tmp_path)
    serialized = manifest.model_dump_json()
    assert "%PDF" not in serialized
    assert len(serialized) < 4096, "a manifest is refs, not documents"


def test_a_late_added_document_is_picked_up_by_the_next_attempt(tmp_path):
    """§7 — ingest re-runs on every attempt, which is what makes the reject
    loop able to consume a document the client supplied after the rejection."""
    documents = tmp_path / "documents"
    client = documents / "acme-corp"
    client.mkdir(parents=True)
    for stem in STEMS[:-1]:
        shutil.copy2(DOCUMENTS / "acme-corp" / f"{stem}.pdf",
                     client / f"{stem}.pdf")
    store = tmp_path / "store"

    with pytest.raises(ApplicationError):
        _run(IngestRequest(client_key="acme-corp", attempt=1), store,
             documents=documents)

    shutil.copy2(DOCUMENTS / "acme-corp" / "ownership-declaration.pdf",
                 client / "ownership-declaration.pdf")
    manifest = _run(IngestRequest(client_key="acme-corp", attempt=2), store,
                    documents=documents)
    assert {r.kind for r in manifest.refs} == KINDS


def test_the_activity_is_registered_under_its_contract_name():
    """The gateway and worker agree by string name (§6)."""
    assert ingest_documents.__temporal_activity_definition.name == \
        "ingest_documents"
