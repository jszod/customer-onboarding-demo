"""§17.1 — the stages are padded so a live audience can watch them.

The stubbed stages complete in milliseconds, so the stepper jumps 1 -> 3 before
anyone in the room has read it. `DEMO_STEP_MS` pads them. Default 0, so the
suite pays nothing.

Two of these tests exist because the failure mode is *silent*: a `time.sleep`
in an `async def` activity does not raise, it just serialises the entire
worker.
"""
import asyncio
import time
from pathlib import Path

import pytest

from python import config

ROOT = Path(__file__).resolve().parents[1]
PACED = {
    "python/activities/ingest.py": "ingest_documents",
    "python/activities/delivery.py": "send_documents",
}


def test_demo_pause_is_off_by_default(monkeypatch):
    """Default 0 keeps `make verify` at its current runtime. A suite that pays
    the demo's pacing is a suite people stop running."""
    monkeypatch.delenv("DEMO_STEP_MS", raising=False)
    assert config.settings().demo_step_ms == 0


@pytest.mark.asyncio
async def test_demo_pause_returns_immediately_when_unset(monkeypatch):
    monkeypatch.delenv("DEMO_STEP_MS", raising=False)
    started = time.perf_counter()
    await config.demo_pause(2)
    assert time.perf_counter() - started < 0.05


@pytest.mark.asyncio
async def test_demo_pause_scales_by_its_multiplier(monkeypatch):
    monkeypatch.setenv("DEMO_STEP_MS", "40")
    started = time.perf_counter()
    await config.demo_pause(2)
    elapsed = time.perf_counter() - started
    assert 0.06 <= elapsed < 0.5, elapsed


@pytest.mark.asyncio
async def test_demo_pause_yields_the_event_loop(monkeypatch):
    """The whole point. A `time.sleep` here would stall every other activity,
    every workflow task and the worker's pollers, because the activities are
    `async def` sharing one loop. If this pause yields, other coroutines make
    progress while it waits."""
    monkeypatch.setenv("DEMO_STEP_MS", "60")
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.005)
            ticks += 1

    task = asyncio.create_task(ticker())
    await config.demo_pause(1)
    task.cancel()
    assert ticks > 2, f"the pause blocked the loop; only {ticks} ticks"


def test_no_blocking_sleep_in_any_activity():
    """§17.1. A blocking sleep in an `async def` activity stalls the shared
    loop. Written as a source grep because the failure is silent: everything
    still works, just serially and slowly, and no test would otherwise
    notice."""
    offenders = []
    for path in (ROOT / "python" / "activities").rglob("*.py"):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            code = line.split("#", 1)[0]
            if "time.sleep" in code:
                offenders.append(f"{path.name}:{n}")
    assert not offenders, f"blocking sleep in an async activity: {offenders}"


def test_the_paced_activities_await_the_pause():
    """A pause nobody calls is a knob that does nothing."""
    missing = [f for f, _ in PACED.items()
               if "demo_pause(" not in (ROOT / f).read_text()]
    assert not missing, f"not paced: {missing}"


def test_live_extraction_is_not_padded():
    """§17.1 — a live model call already takes real seconds. Only the
    fixture-backed path is padded."""
    src = (ROOT / "python" / "activities" / "llm.py").read_text()
    live = src[src.index("async def live_call_llm"):src.index("async def fixture_call_llm")]
    assert "demo_pause(" not in live
    assert "demo_pause(" in src[src.index("async def fixture_call_llm"):]


def test_open_account_is_never_padded():
    """§10.1 — its 5s start_to_close_timeout IS the headline beat. Padding it
    either eats the margin or fires the timeout spuriously."""
    src = (ROOT / "python" / "activities" / "core_banking.py").read_text()
    assert "demo_pause(" not in src
