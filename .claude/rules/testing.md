---
paths:
  - "tests/**/*.py"
  - "fixtures/**"
  - "histories/**"
  - "tools/**/*.py"
---

# Testing rules

Spec §16.

## The manifest is the definition of done

`tests/test_manifest.py` holds all 22 scenarios by stable ID. The build is
complete when all 22 pass and none are skipped; `make verify` asserts
`skipped == 0`.

**Reuse the manifest's exact test names.** Do not invent parallel names — the
manifest is the authoritative list, and a scenario implemented under a
different name leaves a skip behind that reads as remaining work forever.

Adding a scenario is allowed: add a row with a new ID and log the addition as a
ruling. **Silently dropping one is not.**

## Stubs and fixtures are different things

| | Stub | Fixture |
|---|---|---|
| What | a canned value a test constructs inline | a recorded real model response in `fixtures/` |
| Hand-written? | **yes — correct and expected** | **never** |
| Tests | control flow: does the workflow branch correctly | realism: does the loop actually find `tax_id` in the W-9 |

**"Never hand-written" applies only to fixtures.** A hand-written fixture
drifts from real model output and silently stops testing anything while still
appearing to. A hand-written stub is an ordinary test double.

If a recorded run doesn't produce the behaviour you wanted, **change the prompt
and re-record** — do not edit the fixture. Editing it is the exact failure this
rule exists to prevent.

`FIXTURE_MODE=1` selects the fixture-backed `call_llm`. It has nothing to do
with stubs.

## Re-record fixtures only when

The prompt changes, `ApplicationFields` changes, or the document set changes.
`fixtures/README.md` carries the provenance so a stale fixture can be
recognised as stale. Review the diff.

## A test that greps source makes the prose in that file part of the test

Several gates here scan source text — `execute_activity` appears exactly once
in the extraction child, `"temporalio"` never appears in `core_banking/`,
`"info().attempt"` never appears in `open_account`. A docstring or comment that
*names the forbidden thing in order to warn about it* fails the gate as surely
as real code would.

This has already happened twice, both times to a docstring the plan itself
supplied. Write around the string: "a retry counter", not the expression.

## Grepping a page proves the string is there, not that the page works

`tests/test_console.py` reads `web/static/index.html` as text and asserts
substrings. That is a reasonable structural gate and it is all it is: every one
of those tests passes against a page whose JavaScript throws on load.

So when you change console behaviour, check the behaviour:

- `node --check` on the extracted `<script>` catches a syntax error in seconds.
- A headless browser catches the rest. Chromium is available at
  `/opt/pw-browsers/`, and `uv run --with playwright` gets the driver without
  touching `pyproject.toml`. Stub the gateway's routes, drive the control, and
  assert on the intercepted request body.

R-018 did exactly this for the editable field table, and the check is what
turned "the substring is present" into "the analyst's correction reaches
`field_edits`".

## Test environments

Use `WorkflowEnvironment.start_local()` for most tests; it is shareable via a
pytest fixture. Use `start_time_skipping()` **only** for the SLA-timer tests —
time-skipping environments cannot be shared between tests.

## Histories are captured, never authored

`make histories` drives a live stack and downloads the real histories. Do not
hand-write a history JSON file. Replay tests are the highest-value gate — they
catch the failure mode an autonomous agent causes most, an innocuous edit to
workflow code that breaks determinism — and a hand-authored history guards
nothing.

Capture the child workflow's history too. A determinism break there is just as
fatal and just as easy to introduce.

## `make test` needs no API key

It runs with `FIXTURE_MODE=1`. If a test you write requires `ANTHROPIC_API_KEY`,
it belongs in `make test-live`, not the default suite.

## A gate nobody has seen fail is not known to work

After wiring the determinism guard and the replay tests, deliberately break
determinism once, watch the gate fail, and revert.
