"""The ambiguous timeout and the core rejection. §10.1, §10.3, T-WF-07/08.

The headline: a `start_to_close_timeout` firing does not cancel the server's
work. The work happened, the answer was lost. Retry alone opens a second
account; retry plus a stable key does not.
"""
import asyncio
import uuid

from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import (SandboxedWorkflowRunner,
                                                SandboxRestrictions)

from python.models.core_banking import OpenAccountAck, OpenAccountRequest
from python.models.onboarding import OnboardingResult
from python.models.review import ReviewAck
from python.workflows.onboarding import OnboardingWorkflow
from tests.conftest import Stubs
from tests.test_onboarding_workflow import APPROVE, _wait_for


def _worker_with(env, stubs: Stubs, open_account_stub):
    """The standard stub set with `open_account` swapped for this test's."""
    queue = str(uuid.uuid4())
    acts = [a for a in stubs.activities()
            if a.__temporal_activity_definition.name != "open_account"]
    worker = Worker(
        env.client, task_queue=queue,
        workflows=[OnboardingWorkflow, stubs.child()],
        activities=acts + [open_account_stub],
        workflow_runner=SandboxedWorkflowRunner(
            restrictions=SandboxRestrictions.default.with_passthrough_modules(
                "tests")))
    return queue, worker


async def _to_core(env, queue):
    handle = await env.client.start_workflow(
        "OnboardingWorkflow",
        {"client_key": "acme-corp", "legal_name": "Acme Holdings LLC"},
        result_type=OnboardingResult,
        id=f"onboarding-acme-corp-{uuid.uuid4()}", task_queue=queue)
    await _wait_for(handle, "awaiting_review")
    await handle.execute_update("submit_review", APPROVE, result_type=ReviewAck)
    return handle


async def assert_timeout_then_duplicate_opens_exactly_one_account(env):
    """THE HEADLINE (§10.1). The activity times out while the service keeps
    working; the retry carries the SAME key and gets `duplicate`."""
    seen_keys: list[str] = []
    calls = {"n": 0}

    @activity.defn(name="open_account")
    async def flaky(req: OpenAccountRequest) -> OpenAccountAck:
        seen_keys.append(req.idempotency_key)
        calls["n"] += 1
        if calls["n"] == 1:
            # The service created the account and then failed to answer. Only
            # needs to exceed the 5s start_to_close; the spec's 10s is the
            # demo service's behaviour, not a requirement on this test.
            await asyncio.sleep(8)
        return OpenAccountAck(request_id="REQ-ORIGINAL", status="duplicate")

    stubs = Stubs()
    queue, worker = _worker_with(env, stubs, flaky)
    async with worker:
        handle = await _to_core(env, queue)
        await _wait_for(handle, "awaiting_client_id", timeout=60)
        status = await handle.query("status")

    assert calls["n"] == 2, "the activity must have retried"
    assert len(set(seen_keys)) == 1, "the idempotency key must be stable"
    assert seen_keys[0].startswith("onboarding-acme-corp")
    assert status["core_request_id"] == "REQ-ORIGINAL"
    assert status["core_attempt"] >= 2


async def test_the_timeout_is_visible_in_status_while_it_retries(env):
    """§13 — the console reads `core_attempt` and `last_error` live. This is
    the reason the retry is a workflow loop rather than the activity policy."""
    calls = {"n": 0}

    @activity.defn(name="open_account")
    async def flaky(req: OpenAccountRequest) -> OpenAccountAck:
        calls["n"] += 1
        if calls["n"] == 1:
            await asyncio.sleep(8)
        return OpenAccountAck(request_id="REQ-ORIGINAL", status="duplicate")

    stubs = Stubs()
    queue, worker = _worker_with(env, stubs, flaky)
    async with worker:
        handle = await _to_core(env, queue)
        seen = None
        for _ in range(300):
            status = await handle.query("status")
            if status["stage"] == "submitting_to_core" and status["last_error"]:
                seen = status
                break
            if status["stage"] == "awaiting_client_id":
                break
            await asyncio.sleep(0.1)
        await _wait_for(handle, "awaiting_client_id", timeout=60)

    assert seen is not None, "the failed attempt never showed in status"
    assert seen["core_attempt"] >= 1
    assert "attempt 1" in seen["last_error"]


