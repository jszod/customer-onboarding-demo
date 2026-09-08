"""Captures workflow histories for the replay tests. §16.7 step 4.

Drives a LIVE stack through four scenarios and downloads each history --
parent and children. Regenerate deliberately and commit the result: these
files are the determinism gate, so a stale history silently stops guarding.

    make up      # temporal + core banking + gateway + worker
    make histories

Run the stack with `FIXTURE_MODE=1` (`FIXTURE_MODE=1 make up`) unless you mean
to spend a real API key. §16.7 puts the fixtures before the histories for
exactly this reason -- a recorded extraction is what makes a captured run
reproducible, and the child history is a record of the loop the fixtures drive.

The four scenarios share one workflow id, `onboarding-acme-corp`, because §7's
id is derived from the client key. So they run strictly in sequence, each after
the previous run has closed, and `_reset` terminates a leftover open run so a
second capture does not wedge on the 409 the id is there to produce.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

# Run from anywhere: `python tools/capture_histories.py` puts `tools/` on the
# path, not the repo root, so the `python.*` imports below would fail. pytest
# gets this from pyproject's `pythonpath = ["."]`; a plain script does not.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from python import config

OUT = ROOT / "histories"
CLIENT = "acme-corp"

APPROVE = {"decision": "approve", "analyst_id": "kyc-analyst-1", "note": None,
           "field_edits": [{"field_path": "beneficial_owners[1].dob",
                            "value": "1985-01-01"}],
           "attested": True}
REJECT = {"decision": "reject", "analyst_id": "kyc-analyst-1",
          "note": "missing the EIN letter", "field_edits": [], "attested": False}


def gw() -> str:
    return config.settings().gateway_url


def core() -> str:
    return config.settings().core_banking_url


async def _status(http: httpx.AsyncClient) -> dict | None:
    r = await http.get(f"{gw()}/api/status/{CLIENT}")
    return r.json() if r.status_code == 200 else None


async def _wait(http: httpx.AsyncClient, what: str, predicate,
                timeout: float = 120) -> dict:
    """Poll the query until `predicate(status)` holds.

    A predicate rather than a stage name because two of these waits follow a
    decision that leaves the stage unchanged for a moment: after a rejection
    the workflow is still `awaiting_review` on attempt 1 for as long as it
    takes to re-ingest, and a bare stage match would return the state we were
    trying to leave.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    last = None
    while asyncio.get_running_loop().time() < deadline:
        last = await _status(http)
        if last and predicate(last):
            return last
        await asyncio.sleep(0.5)
    raise SystemExit(f"never reached {what} within {timeout:.0f}s "
                     f"(last status: {last}). Check `make logs`.")


def _stage(name: str):
    return lambda st: st["stage"] == name


async def _preflight(http: httpx.AsyncClient) -> None:
    for name, url in (("gateway", f"{gw()}/"), ("core banking", f"{core()}/ledger")):
        try:
            await http.get(url)
        except httpx.HTTPError as e:
            raise SystemExit(f"{name} is not answering at {url} ({e}). "
                             f"Start the stack first: FIXTURE_MODE=1 make up")


async def _reset(client: Client, http: httpx.AsyncClient) -> None:
    """Clear application state and start a fresh onboarding.

    The terminate is what makes this tool re-runnable: the escalation scenario
    deliberately leaves its workflow open at `awaiting_review`, and a second
    capture would otherwise be told -- correctly -- that an onboarding is
    already in progress for this client.
    """
    handle = client.get_workflow_handle(f"onboarding-{CLIENT}")
    try:
        if (await handle.describe()).status.name == "RUNNING":
            await handle.terminate("superseded by a fresh history capture")
    except RPCError as e:
        if e.status != RPCStatusCode.NOT_FOUND:
            raise

    await asyncio.to_thread(subprocess.run,
                            ["make", "-C", str(ROOT), "demo-reset"], check=True)

    r = await http.post(f"{gw()}/applications", json={"client_key": CLIENT})
    if r.status_code != 202:
        raise SystemExit(f"POST /applications returned {r.status_code}: {r.text}")


