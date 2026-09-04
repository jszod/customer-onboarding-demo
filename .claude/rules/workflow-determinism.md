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