async def assert_core_rejection_completes_as_rejected_by_core(env):
    """§10.3 — a completed workflow with a business status, not a crash."""

    @activity.defn(name="open_account")
    async def rejecting(req: OpenAccountRequest) -> OpenAccountAck:
        raise ApplicationError("entity not found in state registry",
                               type="CoreRejection", non_retryable=True)

    stubs = Stubs()
    queue, worker = _worker_with(env, stubs, rejecting)
    async with worker:
        handle = await _to_core(env, queue)
        result = await handle.result()

    assert result.status == "rejected_by_core"
    assert "state registry" in result.detail
    assert any(n["outcome"] == "rejected_by_core" for n in stubs.notifications)


async def test_the_key_is_the_parent_workflow_id(env):
    """§10.1's trap, asserted at the workflow level too."""
    captured = {}

    @activity.defn(name="open_account")
    async def capture(req: OpenAccountRequest) -> OpenAccountAck:
        captured["key"] = req.idempotency_key
        return OpenAccountAck(request_id="REQ-1", status="accepted")

    stubs = Stubs()
    queue, worker = _worker_with(env, stubs, capture)
    async with worker:
        handle = await _to_core(env, queue)
        await _wait_for(handle, "awaiting_client_id")
    assert captured["key"] == handle.id


async def assert_first_attempt_duplicate_is_already_onboarded(env):
    """§10.1.1, T-WF-10. `duplicate` on attempt 1 means a PREVIOUS onboarding
    owns the account -- nothing in this run created anything.

    T-WF-07 is the attempt-2 case, where the same answer means "our own call
    landed and the reply was lost". The pair is what proves the workflow tells
    them apart; either one alone passes against code that conflates them.

    The property that matters is the last assertion: the end client is never
    told about an account they have held for months. The specialist and the
    supervisor are, because a repeat onboarding attempt on an existing client
    is a compliance event that wants a record (§5.5.1)."""
    calls = {"n": 0}

    @activity.defn(name="open_account")
    async def already_there(req: OpenAccountRequest) -> OpenAccountAck:
        calls["n"] += 1
        return OpenAccountAck(request_id="REQ-PRIOR", status="duplicate")

    stubs = Stubs()
    queue, worker = _worker_with(env, stubs, already_there)
    async with worker:
        handle = await _to_core(env, queue)
        # Wait on the STAGE, not on the result. Against code that conflates the
        # two duplicates the workflow sails past the core call into
        # `awaiting_client_id` and blocks on a signal that never comes, so
        # `handle.result()` hangs the suite instead of failing it. `_wait_for`
        # bounds that to 20s and names the stage it actually reached.
        status = await _wait_for(handle, "already_onboarded", timeout=30)
        result: OnboardingResult = await handle.result()

    assert result.status == "already_onboarded", result.status
    assert result.client_id is None, "this run opened no account"
    assert calls["n"] == 1, "nothing was ambiguous, so nothing should retry"

    assert status["stage"] == "already_onboarded"
    assert status["core_duplicate"] is True
    assert status["core_preexisting"] is True, \
        "a duplicate on attempt 1 is a pre-existing account, not the beat"
    assert status["core_request_id"] == "REQ-PRIOR"

    assert len(stubs.notifications) == 1, stubs.notifications
    note = stubs.notifications[0]
    assert note["outcome"] == "already_onboarded"
    assert note["packet_uri"] is None, "the welcome pack must not have been sent"
    assert "end_client" not in note["recipients"], \
        "the client must never be told about an account they already had"
    assert set(note["recipients"]) == {"onboarding_specialist", "supervisor"}
