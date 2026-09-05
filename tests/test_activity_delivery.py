"""Delivery activity unit tests. §5.5.1, §9.2, §10.2.

Both activities are idempotent by construction, and that is the point: Tasks 14
and 17 retry both, and neither may produce a duplicate. Everything here runs in
`ActivityEnvironment` — in-process, no Temporal server — and writes to a temp
directory rather than the repo's real `outbox/`.
"""
import asyncio
import json

from temporalio.testing import ActivityEnvironment

from python.activities.delivery import notify, send_documents
from python.models.application import ApplicationFields
from python.models.delivery import NotifyRequest, SendDocumentsRequest


def _run(fn, arg):
    return asyncio.new_event_loop().run_until_complete(
        ActivityEnvironment().run(fn, arg))


def _pack(tmp_path):
    import os
    os.environ["OUTBOX_DIR"] = str(tmp_path)
    return SendDocumentsRequest(
        client_key="acme-corp", client_id="CL-ABC12345",
        legal_name="Acme Holdings LLC",
        application=ApplicationFields(legal_name="Acme Holdings LLC"))


def test_send_documents_writes_a_packet_and_returns_a_reference(tmp_path):
    """§5.5.1 — a reference, not content, consistent with §8.2."""
    result = _run(send_documents, _pack(tmp_path))
    assert result.packet_uri
    assert (tmp_path / result.packet_uri).exists()
    assert result.page_count >= 1


def test_send_documents_is_idempotent(tmp_path):
    """Deterministic path from client_key + client_id, so a retry overwrites."""
    first = _run(send_documents, _pack(tmp_path))
    second = _run(send_documents, _pack(tmp_path))
    assert first.packet_uri == second.packet_uri
    assert len(list(tmp_path.rglob("*.txt"))) == 1


def test_notify_records_recipients(tmp_path):
    import os
    os.environ["OUTBOX_DIR"] = str(tmp_path)
    result = _run(notify, NotifyRequest(
        client_key="acme-corp", client_id="CL-ABC12345", outcome="completed",
        recipients=["onboarding_specialist", "end_client"],
        packet_uri="acme-corp/CL-ABC12345.txt", detail="onboarding complete"))
    assert set(result.delivered_to) == {"onboarding_specialist", "end_client"}
    log = json.loads((tmp_path / "notifications.json").read_text())
    assert log[0]["outcome"] == "completed"


def test_notify_serves_reminders_and_escalations_too(tmp_path):
    """§5.5.1 — one activity, three callers."""
    import os
    os.environ["OUTBOX_DIR"] = str(tmp_path)
    _run(notify, NotifyRequest(client_key="acme-corp", client_id=None,
                               outcome="manual_intervention",
                               recipients=["supervisor"],
                               detail="KYC review SLA breached"))
    log = json.loads((tmp_path / "notifications.json").read_text())
    assert log[0]["recipients"] == ["supervisor"]


def test_notify_dedupes_identical_records(tmp_path):
    import os
    os.environ["OUTBOX_DIR"] = str(tmp_path)
    req = NotifyRequest(client_key="acme-corp", client_id="CL-1",
                        outcome="completed", recipients=["end_client"],
                        detail="done")
    _run(notify, req)
    _run(notify, req)
    log = json.loads((tmp_path / "notifications.json").read_text())
    assert len(log) == 1


def test_notify_keeps_distinct_reminders(tmp_path):
    """§9.2 — the per-attempt reminders differ only in `detail`.

    The dedupe key is `(client_key, outcome, recipients, detail)`. A Temporal
    retry reproduces `detail` verbatim, so retries still collapse (the test
    above), while the attempt-2 reminder the analyst genuinely needs to see
    still reaches the log.
    """
    import os
    os.environ["OUTBOX_DIR"] = str(tmp_path)
    for attempt in (1, 2):
        _run(notify, NotifyRequest(
            client_key="acme-corp", client_id=None,
            outcome="manual_intervention",
            recipients=["onboarding_specialist"],
            detail=f"KYC review reminder: attempt {attempt} awaiting review"))
    log = json.loads((tmp_path / "notifications.json").read_text())
    assert len(log) == 2
