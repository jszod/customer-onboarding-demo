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

## Activities are idempotent

Temporal re-executes activities on retry and replay. `send_documents` writes to
a deterministic path derived from `client_key` + `client_id`, so a retry
overwrites rather than duplicating. `notify` keys its records so a retry does
not double-send.

## The gateway imports zero worker code

`web/gateway.py` drives workflows by **string name** only. That is what makes
`CONTRACT.md` real rather than aspirational, and it is what would let a Go or
TypeScript worker replace the Python one without touching the gateway.

`core_banking/` never imports `temporalio` at all — it only speaks HTTP.