async def _save(client: Client, name: str) -> None:
    """Write the parent's history and the children THIS run started.

    The children are read out of the parent's own history rather than guessed
    at by id. Child ids are derived from the parent id (§7), so
    `onboarding-acme-corp-extract-2` exists as soon as ANY earlier run reached
    attempt 2 -- a different scenario's, or a capture that failed halfway --
    and fetching it by id alone silently files a stale run under this
    scenario's name. `ChildWorkflowExecutionStarted` carries the run id, which
    is the only thing that says "this one, from this parent run".
    """
    OUT.mkdir(exist_ok=True)
    parent_id = f"onboarding-{CLIENT}"
    parent = await client.get_workflow_handle(parent_id).fetch_history()
    written = [_write(parent, OUT / f"{name}.json")]
    for child_id, run_id in _children_of(parent):
        history = await client.get_workflow_handle(
            child_id, run_id=run_id).fetch_history()
        # `-extract-N` -- the child's own suffix, so the file names the attempt
        # the child actually ran for.
        written.append(_write(history, OUT / f"{name}{child_id[len(parent_id):]}.json"))
    print(f"  {len(written)} file(s): {', '.join(p.name for p in written)}")


def _children_of(history) -> list[tuple[str, str]]:
    return [(e.child_workflow_execution_started_event_attributes
             .workflow_execution.workflow_id,
             e.child_workflow_execution_started_event_attributes
             .workflow_execution.run_id)
            for e in history.events
            if e.HasField("child_workflow_execution_started_event_attributes")]


def _write(history, path: Path) -> Path:
    path.write_text(json.dumps(json.loads(history.to_json()), indent=2) + "\n")
    return path


async def happy_path(client: Client, http: httpx.AsyncClient) -> None:
    await http.post(f"{core()}/control", json={"slow_first_call": False})
    await _reset(client, http)
    await _wait(http, "awaiting_review", _stage("awaiting_review"))
    await http.post(f"{gw()}/api/review/{CLIENT}", json=APPROVE)
    await _wait(http, "awaiting_client_id", _stage("awaiting_client_id"))
    await http.post(f"{gw()}/api/assign/{CLIENT}")
    await _wait(http, "complete", _stage("complete"))
    await _save(client, "happy-path")


async def reject_loop(client: Client, http: httpx.AsyncClient) -> None:
    """A rejection is a spent attempt: the loop re-ingests and re-extracts, so
    attempt 2 has its own child workflow and its own child history."""
    await http.post(f"{core()}/control", json={"slow_first_call": False})
    await _reset(client, http)
    await _wait(http, "awaiting_review", _stage("awaiting_review"))
    await http.post(f"{gw()}/api/review/{CLIENT}", json=REJECT)
    await _wait(http, "awaiting_review on attempt 2",
                lambda st: st["stage"] == "awaiting_review" and st["attempt"] == 2)
    await http.post(f"{gw()}/api/review/{CLIENT}", json=APPROVE)
    await _wait(http, "awaiting_client_id", _stage("awaiting_client_id"))
    await http.post(f"{gw()}/api/assign/{CLIENT}")
    await _wait(http, "complete", _stage("complete"))
    await _save(client, "reject-loop")


async def timeout_retry(client: Client, http: httpx.AsyncClient) -> None:
    """THE HEADLINE (§10.1). Core banking creates the account and then fails to
    answer inside the 5s timeout; the workflow retries with the same key, gets
    `duplicate`, and the ledger holds exactly one account."""
    await http.post(f"{core()}/control", json={"slow_first_call": True})
    await _reset(client, http)
    await _wait(http, "awaiting_review", _stage("awaiting_review"))
    await http.post(f"{gw()}/api/review/{CLIENT}", json=APPROVE)
    st = await _wait(http, "awaiting_client_id", _stage("awaiting_client_id"),
                     timeout=180)
    if st["core_attempt"] < 2:
        raise SystemExit("the headline is broken: core banking answered the "
                         "first call in time, so nothing was ever ambiguous")
    ledger = (await http.get(f"{core()}/ledger")).json()
    if len(ledger["accounts"]) != 1:
        raise SystemExit(f"the headline is broken: the ledger holds "
                         f"{len(ledger['accounts'])} accounts, not 1")
    await http.post(f"{gw()}/api/assign/{CLIENT}")
    await _wait(http, "complete", _stage("complete"))
    await _save(client, "timeout-retry")


