"""The tiered SLA. §9.2, §9.3, T-TIME-01/02/03.

**Never auto-approve.** The timers remind, then escalate, then keep waiting.
Only a human closes the KYC gate.
"""
import uuid
from datetime import timedelta

from python.models.onboarding import OnboardingResult
from python.models.review import ReviewAck
from tests.conftest import Stubs, run_worker


async def _start(env, queue):
    return await env.client.start_workflow(
        "OnboardingWorkflow",
        {"client_key": "acme-corp", "legal_name": "Acme Holdings LLC"},
        result_type=OnboardingResult,
        id=f"onboarding-acme-corp-{uuid.uuid4()}", task_queue=queue)


def _details(stubs) -> str:
    return " | ".join(n["detail"].lower() for n in stubs.notifications)


async def assert_remind_then_escalate_fire_in_order(skip_env, monkeypatch):
    monkeypatch.setenv("SLA_REMIND", "1h")
    monkeypatch.setenv("SLA_ESCALATE", "3h")
    stubs = Stubs()
    queue, worker = await run_worker(skip_env, stubs)
    async with worker:
        handle = await _start(skip_env, queue)
        await skip_env.sleep(timedelta(hours=2))
        assert "remind" in _details(stubs)
        assert "escalat" not in _details(stubs), "escalation fired too early"
        await skip_env.sleep(timedelta(hours=2))
        assert "escalat" in _details(stubs)
        assert (await handle.query("status"))["stage"] == "awaiting_review"


async def assert_never_auto_approves(skip_env, monkeypatch):
    """§9.2's rule is worthless without this test. A workflow that approves a
    KYC application because a timer fired is a compliance incident."""
    monkeypatch.setenv("SLA_REMIND", "1h")
    monkeypatch.setenv("SLA_ESCALATE", "2h")
    stubs = Stubs()
    queue, worker = await run_worker(skip_env, stubs)
    async with worker:
        handle = await _start(skip_env, queue)
        await skip_env.sleep(timedelta(days=365))
        status = await handle.query("status")
    assert status["stage"] == "awaiting_review", \
        "the workflow must still be waiting a year later"
    assert status["attempt"] == 1, "the SLA must not spend an attempt"


async def assert_client_id_sla_does_not_abandon_the_workflow(
        skip_env, monkeypatch):
    monkeypatch.setenv("CLIENT_ID_SLA", "1h")
    stubs = Stubs()
    queue, worker = await run_worker(skip_env, stubs)
    async with worker:
        handle = await _start(skip_env, queue)
        await _await_stage(skip_env, handle, "awaiting_review")
        await handle.execute_update(
            "submit_review",
            {"decision": "approve", "analyst_id": "kyc-7", "note": None,
             "field_edits": [], "attested": True}, result_type=ReviewAck)
        await _await_stage(skip_env, handle, "awaiting_client_id")
        await skip_env.sleep(timedelta(days=30))
        status = await handle.query("status")
    assert status["stage"] == "awaiting_client_id"
    assert "client id" in _details(stubs)


async def test_the_sla_timer_restarts_per_attempt(skip_env, monkeypatch):
    """§9.2 — the timer restarts per attempt."""
    monkeypatch.setenv("SLA_REMIND", "1h")
    monkeypatch.setenv("SLA_ESCALATE", "100h")
    stubs = Stubs()
    queue, worker = await run_worker(skip_env, stubs)
    async with worker:
        handle = await _start(skip_env, queue)
        await skip_env.sleep(timedelta(hours=2))
        first = _details(stubs).count("remind")
        await handle.execute_update(
            "submit_review",
            {"decision": "reject", "analyst_id": "kyc-7",
             "note": "missing EIN letter", "field_edits": [], "attested": False},
            result_type=ReviewAck)
        await _await_stage(skip_env, handle, "awaiting_review", attempt=2)
        await skip_env.sleep(timedelta(hours=2))
        second = _details(stubs).count("remind")
    assert first >= 1
    assert second > first, "the reminder must fire again on the new attempt"


