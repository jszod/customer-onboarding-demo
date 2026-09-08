---
paths:
  - "python/models/**/*.py"
  - "python/activities/**/*.py"
  - "python/config.py"
  - "web/**/*.py"
  - "core_banking/**/*.py"
---

# Payload and activity rules

Spec §5, §8.3, §10.2, §17.

## One Pydantic model per handler

Every workflow, activity, signal, update, and query takes **exactly one**
Pydantic model, or nothing — and returns one model, or nothing. No positional
argument lists anywhere, including single-field payloads, and including return
types.

`core/versioning.md` lists *"changing arguments passed to activities or child
workflows"* as a breaking change. Adding a parameter changes arity and breaks
replay for in-flight runs; adding an optional field to a model does not. This
demo gets edited between customer calls, so it matters more here than usual.

`IngestRequest` wrapping one `client_key` looks like overkill and is exactly
what saves you when a second field is needed.

## Pydantic, not dataclasses

Payloads carry `date`, `Decimal`, nested models, `Literal` enums, and a
discriminated union. The default converter degrades those on the way back — a
date returns as a string, a `Decimal` as a float, and we validate a sum over
`ownership_pct`. Pydantic reconstructs them, validates on deserialization, and
generates the JSON schema handed to Claude for structured extraction.

## The data converter is built in one place

`config.build_data_converter()`. Every process that talks to Temporal uses it:
worker, gateway, core-banking callback, tests. A mismatch produces
deserialization errors that look like data corruption rather than
configuration.

That single construction point is also the seam for enabling a `PayloadCodec`
later — a stated scope cut (§18), not an oversight.

## Error classification lives inside the activity

Raise `ApplicationError(..., non_retryable=True)` from within the activity.
Do **not** list `non_retryable_error_types` at the call site. One source of
truth, and correct retry behaviour then falls out of merely calling the
activity.

The classification for model calls: 401 / content policy / invalid input are
non-retryable; 429 sets `next_retry_delay` parsed from the `retry-after`
header; 5xx and connection errors are retryable.

## LLM client retries are disabled

`max_retries=0`. Temporal owns all retry behaviour. A client that retries
internally hides attempts from the history and from the console.

## No blocking I/O inside `async def`

`open()`, `Path.read_text()`, `sqlite3`, `time.sleep` and blocking HTTP all
stall the event loop and every other activity the worker is running. Use
`asyncio.to_thread`, or make the handler `def` and let the SDK run it in the
thread pool.

This is the single most repeated defect in this build — three instances so far:
the gateway's control and assign endpoints, and `open_account`. Assume it is in
any `async def` you write until you have checked.

## Activities are idempotent

Temporal re-executes activities on retry and replay. `send_documents` writes to
a deterministic path derived from `client_key` + `client_id`, so a retry
overwrites rather than duplicating. `notify` keys its records so a retry does
not double-send.

## The gateway imports zero worker code

`web/gateway.py` drives workflows by **string name** only. That is what makes
`CONTRACT.md` real rather than aspirational, and it is what would let a Go or
TypeScript worker replace the Python one without touching the gateway.

The cost of the string name is that nothing can infer the types: every
`execute_workflow`, `start_workflow`, `query` and `execute_update` needs an
explicit `result_type=`, or the converter hands back a bare `dict` that looks
like a model until something touches an attribute.

The receiving end has the mirror obligation: every activity handler annotates
its parameter (`async def open_account(req: OpenAccountRequest)`). Without the
annotation the activity is handed a `dict`, raises on first attribute access,
and then retries on the default unlimited policy — so the symptom is a hung
caller rather than an error. Test stubs are handlers too.

`core_banking/` never imports `temporalio` at all — it only speaks HTTP.

## The transcript never ends on an assistant turn

`call_llm` renders an `AgentTurn` with `role="assistant"` as an assistant
message. An assistant message in last position is an assistant **prefill**, and
prefill was removed across Claude 4.6+ — `claude-sonnet-5` included. It is a
permanent 400 (`This model does not support assistant message prefill`), not a
transient one, so there is no retry that recovers.

Practically: **every non-terminal tool records its result** as an
`AgentTurn(role="tool", ...)`, which `call_llm` maps to a user message. Add a
tool, record its result — see `document_tool_turn()` and R-024. Never leave the
result unrecorded because "the next request re-renders it anyway": the content
may travel, but the transcript shape is what the API rejects.

An empty result string fails the same call for a different reason — the API
rejects empty content blocks too. Always say something.