async def escalation(client: Client, http: httpx.AsyncClient) -> None:
    """§8.4's deliberate gap. Approve is impossible until the gap is filled, so
    this history captures the workflow SITTING at `awaiting_review` with a live
    gap and a durable SLA timer running -- which is the state the escalation
    beat is narrated from, and one no completed history contains."""
    await http.post(f"{core()}/control", json={"slow_first_call": False})
    await _reset(client, http)
    st = await _wait(http, "awaiting_review", _stage("awaiting_review"))
    if not st["gaps"]:
        raise SystemExit("the escalation scenario needs a live gap; extraction "
                         "reported none. Is the worker in FIXTURE_MODE?")
    r = await http.post(f"{gw()}/api/review/{CLIENT}",
                        json=dict(APPROVE, field_edits=[]))
    if r.status_code != 422:
        raise SystemExit(f"the validator should have refused an approve with "
                         f"the gap unfilled; it returned {r.status_code}")
    await _save(client, "escalation")


def _knob(name: str, default: str) -> str:
    """The §17 knob as it was SET, not as `Settings` parsed it. `3d` is the
    thing to compare against `.env`; `3 days, 0:00:00` is a `timedelta.__str__`
    nobody can grep for."""
    return os.environ.get(name, default)


def _provenance() -> None:
    """The histories' equivalent of `fixtures/README.md`: what they were
    captured against, so a stale one can be recognised as stale.

    Everything here is read from THIS process's environment, which is the
    capture tool's -- not the worker's. `make histories` and `make up` are
    separate invocations, and nothing in a history says which mode the worker
    was in. Hence the wording below: this is the environment the capture was
    RUN under, and the instruction is to bring the stack up the same way.
    """
    (OUT / "README.md").write_text(f"""\
# Committed workflow histories

Captured by `make histories` (`tools/capture_histories.py`) against a live
stack. **Never hand-authored** — a hand-written history guards nothing.
`tests/test_replay.py` replays every file here against the current workflow
code; §16.5 calls that the highest-value gate in the suite.

Captured: {datetime.now(UTC).strftime('%Y-%m-%d')}
Capture ran with: `FIXTURE_MODE={_knob('FIXTURE_MODE', '0')}` \
({'keyless, off the committed recording' if _knob('FIXTURE_MODE', '0') == '1'
   else 'live API'}) — bring the worker up the same way (`make up` reads the
same variables), or the run is not the one this file describes.

| §17 knob | Value at capture |
|----------|------------------|
| `MAX_ATTEMPTS` | `{_knob('MAX_ATTEMPTS', '3')}` |
| `MAX_ITERATIONS` | `{_knob('MAX_ITERATIONS', '8')}` |
| `SLA_REMIND` | `{_knob('SLA_REMIND', '3d')}` |
| `SLA_ESCALATE` | `{_knob('SLA_ESCALATE', '7d')}` |
| `CLIENT_ID_SLA` | `{_knob('CLIENT_ID_SLA', '1d')}` |
| `CORE_SLOW_MS` | `{_knob('CORE_SLOW_MS', '10000')}` |

The SLA row matters more than it looks. Replay re-runs the workflow's own
branching, and `_await_review` asks whether a deadline is already behind it
before deciding to start a timer. Capture with the DEFAULT SLAs and answer
promptly, as this tool does, and both the capture and the replay take the
"start a timer" branch. Capture under the demo profile's 30s/60s while
something waits a minute, and the branch differs — which is a replay failure
reported as non-determinism in code nobody touched.

**Re-capture when** the workflow's command sequence legitimately changes: a new
activity, a reordered step, a different child id. That is a deliberate act, and
the diff is reviewed. Re-capturing to make a red replay test go green is how
the gate stops guarding — read the failure first.

| File | Scenario |
|------|----------|
| `happy-path.json` | Approve on the first attempt, straight through to `complete` |
| `reject-loop.json` | Reject, re-ingest, approve on attempt 2 (two child histories) |
| `timeout-retry.json` | §10.1's ambiguous timeout: retry, `duplicate`, one account |
| `escalation.json` | Still open at `awaiting_review` with §8.4's gap unfilled |
| `*-extract-N.json` | The extraction child of attempt N of that scenario |
""")


async def main() -> None:
    s = config.settings()
    client = await Client.connect(s.temporal_address,
                                  data_converter=config.build_data_converter())
    async with httpx.AsyncClient(timeout=30.0) as http:
        await _preflight(http)
        for scenario in (happy_path, reject_loop, timeout_retry, escalation):
            print(f"--- {scenario.__name__}")
            await scenario(client, http)
    OUT.mkdir(exist_ok=True)
    _provenance()
    print(f"\nwrote {len(list(OUT.glob('*.json')))} histories to {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
