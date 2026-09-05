---
paths:
  - "python/workflows/**/*.py"
---

# Workflow code rules

These bind everything under `python/workflows/`. Spec §8, §10.3, §16.6.

## Determinism

No I/O, no clocks, no randomness. Specifically: no `requests`, no `httpx`, no
`datetime.now()`, no `time.time()`, no `random`. Use `workflow.now()` and
`workflow.uuid4()`. Everything non-deterministic goes in an activity.

`tests/test_determinism_guard.py` greps for these. The SDK sandbox catches most
of the rest at runtime.

## Configuration is read at import time, never inside `run()`

`config.settings()` reads `os.environ`, which the sandbox forbids during
workflow execution. Call it inside `workflow.unsafe.imports_passed_through()`
at module scope and bind the result to a module constant:

```python
with workflow.unsafe.imports_passed_through():
    from python import config
    SETTINGS = config.settings()
```

The sandbox is right to refuse: a workflow that re-read its config mid-run
would replay differently after an env change.

**Know the symptom, because it is not an error.** A restricted access fails the
workflow *task*, and workflow tasks retry forever. The test does not fail — it
hangs.

## A hanging test is a retry loop — go and read the log

Nothing here retries a bounded number of times by default: a failing workflow
task retries forever, and a failing activity retries on the default policy,
which is also unlimited. So a defect anywhere in that path presents as a test
that never returns, with no traceback and no failing assertion. Two places to
look, in this order:

1. **The worker log.** `Completing activity as failed` with a climbing
   `attempt` number names the activity and carries the real traceback.
2. **The history.** For a workflow-task failure, start the workflow rather than
   executing it, `asyncio.wait_for(handle.result(), timeout=25)`, then walk
   `handle.fetch_history_events()` and read the task-failure message.

Do not sit through the timeout a second time hoping for different output.

## Both ends of a call need types

**Calling:** `workflow.execute_activity("call_llm", req,
result_type=LLMResponse, ...)`. A type annotation on the receiving variable
deserializes nothing — the converter has no signature to infer from, so without
`result_type` it returns a bare `dict` and the next attribute access dies. Same
for `execute_child_workflow` and for `execute_workflow` from a client or a test.

**Receiving:** every activity, workflow, signal, update and query handler
annotates its parameter — `async def ingest(req: IngestRequest)`, never
`async def ingest(req)`. The converter builds the model from that annotation
and nothing else. This applies to test stubs exactly as it does to real
handlers; an unannotated stub is the most common way to hit it.

## `maximum_attempts=0` means UNLIMITED, not none

Zero is the default policy's value and is what §10.2 wants for `call_llm`. If
you intend no retry, that is `maximum_attempts=1`. Read the spec before
"fixing" a zero you find here — the classification inside the activity, not the
policy, is what stops a 401.

## Big things by reference, small things by value

Temporal records activity inputs **and** outputs. An agent loop that passes
document text into `call_llm` re-records every prior iteration's text on each
call — quadratic growth, and a plausible breach of the 2MB payload cap.

So workflow state holds document **ids**; the activity resolves them to text
itself. Document content never appears in a workflow argument, a return value,
or a tool result.

Any future activity-backed tool caps its result at 4KB before it enters
workflow state, with the full result retrievable from the store.

## Workflows never parse model output

`call_llm` returns already-validated Pydantic models. The workflow dispatches
on `action.kind` and stores the result. It never coerces dates, decimals, or
enums.

Three reasons: only known-good structures reach workflow state; malformed model
output becomes a retryable *activity* failure rather than a workflow exception;
and no parsing logic sits on the determinism-critical path, where a locale- or
clock-dependent parse would be a latent replay bug.

## Inline tools vs activities

The extraction child has **exactly one** activity, `call_llm`. Its three tools
— `request_documents`, `submit_extraction`, `escalate` — are inline workflow
functions, because each mutates only agent state.

This is the line `core/ai-patterns.md` draws: Pattern 2 puts file-system and
API work in activities; Pattern 3 puts deterministic state mutations in
workflow code. Nothing in the tool set reads the disk.

If you add a tool that needs I/O, it becomes an activity. If it only edits
workflow state, keep it inline.

## Escalation is a return value, never an exception

`ExtractionResult(escalated=True)` with populated `gaps`. A missing date of
birth is a compliance-normal outcome; raising would surface it as a red failed
workflow.

The same principle governs the parent: a `ChildWorkflowError` spends an
attempt, a non-retryable core rejection completes as `rejected_by_core`, and
exhausting attempts completes as `manual_intervention`. **Every path ends in a
business status.**

## The idempotency key

`open_account`'s key is the **parent workflow ID**, stable across every retry.
Never derive it from `activity.info().attempt` — that is the intuitive move,
since the SDK exposes it, and it produces exactly the duplicate account the
whole design prevents.

## Never auto-approve

The KYC gate's timers remind, then escalate, then keep waiting indefinitely.
The workflow must never approve because a timer fired. `T-TIME-02` advances a
year and asserts the stage is still `awaiting_review`.
