"""The `submit_review` validator. §9.1, T-WF-04/05/06.

Six rules, enforced before anything enters history. Format and internal
consistency only — a validator may not block or mutate.
"""
import uuid

import pytest
from temporalio.client import WorkflowUpdateFailedError

from python.models.onboarding import OnboardingResult
from python.models.review import ReviewAck
from tests.conftest import Stubs, application_with_the_gap, run_worker
from tests.test_onboarding_workflow import _wait_for

FILL_THE_GAP = [{"field_path": "beneficial_owners[1].dob", "value": "1985-01-01"}]


async def _at_review(env, gap: bool = True):
    stubs = Stubs()
    if gap:
        from python.models.extraction import FieldGap
        stubs.extraction.application = application_with_the_gap()
        stubs.extraction.escalated = True
        stubs.extraction.gaps = [FieldGap(field_path="beneficial_owners[1].dob",
                                          reason="not stated",
                                          documents_searched=["ownership_declaration"])]
    queue, worker = await run_worker(env, stubs)
    return stubs, queue, worker


async def _submit(env, queue, body: dict):
    handle = await env.client.start_workflow(
        "OnboardingWorkflow",
        {"client_key": "acme-corp", "legal_name": "Acme Holdings LLC"},
        result_type=OnboardingResult,
        id=f"onboarding-acme-corp-{uuid.uuid4()}", task_queue=queue)
    await _wait_for(handle, "awaiting_review")
    return handle, await handle.execute_update("submit_review", body,
                                               result_type=ReviewAck)


def _approve(**over) -> dict:
    return {"decision": "approve", "analyst_id": "kyc-7", "note": None,
            "field_edits": [], "attested": True, **over}


async def assert_approve_with_empty_required_field_is_rejected(env):
    """The rule that forces the analyst to fill the escalated dob (§9.1 r2)."""
    _, queue, worker = await _at_review(env)
    async with worker:
        with pytest.raises(WorkflowUpdateFailedError) as ei:
            await _submit(env, queue, _approve())
    assert "beneficial_owners[1].dob" in str(ei.value.cause)


async def assert_approve_without_attestation_is_rejected(env):
    """§9.1 r3."""
    _, queue, worker = await _at_review(env)
    async with worker:
        with pytest.raises(WorkflowUpdateFailedError) as ei:
            await _submit(env, queue,
                          _approve(attested=False, field_edits=FILL_THE_GAP))
    assert "attest" in str(ei.value.cause).lower()


async def assert_ownership_over_100_is_rejected(env):
    """§9.1 r5 — <=, not ==."""
    _, queue, worker = await _at_review(env)
    async with worker:
        with pytest.raises(WorkflowUpdateFailedError) as ei:
            await _submit(env, queue, _approve(field_edits=FILL_THE_GAP + [
                {"field_path": "beneficial_owners[0].ownership_pct", "value": "80"}]))
    assert "100" in str(ei.value.cause)


async def test_ownership_under_100_is_accepted(env):
    """85% is the acme-corp total: holders below 25% are not listed."""
    _, queue, worker = await _at_review(env)
    async with worker:
        _, ack = await _submit(env, queue, _approve(field_edits=FILL_THE_GAP))
    assert ack.accepted is True


async def test_malformed_ein_is_rejected(env):
    """§9.1 r4."""
    _, queue, worker = await _at_review(env)
    async with worker:
        with pytest.raises(WorkflowUpdateFailedError) as ei:
            await _submit(env, queue, _approve(field_edits=FILL_THE_GAP + [
                {"field_path": "tax_id", "value": "881234567"}]))
    assert "tax_id" in str(ei.value.cause)


async def test_reject_without_a_note_is_rejected(env):
    """§9.1 r6 — a rejection the specialist cannot act on is useless."""
    _, queue, worker = await _at_review(env)
    async with worker:
        with pytest.raises(WorkflowUpdateFailedError) as ei:
            await _submit(env, queue, {"decision": "reject", "analyst_id": "kyc-7",
                                       "note": None, "field_edits": [],
                                       "attested": False})
    assert "note" in str(ei.value.cause).lower()


async def test_reject_does_not_require_filling_gaps(env):
    """Only APPROVE requires completeness."""
    _, queue, worker = await _at_review(env)
    async with worker:
        _, ack = await _submit(env, queue, {"decision": "reject",
                                            "analyst_id": "kyc-7",
                                            "note": "missing the EIN letter",
                                            "field_edits": [], "attested": False})
    assert ack.accepted is True


async def test_edits_do_not_overwrite_the_extracted_application(env):
    """§9.1 audit rule — the AI's output and the human delta are both kept."""
    stubs, queue, worker = await _at_review(env)
    async with worker:
        handle, _ = await _submit(env, queue, _approve(field_edits=FILL_THE_GAP))
        await _wait_for(handle, "awaiting_client_id")
    assert stubs.extraction.application.beneficial_owners[1].dob is None


async def test_an_edit_to_a_field_that_is_not_a_gap_is_accepted(env):
    """Settles the open question left for this task: `field_edits` is not
    scoped to `gaps[]`. §9.1 justifies choosing an update over a signal on the
    grounds that the analyst edits field values, and §19.3 already requires
    accepting an edit to an *optional* field — neither reading survives a
    contract that only accepts gap paths. Correcting a field the model filled
    in wrongly is the ordinary case in KYC review."""
    _, queue, worker = await _at_review(env)
    async with worker:
        handle, ack = await _submit(env, queue, _approve(
            field_edits=FILL_THE_GAP + [
                {"field_path": "legal_name", "value": "Acme Holdings LLC"},
                {"field_path": "website", "value": "https://acme.example"}]))
        await _wait_for(handle, "awaiting_client_id")
        status = await handle.query("status")
    assert ack.accepted is True
    assert status["application"]["website"] == "https://acme.example"
