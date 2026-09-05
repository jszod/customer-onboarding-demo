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


async def test_T_TIME_01_remind_then_escalate_fire_in_order(skip_env, monkeypatch):
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


async def test_T_TIME_02_never_auto_approves(skip_env, monkeypatch):
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


async def test_T_TIME_03_client_id_sla_does_not_abandon_the_workflow(
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
