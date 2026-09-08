# Committed workflow histories

Captured by `make histories` (`tools/capture_histories.py`) against a live
stack. **Never hand-authored** — a hand-written history guards nothing.
`tests/test_replay.py` replays every file here against the current workflow
code; §16.5 calls that the highest-value gate in the suite.

Captured: 2026-09-08
Capture ran with: `FIXTURE_MODE=1` (keyless, off the committed recording) — bring the worker up the same way (`make up` reads the
same variables), or the run is not the one this file describes.

| §17 knob | Value at capture |
|----------|------------------|
| `MAX_ATTEMPTS` | `3` |
| `MAX_ITERATIONS` | `8` |
| `SLA_REMIND` | `3d` |
| `SLA_ESCALATE` | `7d` |
| `CLIENT_ID_SLA` | `1d` |
| `CORE_SLOW_MS` | `10000` |

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