async def test_the_client_id_chase_repeats_and_escalates(skip_env, monkeypatch):
    """§9.3 — the chase reminds, then escalates, and every round lands.

    `notify` dedupes on (client_key, outcome, recipients, detail), so a chase
    whose detail never varied would be recorded once and then silently
    swallowed for as long as the wait lasted."""
    monkeypatch.setenv("CLIENT_ID_SLA", "1h")
    stubs = Stubs()
    queue, worker = await run_worker(skip_env, stubs)
    async with worker:
        handle = await _start(skip_env, queue)
        await _await_stage(skip_env, handle, "awaiting_review")
        await handle.execute_update(
            "submit_review",
            {"decision": "approve", "analyst_id": "kyc-7", "note": None,
             "field_edits": [], "attested": True}, result_type=ReviewAck)
        await _await_stage(skip_env, handle, "awaiting_client_id")
        await skip_env.sleep(timedelta(hours=5))
        chases = [n for n in stubs.notifications
                  if "client id" in n["detail"].lower()]

    assert len(chases) >= 3, \
        f"every chase must be recorded, got {len(chases)}: {chases}"
    details = [n["detail"] for n in chases]
    assert len(set(details)) == len(details), \
        f"chase details must differ or notify dedupes them away: {details}"
    assert any("supervisor" in n["recipients"] for n in chases), \
        "§9.3 escalates as well as reminds -- a later chase must reach the supervisor"


async def test_the_escalation_timer_is_measured_from_when_the_gate_opened(
        skip_env, monkeypatch):
    """Both tiers are offsets from when the gate opened, not from each other.

    Chaining them -- starting a `SLA_ESCALATE - SLA_REMIND` timer only once
    the reminder's notify has returned -- pushes escalation past its own
    deadline by however long that activity took. The reminder here is
    deliberately slow so that duration is measurable: the escalation timer
    must come out SHORTER than the gap between the two SLAs, having absorbed
    it. Asserted against the timer recorded in history rather than against
    wall-clock arrival, so nothing here depends on scheduling luck."""
    monkeypatch.setenv("SLA_REMIND", "1h")
    monkeypatch.setenv("SLA_ESCALATE", "2h")
    stubs = Stubs()
    stubs.notify_delay = 2.0
    queue, worker = await run_worker(skip_env, stubs)
    async with worker:
        handle = await _start(skip_env, queue)
        await skip_env.sleep(timedelta(minutes=90))
        assert "remind" in _details(stubs)
        assert "escalat" not in _details(stubs), "escalation fired too early"
        await skip_env.sleep(timedelta(minutes=45))
        assert "escalat" in _details(stubs)
        assert (await handle.query("status"))["stage"] == "awaiting_review"
        timers = [e.timer_started_event_attributes.start_to_fire_timeout.ToTimedelta()
                  async for e in handle.fetch_history_events()
                  if e.HasField("timer_started_event_attributes")]

    assert len(timers) >= 2, f"expected both SLA tiers to start a timer: {timers}"
    remind, escalate = timers[0], timers[1]
    assert remind == timedelta(hours=1)
    assert escalate < timedelta(hours=1), (
        f"the escalation timer is {escalate}, the whole SLA_ESCALATE - "
        f"SLA_REMIND gap -- so it was started from the end of the reminder "
        f"rather than from when the gate opened, and escalation lands late by "
        f"however long the reminder's notify took")


async def test_escalate_not_after_remind_still_fires_both_tiers(
        skip_env, monkeypatch):
    """A misconfigured SLA_ESCALATE <= SLA_REMIND must not wait a negative
    timeout. Both tiers fire; the gate still never auto-approves."""
    monkeypatch.setenv("SLA_REMIND", "2h")
    monkeypatch.setenv("SLA_ESCALATE", "1h")
    stubs = Stubs()
    queue, worker = await run_worker(skip_env, stubs)
    async with worker:
        handle = await _start(skip_env, queue)
        await skip_env.sleep(timedelta(hours=3))
        details = _details(stubs)
        status = await handle.query("status")
    assert "remind" in details and "escalat" in details
    assert status["stage"] == "awaiting_review", "still never auto-approves"


async def _await_stage(env, handle, stage: str, attempt: int | None = None):
    """Time-skipping auto-advances when the workflow is idle, so nudge it
    forward in small steps rather than polling in real time."""
    status = None
    for _ in range(200):
        status = await handle.query("status")
        if status["stage"] == stage and (attempt is None
                                         or status["attempt"] == attempt):
            return status
        await env.sleep(timedelta(seconds=1))
    raise AssertionError(f"never reached {stage!r}; last was {status}")
