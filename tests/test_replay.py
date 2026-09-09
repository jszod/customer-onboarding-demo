"""Replay tests — §16.5, the highest-value gate.

`Replayer` re-runs committed histories against the CURRENT workflow code and
fails on the first command that does not match what the history recorded. That
catches the failure mode an autonomous agent causes most often: an
innocent-looking edit to workflow code that breaks determinism, which every
other test in this suite passes straight through.

Nothing here needs a server, an API key, or a running stack — the histories are
committed. They are captured by `make histories` against a live stack and are
never hand-authored; a hand-written history guards nothing.

The four scenario bodies are named `assert_...` so pytest collects them once,
through the manifest (see `tests/test_manifest.py`'s docstring).
"""
from __future__ import annotations

import json
from pathlib import Path

from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer

from python import config
from python.workflows.extraction import ExtractionAgentWorkflow
from python.workflows.onboarding import OnboardingWorkflow

HISTORIES = Path(__file__).resolve().parent.parent / "histories"
SCENARIOS = ("happy-path", "reject-loop", "timeout-retry", "escalation")


async def _replay(name: str) -> None:
    path = HISTORIES / f"{name}.json"
    assert path.exists(), (
        f"{path} is missing. Run `make histories` against a live stack "
        f"(§16.7 step 4). Do not hand-author histories.")
    await _replay_file(path, [OnboardingWorkflow, ExtractionAgentWorkflow])


async def _replay_file(path: Path, workflows: list) -> None:
    raw = json.loads(path.read_text())
    replayer = Replayer(workflows=workflows,
                        data_converter=config.build_data_converter())
    await replayer.replay_workflow(WorkflowHistory.from_json(_workflow_id(raw), raw))


def _workflow_id(raw: dict) -> str:
    """`WorkflowHistory.from_json`'s first argument is the WORKFLOW ID, not a
    run id or a label, and it is not decoration: the parent builds its child's
    id from `workflow.info().workflow_id` (§7), so replaying under an invented
    id produces a child-id mismatch reported as a nondeterminism error in code
    nobody touched. The started event carries the real one -- read it from the
    history rather than deriving it from the file name, which would drift."""
    started = raw["events"][0].get("workflowExecutionStartedEventAttributes", {})
    workflow_id = started.get("workflowId")
    assert workflow_id, (
        "the first event is not a WorkflowExecutionStarted carrying a "
        "workflowId; this history was not captured by `make histories`")
    return workflow_id


# --- the four manifest scenarios -------------------------------------------

async def assert_happy_path_replays() -> None:
    await _replay("happy-path")


async def assert_reject_loop_replays() -> None:
    await _replay("reject-loop")


async def assert_timeout_retry_replays() -> None:
    await _replay("timeout-retry")


async def assert_escalation_replays() -> None:
    await _replay("escalation")


# --- everything else --------------------------------------------------------

async def test_histories_cover_the_child_workflow_too():
    """The child has its own history; a determinism break there is just as
    fatal and just as easy to introduce."""
    child = sorted(HISTORIES.glob("*-extract-*.json"))
    assert child, "capture at least one child workflow history"
    for path in child:
        await _replay_file(path, [ExtractionAgentWorkflow])


def test_every_committed_history_is_named_by_a_scenario():
    """A history file nobody replays is a file nobody notices going stale.
    Every `.json` under `histories/` is either one of the four scenarios or a
    child of one, and both sets are replayed above."""
    orphans = [p.name for p in HISTORIES.glob("*.json")
               if p.stem not in SCENARIOS
               and not any(p.stem.startswith(f"{s}-extract-") for s in SCENARIOS)]
    assert not orphans, (
        f"histories/ holds files no test replays: {orphans}. Either add the "
        f"scenario to SCENARIOS (and to the manifest, with a ruling) or delete "
        f"the file.")
