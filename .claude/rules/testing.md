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
- A headless browser catches the rest. `uv run --with playwright` gets the
  driver without touching `pyproject.toml`. Stub the gateway's routes, drive
  the control, and assert on the intercepted request body.

  **Getting a browser depends on where you are.** In a container, Chromium is
  at `/opt/pw-browsers/`. On macOS that path does not exist — use
  `p.chromium.launch(channel="chrome")`, which drives the Chrome already in
  `/Applications` and downloads nothing. Task 22 ran the whole visual audit
  that way. Reach for `playwright install chromium` only if neither is there.

R-022 did exactly this for the editable field table, and the check is what
turned "the substring is present" into "the analyst's correction reaches
`field_edits`".

### Never open the console over `file://`

The page's first act is `fetch("/api/status/" + CLIENT_KEY)`. Under `file://`
Chromium refuses the scheme, so the fetch throws, `#review` stays `hidden` and
`#detail` stays empty — the page renders its idle state and says "Gateway
unreachable". A browser check written that way is not weak, it is aimed at the
wrong screen: the review gate, the gap card, the error line and both alert
tones never exist. Give the page an `http://` origin and fulfil both the
document and `/api/status/*` from `page.route`; no server process is needed.
R-032 lost a whole contrast audit to this — it passed, against a page showing
none of what it was auditing.

### A check that skips a missing element is not a check

`if not el: continue` turns "this pair is absent" into "this pair passed". When
the element is supposed to be on screen, **assert it rendered**, then assert the
property. Absence is the more likely failure and the one that reports as green:
in R-032 three of four contrast selectors were silently skipped on every run.
The same goes for a grep whose subject can vanish — an audit over
`font-size: Npx` matches nothing once every size is a `var()`, so
`used <= ALLOWED` passes against any scale at all. Pin the token values too.

## Test environments

Use `WorkflowEnvironment.start_local()` for most tests; it is shareable via a
pytest fixture, and `env` **is** session-scoped — one dev server per run. Use
`start_time_skipping()` **only** for the SLA-timer tests, and leave `skip_env`
function-scoped: time-skipping environments cannot be shared between tests.

`tests/test_fixture_scopes.py` pins both scopes. They are not stylistic: one
server per *test* raced its own ports (three sightings of an intermittent
`Failed connecting to test server` fixture error), and one time-skipping
environment shared between tests would let a test that advances the clock a
year decide what "now" means for every test after it.

**A shared server is only safe while nothing shares names.** `run_worker`
takes a fresh uuid4 task queue and every workflow id carries a uuid4, so two
tests cannot see each other's workflows. A test that pins a fixed workflow id
or task queue breaks that — check before adding one.

## Fixture mode is a contract too, and it has its own unit

One recorded response is one model **call**, and a call adds one *assistant*
turn — never the whole transcript, which also carries tool turns. Indexing the
recording by `len(turns)` skips a response per tool result and dies as
`FixturesExhausted` on the second call of every real run, while every
hand-built unit test passes (R-026).

The general form: a fixture-backed activity and the recorder that wrote the
fixture must agree about the unit, and only running the real loop over the real
recording proves they do.
`test_the_committed_fixture_drives_the_real_loop` is that test — the child
workflow, `fixture_call_llm`, and `fixtures/acme-corp.json`, with nothing
stubbed. Keep one like it for any loop that fixtures drive.

## Histories are captured, never authored

`make histories` drives a live stack and downloads the real histories. Do not
hand-write a history JSON file. Replay tests are the highest-value gate — they
catch the failure mode an autonomous agent causes most, an innocuous edit to
workflow code that breaks determinism — and a hand-authored history guards
nothing.

Capture the child workflow's history too. A determinism break there is just as
fatal and just as easy to introduce — and capture it by **run id**, read out of
the parent's `ChildWorkflowExecutionStarted`. Child ids are derived from the
parent id (§7), so fetching `onboarding-acme-corp-extract-2` by id alone can
hand you a dead run from an earlier capture and file it under this scenario's
name (R-027).

**`WorkflowHistory.from_json`'s first argument is the workflow id**, not a
label. The parent builds its child's id from `workflow.info().workflow_id`, so
replaying under an invented id fails as a child-id mismatch — reported as
nondeterminism in code nobody touched, which is the worst false positive this
gate can produce. Read the id out of the started event.

A red replay test is a claim about the code, not about the file. Re-capturing
to make it green is how the gate stops guarding: read the failure first, and
re-capture only once you know the command sequence changed on purpose.

## `make test` needs no API key

It runs with `FIXTURE_MODE=1`. If a test you write requires `ANTHROPIC_API_KEY`,
it belongs in `make test-live`, not the default suite.

## A gate nobody has seen fail is not known to work

After wiring the determinism guard and the replay tests, deliberately break
determinism once, watch the gate fail, and revert.

## A script in `tools/` needs the repo root on `sys.path` itself

`pyproject.toml`'s `pythonpath = ["."]` applies to pytest, not to
`uv run python tools/whatever.py` — that puts `tools/` on the path, so any
`from python import ...` raises `ModuleNotFoundError` before the script's own
checks run. Every `make` target here invokes these as plain scripts.

Start any tool that imports the package with:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
```

`record_fixtures.py` shipped without it and would have failed on the one step a
human has to run themselves (R-023).

## A stub proves our side of a contract, not the contract

Every `call_llm` test hands `_create_message` a payload that already matches the
Pydantic models, and every child-workflow test stubs the activity out. Both are
correct, and both are blind to the two things a live call actually checks: the
shape of the request that goes out, and the schema the model is handed. R-024
found two merged, green defects that way — a transcript ending on an assistant
turn (a permanent 400) and terminal tools declaring `{"type": "object"}` for
their payloads.

So: assert on **what crosses the boundary**, not on the constant that feeds it.
Capture the kwargs `_create_message` receives and assert on those — a schema
written correctly in `prompts.TOOLS` but never sent is worth nothing.

And run the real thing once, deliberately, when a task first makes it possible.
`make fixtures` is that run for the model call. Same shape as R-022's rule for
the console: grepping the page is not driving it.

### A grep cannot see the cascade

`test_there_is_exactly_one_breakpoint` passed while the breakpoint did nothing.
Task 22 put `.cols { grid-template-columns: 1fr }` in a media block 115 lines
*above* the unconditional `.cols` rule; `@media` adds no specificity, so the
later rule won and the columns never collapsed. The text search found one
breakpoint, the right selector and the right value — and all three were true.

CSS behaviour is decided by cascade order, media state and DOM state. None of
those is text, so none of them is greppable. When you add a rule that is meant
to *override* another, put the override last and pin the order with a test that
compares source positions — then plant the regression and watch that test fail
before you believe it. R-033 has the worked example.
