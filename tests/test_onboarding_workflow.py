"""The seven-step parent. §7, T-WF-01/02/03/09.

Everything the workflow calls is a hand-written stub (§16.0) — these tests pin
the business process, not the activities, which have their own tests.
"""
import asyncio
import uuid

import pytest
from temporalio.client import WorkflowUpdateFailedError

from python.models.onboarding import OnboardingResult
from tests.conftest import Stubs, application_with_the_gap, run_worker

APPROVE = {"decision": "approve", "analyst_id": "kyc-7", "note": None,
           "field_edits": [], "attested": True}


def _reject(note: str) -> dict:
    return {"decision": "reject", "analyst_id": "kyc-7", "note": note,
            "field_edits": [], "attested": False}


async def _start(env, stubs, queue):
    return await env.client.start_workflow(
        "OnboardingWorkflow",
        {"client_key": "acme-corp", "legal_name": "Acme Holdings LLC"},
        result_type=OnboardingResult,
        id=f"onboarding-acme-corp-{uuid.uuid4()}", task_queue=queue)


async def _wait_for(handle, stage: str, attempt: int | None = None,
                    timeout: float = 20.0):
    status = None
    for _ in range(int(timeout * 10)):
        status = await handle.query("status")
        if status["stage"] == stage and (attempt is None
                                         or status["attempt"] == attempt):
            return status
        await asyncio.sleep(0.1)
    raise AssertionError(f"never reached {stage!r}; last was {status}")


async def assert_happy_path(env):
    """Approve once, receive the client ID, complete."""
    stubs = Stubs()
    queue, worker = await run_worker(env, stubs)
    async with worker:
        handle = await _start(env, stubs, queue)
        await _wait_for(handle, "awaiting_review")
        await handle.execute_update("submit_review", APPROVE)
        await _wait_for(handle, "awaiting_client_id")
        await handle.signal("client_id_received",
                            {"client_id": "CL-ABC12345", "core_ref": "REQ-1",
                             "assigned_at": "2026-09-04T10:00:00Z"})
        result = await handle.result()
    assert result.status == "completed"
    assert result.client_id == "CL-ABC12345"
    assert result.attempts == 1


async def assert_reject_increments_attempt_and_reingests(env):
    stubs = Stubs()
    queue, worker = await run_worker(env, stubs)
    async with worker:
        handle = await _start(env, stubs, queue)
        await _wait_for(handle, "awaiting_review")
        await handle.execute_update("submit_review",
                                    _reject("you missed the EIN letter"))
        await _wait_for(handle, "awaiting_review", attempt=2)
        status = await handle.query("status")
        assert status["attempt"] == 2
        assert stubs.ingest_calls == [1, 2], "ingest must re-run per attempt"
        await handle.execute_update("submit_review", APPROVE)
        await _wait_for(handle, "awaiting_client_id")
        await handle.signal("client_id_received",
                            {"client_id": "CL-2", "core_ref": "REQ-1",
                             "assigned_at": "2026-09-04T10:00:00Z"})
        result = await handle.result()
    assert result.attempts == 2


async def assert_max_attempts_exhausted_is_manual_intervention(env):
    """Not a failed workflow — a completed one with a business status (§10.3)."""
    stubs = Stubs()
    queue, worker = await run_worker(env, stubs)
    async with worker:
        handle = await _start(env, stubs, queue)
        for attempt in range(1, 4):
            await _wait_for(handle, "awaiting_review", attempt=attempt)
            await handle.execute_update("submit_review", _reject("still wrong"))
        result = await handle.result()
    assert result.status == "manual_intervention"
    assert result.attempts == 3
    assert stubs.ingest_calls == [1, 2, 3]
    assert any(n["outcome"] == "manual_intervention" for n in stubs.notifications)


async def assert_child_workflow_error_counts_as_a_spent_attempt(env):
    stubs = Stubs()
    stubs.child_raises = True
    queue, worker = await run_worker(env, stubs)
    async with worker:
        handle = await _start(env, stubs, queue)
        result = await handle.result()
    assert result.status == "manual_intervention"
    assert result.attempts == 3, "each child failure spends one attempt"
    assert stubs.ingest_calls == [1, 2, 3]


async def test_exhausted_child_failures_report_the_real_cause(env):
    """Three ChildWorkflowErrors exhaust the loop without a single human
    decision, so the detail must not describe a review that never happened --
    and must not drop the only record of what actually went wrong."""
    stubs = Stubs()
    stubs.child_raises = True
    queue, worker = await run_worker(env, stubs)
    async with worker:
        handle = await _start(env, stubs, queue)
        result = await handle.result()

    assert result.status == "manual_intervention"
    assert "rejected" not in result.detail.lower(), \
        f"nothing was ever rejected: {result.detail!r}"
    assert "extraction" in result.detail.lower(), \
        f"the detail must carry the real cause: {result.detail!r}"
    supervisor = [n for n in stubs.notifications
                  if "supervisor" in n["recipients"]]
    assert supervisor and "extraction" in supervisor[-1]["detail"].lower(), \
        "the supervisor is told what actually failed"


async def test_exhausted_rejections_still_report_the_analyst_note(env):
    """The other way out of the loop: three real rejections. The last note is
    what the supervisor needs, so it must survive."""
    stubs = Stubs()
    queue, worker = await run_worker(env, stubs)
    async with worker:
        handle = await _start(env, stubs, queue)
        for attempt in range(1, 4):
            await _wait_for(handle, "awaiting_review", attempt=attempt)
            await handle.execute_update("submit_review",
                                        _reject(f"wrong for the {attempt} time"))
        result = await handle.result()

    assert result.status == "manual_intervention"
    assert "wrong for the 3 time" in result.detail, \
        f"the last analyst note must survive: {result.detail!r}"


async def test_a_second_decision_cannot_replace_the_first(env):
    """An approval the workflow has acknowledged must not be undone by a later
    reject (§9.1). Once the gate has closed the stage guard is what refuses
    it; the same-activation race, where the stage has not moved yet, is
    `test_concurrent_decisions_do_not_both_win` below."""
    stubs = Stubs()
    queue, worker = await run_worker(env, stubs)
    async with worker:
        handle = await _start(env, stubs, queue)
        await _wait_for(handle, "awaiting_review")
        ack = await handle.execute_update("submit_review", APPROVE)
        assert ack["accepted"] is True

        with pytest.raises(WorkflowUpdateFailedError):
            await handle.execute_update("submit_review",
                                        _reject("changed my mind"))

        # The approval stands: the workflow moved on rather than looping back
        # into a second review.
        await _wait_for(handle, "awaiting_client_id")
        await handle.signal("client_id_received",
                            {"client_id": "CL-1", "core_ref": "REQ-1",
                             "assigned_at": "2026-09-04T10:00:00Z"})
        result = await handle.result()
    assert result.status == "completed"
    assert result.attempts == 1


async def test_concurrent_decisions_do_not_both_win(env):
    """Two updates delivered in one activation are both VALIDATED before
    either handler runs, so the validator alone cannot settle this."""
    stubs = Stubs()
    queue, worker = await run_worker(env, stubs)
    async with worker:
        handle = await _start(env, stubs, queue)
        await _wait_for(handle, "awaiting_review")
        results = await asyncio.gather(
            handle.execute_update("submit_review", APPROVE),
            handle.execute_update("submit_review", _reject("changed my mind")),
            return_exceptions=True)

        accepted = [r for r in results if not isinstance(r, BaseException)]
        # Which one wins is a race and does not matter. That only ONE of them
        # is acknowledged is the property: without the guard both are, and the
        # second silently overwrites the decision the first already confirmed.
        assert len(accepted) == 1, \
            f"exactly one decision may be accepted, got {results}"


async def test_gaps_are_visible_in_status_while_awaiting_review(env):
    stubs = Stubs()
    stubs.extraction.application = application_with_the_gap()
    stubs.extraction.escalated = True
    from python.models.extraction import FieldGap
    stubs.extraction.gaps = [FieldGap(field_path="beneficial_owners[1].dob",
                                      reason="not stated",
                                      documents_searched=["ownership_declaration"])]
    queue, worker = await run_worker(env, stubs)
    async with worker:
        handle = await _start(env, stubs, queue)
        await _wait_for(handle, "awaiting_review")
        status = await handle.query("status")
    assert status["gaps"][0]["field_path"] == "beneficial_owners[1].dob"
    assert status["extraction_iterations"] == 2
