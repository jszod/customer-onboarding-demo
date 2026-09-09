# Execution log — rulings made during the build

Spec §19 pre-answers the seven ambiguities judged most likely. This file
records the ones it did not: decisions taken while implementing the plan,
where the spec and plan together left a gap or the plan's own code was wrong.

The plan expects this file to exist — Tasks 16 and 17 both say "record this as
a ruling in the execution log" — but no task creates it. Task 1 does.

Format: one entry per ruling, newest last. Say what was decided, against which
authority, and what it cost.

## Logging a ruling is half the job — promote it, or it will happen again

This file is append-only and nobody reads it top to bottom. A ruling buried at
entry 9 does not stop entry 14 from repeating it. Rules under `.claude/rules/`
are different: they load by path scope, so they arrive in front of the person
about to make the mistake.

**The rule of two.** Promote a ruling into the matching rules file when either
holds:

1. **It has now happened twice.** Two instances is not bad luck, it is a
   property of this codebase. Blocking I/O inside `async def` reached *three*
   instances while staying a ruling, because nothing said when to promote it.
2. **It will bite a task you can name.** R-012 was promoted on its first
   occurrence because Tasks 14–18 copy the extraction child's shape, and two of
   its three faults present as a hanging test rather than a failing one.

Which file: `workflow-determinism.md` for anything under `python/workflows/`,
`payloads-and-activities.md` for models, activities, config, web and core
banking, `testing.md` for the suite and its gates. Promotion **copies the
short form** — the rule states what to do and why in a few lines; the ruling
keeps the full reasoning and the cost. Leave the ruling in place and do not
rewrite history: the log is the record of how the rule was earned.

**When to check:** at each task's Commit step, before writing the message. That
is the moment the evidence is freshest and the cadence is already there.

---

## R-001 — `pgrep`/`pkill` guards must not match the invoking shell

**Task 1, Step 6. `make/common.mk`.**

**The problem.** The plan's Makefile guards read:

```make
@pgrep -f "web.gateway:app" >/dev/null 2>&1 || (start it)
```

`pgrep -f` matches against full command lines, and the make recipe runs in a
shell whose *own* command line contains the literal string `web.gateway:app`.
So pgrep matches itself, the guard always concludes "already running", and the
`||` branch never fires. Verified in this container: `make status` reported all
four processes running when none were — the Temporal CLI is not even installed
here. `make up` would have started nothing and printed the URLs anyway.

The same flaw made `pkill -f "python.worker"` in `kill-worker` able to kill the
make recipe's shell rather than the worker — which would have broken the
worker-kill demo beat (§10.4), the one place the demo deliberately kills a
process on stage.

**The ruling.** Keep the spec's approach — §14 line 873 mandates "`pgrep`
guards so targets are idempotent", and that is still what these are. Change
only the pattern, using the standard bracket idiom:

```make
@pgrep -f "[w]eb.gateway:app" >/dev/null 2>&1 || (start it)
```

`[w]eb…` matches the string `web…` in a real process's command line, but the
guard's own command line now contains `[w]eb…`, which the regex does not
match. Applied to all four process patterns in both `pgrep` and `pkill`.

**Authority.** Spec §14 mandates the mechanism, not the literal string; the
plan's string was simply wrong. No spec conflict — this makes the targets do
what §14 says they do. `make status` now correctly prints four "stopped" lines,
which is what the plan's own Step 8 predicts as the expected output.

**Cost.** None. Same mechanism, one character per pattern.

---

## R-002 — `CLAUDE.md` was merged, not overwritten

**Task 1, Step 7.**

The plan supplies a full `CLAUDE.md` to write. A richer one already existed
(committed in `d2262c6`), carrying the current-stage table, the §18 scope-cut
rule, the never-auto-approve-the-KYC-gate rule, the business-status rule, and
the note that subagents do not inherit the file. The plan's version has none of
those, but does have the determinism rule, which the existing one lacked.

**The ruling.** Merge: keep the existing file and add the plan's determinism
section, plus the document-content-never-enters-history and
one-place-data-converter rules. Update the stage line, which said no
implementation code exists. Writing the plan's version verbatim would have
deleted four standing rules to add one.

**Authority.** `docs/DEVELOPMENT-PROCESS.md` §"3. A `CLAUDE.md` at the repo
root" lists what the file must carry; the merged file carries all of it, and
the plan's would not have.

---

## R-003 — `apply_edits` dumps with `warnings=False`

**Task 2, Step 5. `python/gaps.py`.**

The plan's `apply_edits` sets the analyst's raw string onto a typed field, then
round-trips through `model_dump()` / `model_validate()` so the schema coerces
it. That works — both edit tests pass — but between the `setattr` and the
validate, a field declared `date` or `Decimal` is holding a `str`, and dumping
that intermediate state makes pydantic emit:

```
UserWarning: Pydantic serializer warnings:
  PydanticSerializationUnexpectedValue(Expected `date` — serialized value may
  not be as expected [field_name='dob', input_value='1985-01-01', input_type=str])
```

**The ruling.** Pass `warnings=False` to that one `model_dump()`, with a
comment saying why. The mis-typed intermediate is the mechanism, not a mistake.

Rejected: restructuring the traversal to edit a plain dict instead of the
model. Cleaner in principle, but it rewrites working logic for a cosmetic gain
and risks a real bug in path handling.

**Why it matters beyond tidiness.** Task 15's review validator exercises
`apply_edits` on every submission, so the noise multiplies; and §9.1's audit
rule — the merge that returns a new application — is a beat the demo narrates.
A console printing serializer warnings each time the analyst fixes a field
undercuts the moment.

**Cost.** One keyword argument. Suppression is scoped to this call, so a
genuine serialization problem anywhere else still surfaces.

---

## R-004 — the sample documents' gap test, and reproducible PDFs

**Task 5. `tools/make_documents.py`, `tests/test_sample_documents.py`.**

Three decisions worth keeping, all verified in the parent session rather than
taken on the implementer's word.

**The plan's gap test passed by accident.** It sliced
`body.split("Marcus Vela")[1][:200]` and asserted `"Date of Birth"` was absent.
Under the plan's own document ordering the *control person's*
`Date of Birth: 1978-06-02` begins around character 191 of that slice — it
passed only because the token ran past the 200-character cut. Any rewording
would have flipped it, and the failure would have looked like a content bug
rather than a test bug. **Ruling:** bound Marcus's block by the next section
header (`"Control Person"`) instead of a character count, and additionally
assert no bare date matching `\d{4}-\d{2}-\d{2}` or `\d{1,2}/\d{1,2}/\d{4}`
appears in it — an unlabelled date fills the gap just as effectively as a
labelled one. Strictly stronger than the plan's version.

**`invariant=1` on `SimpleDocTemplate`.** These PDFs are generated *and
committed*, and reportlab stamps a creation timestamp and a random document ID
by default, so every regeneration would produce a spurious binary diff and
`make documents` would dirty the tree on any machine. Verified in the parent
session: two consecutive runs produce byte-identical files by sha256. Task 13's
fixtures are therefore pinned to reproducible inputs.

**Three tests added beyond the plan**, all guarding §8.4 / §5.2 properties the
plan asserted only in prose: the five file stems are exactly the five
`DocumentKind` values (the only place file names and Task 2's `Literal` are
checked against each other); Marcus is named in no other document, so an agent
that reads *everything* still cannot fill the gap and the escalation is
genuine; and every required §5.1 field has a source token somewhere in the set,
so "complete except one dob" is verified rather than assumed.

Independently confirmed here: Marcus appears in `ownership-declaration` only,
with no date in his block; the tax ID appears in both `ein-letter` and `w9`,
which is what T-CHILD-01's fallback needs.

Document prose was extended past the plan's line lists (good-standing
certification, W-9 perjury clause, IRS notice text) so the agent reads
document-shaped text rather than a field list. Every plan-specified token is
preserved verbatim, so Task 13's fixtures can rely on them.

---

## R-005 — `notify`'s dedupe key includes `detail`

**Task 12. `python/activities/delivery.py`.** A genuine spec/plan conflict,
adjudicated in favour of the plan.

§5.5.1's prose says `notify` "appends a record keyed by
`(client_key, outcome, recipients)`". The plan's Step 3 code keys on
`(client_key, outcome, sorted(recipients), detail)` — four parts, not three.

**Ruling: keep the plan's four-part key.** Normally the spec outranks the plan,
but here the literal prose breaks a different part of the spec.

Both keys satisfy the actual requirement, which is idempotency under retry: a
Temporal retry re-delivers the identical `NotifyRequest`, `detail` included, so
neither key appends twice. The three-part key does something extra and
unwanted — it suppresses notifications that are genuinely *distinct events*.
Confirmed against the plan directly: Task 17's reminder is emitted with
`detail=f"KYC review {tier}: attempt {self._attempt} has ..."` (plan line
4530), and §9.2 restarts the review timer per attempt. Under the literal
three-part key, attempt 2's reminder to `["onboarding_specialist"]` matches
attempt 1 on all three fields and is silently dropped from
`notifications.json` — which is the console's source (§13). The same applies to
the client-ID chase loop at plan line 4553.

So the literal §5.5.1 reading makes §9.2's per-attempt reminders invisible in
§13's console. Where two parts of the spec pull apart, the reading that
preserves observable behaviour wins; §5.5.1's tuple is describing the
idempotency property, not specifying an exact dedupe key.

Pinned by `test_notify_keeps_distinct_reminders`, so the choice is reviewable
rather than incidental. To reverse it: drop `detail` from `key` and delete that
one test — and accept that per-attempt reminders stop appearing in the log.

---

## R-006 — the ledger enforces exactly-one-account in the storage engine

**Task 6. `core_banking/ledger.py`, `core_banking/app.py`.**

**The plan's own docstring broke the plan's own test.** Step 1's test asserts
the literal substring `"temporalio"` is absent from the package source; Step 4's
module docstring says *"It NEVER imports temporalio"*. As written Task 6 could
not pass. **Ruling:** keep the assertion (it is the honest check for a real
import) and reword the docstrings to "the Temporal SDK". A second test was
added that AST-parses every module and rejects any import rooted at
`temporalio` *or* `python` — which also catches an indirect route in through
the worker's models. Verified here: zero matches for either.

**`create()` had a duplicate-request race, in exactly the scenario the demo is
about.** The plan's `open_account` did `find()` then `create()`. FastAPI runs
sync handlers in a threadpool, so two concurrent retries could both see `None`,
both INSERT, and the second raise `IntegrityError` — a 500 at the moment the
demo is meant to show a clean `duplicate`. **Ruling:** replace with
`create_or_get()`, a single `INSERT OR IGNORE` guarded by the PRIMARY KEY,
deriving accepted-versus-duplicate from `cur.rowcount`. Exactly-one-account is
now enforced by the storage engine rather than by application logic a retry can
race past.

Probed in the parent session rather than taken on trust: eight threads
released from a barrier onto the same idempotency key produced one
`created=True`, one distinct `request_id`, one ledger row, and no errors.

**`assigned_at` was reporting account-creation time.** The plan sent
`row["created_at"]` as the callback's `assigned_at`, but §5.5 means when the
*client ID* was assigned — after an ambiguous timeout those differ by however
long the operator waits, and the demo deliberately makes that gap visible.
**Ruling:** a separate `assigned_at` column set by `assign_client_id`, emitted
as ISO-8601 with a `Z` so it does not deserialize into a naive datetime on the
gateway side. Re-assignment stays idempotent via `WHERE client_id IS NULL`.

`application` deliberately stays an opaque `dict` rather than
`ApplicationFields`. Importing `python/models` here would couple the system
this service impersonates — bought in 1998 — to the onboarding platform's
Pydantic models, and undercut the independence the whole beat rests on. The
body stays wire-compatible with `OpenAccountRequest`.

---

## R-007 — two gateway errors that would have passed tests and failed on stage

**Task 7. `web/gateway.py`.**

**The 409 must also catch `WorkflowAlreadyStartedError`.** The plan catches
`RPCError` with `ALREADY_EXISTS`. Confirmed against the installed SDK source:
the client converts that gRPC status into the *typed*
`WorkflowAlreadyStartedError` whenever the details unpack, which is the normal
case against a real server. So the plan's handler would have caught nothing,
and §4.1's headline property — "onboarding already in progress for acme-corp" —
would have surfaced as a 500 during the demo while the unit test, which raises
the untyped error, went on passing. **Ruling:** catch both paths, and pin the
typed one with its own test.

**The 422 must unwrap `WorkflowUpdateFailedError.cause`.** §6.1 requires "422
with the validator's rejection message." The real client wraps a validator
rejection in `WorkflowUpdateFailedError`, whose own `str()` is the literal
string `"Workflow update failed"` — so the analyst would have been told nothing
about why their approval was refused. **Ruling:** catch the wrapper first and
return `str(e.cause)`, keeping the plan's `ApplicationError` branch for the
direct case.

Both are the same class of defect and worth naming as a pattern: **a test
written against a hand-made fake can pass while the real client takes a
different path.** These two were caught only by reading the SDK rather than the
plan. Tasks 8 and 14–17 should assume more of these exist.

**The LLM-outage toggle writes a flag file, not `app.state`.** The plan's Step 3
set `app.state.llm_down`, which the worker — a separate process — can never
see. This matches the plan's own gap-closure note (line 5290) that
`live_call_llm` reads a flag at `<DOCUMENT_STORE>/../.llm_down`. **Carried
obligation: Task 10 owns the reader half** and must check
`settings().document_store.parent / ".llm_down"`.

**`GET /api/status/{client_key}` returns 404 before the workflow exists.** Task
8's console polls every 2s "tolerating 404 before the workflow exists," but the
plan's endpoint had no not-found branch — a pre-submit poll would have been a
500 every two seconds behind the demo.

`/api/control` and `/api/assign` use `httpx.AsyncClient` rather than blocking
`httpx.post` inside `async def`, which would stall the event loop for up to 30
seconds during the core-banking beat and freeze the console's polling.

---

## R-008 — `ingest_documents`: paths, unreadable files, and replay-stable refs

**Task 9. `python/activities/ingest.py`.**

**Source `documents/` is anchored at the repo root, not the working directory.**
The plan's `Path("documents")` is cwd-relative, so a worker started from
anywhere but the repo root would fail ingest *non-retryably* and burn one of
`MAX_ATTEMPTS` for what is a configuration mistake, not a document problem.
Resolved from `__file__` instead.

**An unreadable PDF is non-retryable, not just a missing one.** §10.2's
non-retryable column reads "file missing / **unreadable**"; the plan's snippet
handled only "missing", so a corrupt scan would have retried three times before
failing for a reason no retry could improve. Now raises `DocumentUnreadable`.

**`uri` is written with `.as_posix()`.** Refs go into workflow history, and
Task 20's replay tests must pass against histories captured on any machine. A
Windows-style separator baked into a committed history would be a
non-determinism failure that looks like a code bug.

**Follow-up, deliberately deferred:** a `DOCUMENTS_DIR` env override was added,
read directly in `ingest.py` rather than through `config.settings()`, because
the implementer was barred from editing `python/config.py` while three other
agents were running. It exists so §19.7's real case is testable — a document
set that is *present but missing one of the five* — which is impossible to
exercise against the committed complete set. This is in mild tension with §17's
"configuration in exactly one place". **It should move into `Settings` when
`config.py` is next open**; `config.py` is append-only per §20.3, so this is an
addition, not a rewrite.

---

## R-009 — `open_account` must not block the event loop

**Task 11. `python/activities/core_banking.py`.**

**The plan used a synchronous `httpx.Client` inside an `async def` activity**,
with a 110-second client timeout. That blocks the worker's event loop for the
whole call — 10 seconds in the demo's slow-first-call beat, up to 110 in the
wild — stalling the workflow poller and every other activity on that worker.
It would have delayed the very retry the demo exists to show. It also made the
plan's own test unrunnable, since `httpx.ASGITransport` is async-only and
cannot be handed to a sync client. **Ruling:** `httpx.AsyncClient` with the
same `timeout=110.0`, which is deliberately far longer than the 5s
`start_to_close` — the point of §10.1 is that the activity timeout does *not*
cancel the in-flight request. Pinned by
`test_the_http_client_outlives_the_activity_timeout`.

This is the third instance of one pattern, and it is worth naming for the
remaining tasks: **blocking I/O inside `async def`.** Task 7 had it in the
gateway's control and assign endpoints; Task 11 had it here. Tasks 13–17 should
be read with it in mind.

**All 4xx are non-retryable except 408 and 429.** The plan special-cased only
`400`; §10.2 says "core rejects the application (business 4xx)". A 422 from
request validation would otherwise have retried until the attempt was spent, on
a verdict that cannot change. 408 and 429 stay retryable — congestion, not a
verdict. Nothing observable changes today, since the service only emits 400.

**The plan's suggested docstring would have failed the plan's own test.** Its
Step 1 asserts `"info().attempt" not in source`; its Step 3 docstring named
that expression while warning against it. Reworded to "a retry counter". This
is the second occurrence of the same trap — Task 6's docstring broke Task 6's
`"temporalio"` assertion the same way. **When a test greps source for a
forbidden string, the prose in that file is subject to the test.**

Verified here: `grep -i attempt python/activities/core_banking.py` returns
nothing at all, so the key cannot vary per retry by construction rather than by
convention.

---

## R-010 — `call_llm`: the SDK's real HTTP types, and the outage flag closed

**Task 10. `python/activities/llm.py`, `python/prompts.py`.**

**Error fixtures are built from `httpx2`, not `httpx`.** The installed SDK is
`anthropic` 1.4.0, which is built on httpx2 — `APIStatusError.__init__` is
typed `response: httpx2.Response`. Constructing the 401/429/5xx fixtures from
the `httpx` package would hand the activity a *different type* than production
does, so the classification tests would be exercising a path the demo never
takes. Verified here: `anthropic.__version__ == "1.4.0"` and `httpx2` is
present. `pyproject.toml` pins `anthropic>=0.40`, which resolved to 1.x;
`uv.lock` holds it steady.

**The §10.4 outage toggle is now closed end to end**, discharging the
obligation R-007 carried forward. The gateway writes and the activity reads
`config.settings().document_store.parent / ".llm_down"`, and
`test_the_outage_flag_path_matches_the_one_the_gateway_writes` imports *both*
modules and asserts the two resolve equal — so the halves cannot drift apart
silently, which was the whole risk. The raised failure is retryable on purpose:
the beat is the loop retrying and then resuming when the flag clears.

**Malformed tool input is a classified retryable failure.** The plan called
`model_cls.model_validate(...)` bare, so a schema-invalid payload would escape
as a raw `pydantic.ValidationError` — an unclassified error, where §8.3
requires malformed model output to be a retryable activity failure. Also
`{**block.input, "kind": block.name}` rather than the plan's key order, so a
model that emits its own `kind` cannot override the discriminator the workflow
dispatches on.

**A 429 whose `retry-after` will not parse falls back to 30s** instead of
raising. The header may be an HTTP-date; a `ValueError` raised inside the
except block would have replaced a correctly-classified retryable failure with
an unclassified one — the failure mode being handled, reintroduced by the
handler.

**The three manifest helpers pin the outage flag off.** With the default
`DOCUMENT_STORE=./.store`, `.llm_down` resolves into the repo root — ambient
demo state. Running `make demo` with the toggle on would otherwise make
`T-ACT-02` fail for a reason unrelated to error classification.

**Note for Task 13:** `_client()` is `lru_cache`d, so `MODEL` and key changes
need a worker restart — which is precisely why the outage toggle is a flag file
rather than an env var.

**Model-family caveat, out of scope but worth knowing:** the call uses
`tool_choice={"type": "any"}` per the plan. Forced tool use is unavailable on
the Fable/Mythos 5.1 family; on the spec's default `claude-sonnet-5` and on
`claude-opus-5` it is fine. Pointing `MODEL` at a Fable-family model would 400.

---

## R-011 — the console places all ten stages, and what it does not let the analyst edit

**Task 8. `web/static/index.html`.**

**The plan's stage→step map covered eight of §5.6's ten stages.**
`manual_intervention` and `rejected_by_core` had no position, so the two
terminal failure outcomes would have rendered as a blank stepper — in front of
a customer, at the exact moment the demo is making its point about failure
being a *process outcome*. **Ruling:** `manual_intervention`→step 2 (the
extract/review loop that exhausted `MAX_ATTEMPTS`), `rejected_by_core`→step 3
(open account), both drawn in a distinct **failed** treatment rather than
done-or-current. §10.3 says every failure path ends in a business status; the
console now shows that as a finished process with a bad outcome, not a crash.
Verified here: all ten `OnboardingStatus.stage` values appear in the page.

**A network failure is not a 404.** A fetch exception keeps the last good
render behind a quiet footnote ("Gateway unreachable — showing the last known
state"); only a real 404 renders the neutral pre-submit idle state. Clearing
the screen because one poll failed would look, on stage, exactly like the
workflow dying.

**Open question deliberately left for Task 15 — the field table is read-only.**
§9.1 says the analyst can edit field values; the plan scopes the console's
inputs to `gaps[]` only. The implementer kept the plan's narrower scope: gap
inputs are editable, the "N fields extracted & verified" table renders
read-only. **This is a real narrowing of §9.1 and should be decided
deliberately, not inherited.** Widening it changes what lands in
`field_edits`, which Task 15's validator owns — so Task 15 is the right place
to settle it. `gaps.apply_edits` already handles an edit to any path, including
an optional field (§19.3), so the machinery is not the obstacle.

Labels follow §3's personas rather than the plan's terse verbs — "Approve &
open the account", "Reject — send back…" — since two different people operate
this and the plan's own tests only require the substrings.

The one external URL in the page is an `<a>` to the local Temporal UI, which
§12 wants reachable. No external scripts or stylesheets: the page is
self-contained, as §13 requires.

---

## Closed — `make verify`'s false green between Tasks 1 and 3

Recorded in Task 1: `make verify` printed "VERIFY OK: 22/22 scenarios
implemented and passing" while only `tests/test_config.py` existed, because
nothing was skipped. Left unfixed on the reasoning that the message becomes
true when the manifest lands.

**Closed by Task 3.** The gate now exits non-zero with `VERIFY FAILED: skipped
tests remain (§16.8)` against 13 passed / 22 skipped, and the count means what
it says. No code change was needed.

## Known weakness — the determinism guard passes vacuously

`tests/test_determinism_guard.py` walks `Path("python/workflows").rglob("*.py")`.
Until Task 13 creates that directory there is nothing to scan, so the test
passes on an empty set — and it would pass the same way if the directory were
ever renamed or moved. A silent no-op is the failure mode a determinism gate
can least afford.

Verified by hand in Task 3 rather than trusted: a probe file containing
`import httpx`, `import random` and `datetime.now()` was dropped into
`python/workflows/` and the guard failed on all three, naming file and line.
The probe was deleted; nothing about it is committed.

Not fixed, because the honest fix — asserting the directory exists — would fail
the suite for the ten tasks before Task 13 creates it. The file-structure table
locks the path, and Task 20's replay tests are the real determinism gate. If
`python/workflows/` ever moves, this guard must move with it.

---

## R-012 — three defects in the plan's Task 13 code, all of which hang or lie

The plan's Step 3 workflow does not run as written. Each fault was found by
executing it, not by reading it, and each is worth naming because Tasks 14–18
copy this shape.

**1. `config.settings()` inside `run()` — the workflow hangs forever.**
`settings()` reads `os.environ`, which the sandbox forbids at execution time:
`RestrictedWorkflowAccessError`. That fails the workflow *task*, which retries
indefinitely, so the symptom is not an error but a test that never returns. The
sandbox is right — a workflow that re-read its config mid-run would replay
differently after an env change. Moved to `SETTINGS = config.settings()` inside
`workflow.unsafe.imports_passed_through()`, where it is an ordinary import-time
read, frozen for the life of the worker. **Tasks 14–18 must do the same.**

**2. A string-named activity needs `result_type`.** The plan writes
`response: LLMResponse = await workflow.execute_activity("call_llm", ...)`. The
annotation deserializes nothing; the converter has no signature to infer from
and returns a bare `dict`, so the next line dies on `.turn`. Added
`result_type=LLMResponse`. Same fault in the plan's test helper against
`execute_workflow` — added `result_type=ExtractionResult` there.

**3. `RetryPolicy(maximum_attempts=0)` reads as "no retries" and means the
opposite.** Zero is unlimited. This is correct — §10.2 specifies the *default*
policy for `call_llm`, and unlimited-with-backoff is that default — but it is
correct by accident of a confusing spelling. I changed it to `1` on a first
reading, which would have disabled the retry §10.2 requires, and caught it only
by re-reading §10.2. Restored, with a comment saying what zero means. Anywhere
this idiom is copied, the comment goes with it.

Cost: one hang diagnosed by fetching workflow history under a timeout. Faults 1
and 2 are silent — no test the plan specifies would have caught either as
anything but a hang or an `AttributeError`.

## The determinism guard is no longer vacuous

The known weakness logged above is closed by this task: `python/workflows/` now
exists and holds real workflow code, so the guard scans a non-empty set.
Re-probed rather than assumed — a file containing `import httpx` and
`datetime.now()` was dropped in, the guard failed naming both lines, and the
probe was deleted. Nothing about it is committed.

---

## R-013 — four more defects in the plan's Task 14 code, and an off-by-one

Same method as R-012: run it, don't read it.

**1. The stub child cannot be a local class.** The plan builds `StubChild`
inside `Stubs.child()` so it can close over the test's state. The SDK refuses:
*"Local classes unsupported, `@workflow.run` cannot be on a local class"* — it
needs the class globally referenceable by name. Moved to module scope in
`conftest.py`, reading the active `Stubs` through a module global, with
`tests` added to the sandbox's passthrough modules so the stub child and the
test process see the same object. The workflow under test stays sandboxed;
only the stub is passed through.

**2. The stub activities take untyped arguments.** `async def ingest(req)` has
nothing for the converter to build from, so the activity receives a `dict` and
dies on `req.attempt`. This is R-012's fault 2 seen from the other end: the
caller needs `result_type`, the handler needs an annotated parameter, and
neither is optional.

**3. Both of those present as a hang, not a failure.** An activity that raises
retries on the default policy, which is unlimited — so the test sat until the
10-minute cap with no output. Same shape as R-012's fault 1. The tell is in the
worker log rather than the assertion: `Completing activity as failed` with a
climbing `attempt` number. Look there first.

**4. Off-by-one in the exhausted-attempts branch.** The `while` increments
`_attempt` past the cap before the `else` runs, so `OnboardingResult.attempts`
reported 4 after three rejections. `T-WF-03` and `T-WF-09` both assert 3.
Pinned to `SETTINGS.max_attempts` in the `else`. Worth noticing that the plan's
own tests caught this one — it is the only fault here that the plan would have
found on its own.

**Deviation, deliberate: the manifest delegates in-process, not by subprocess.**
The plan has each `T_WF_*` manifest entry shell out to `pytest` against the
topic test. That boots a second interpreter and a second Temporal server per
scenario, and reports a returncode rather than an assertion. The manifest
wrappers are `async def` taking the `env` fixture and awaiting the topic
function directly — same delegation, one process, real failure output. The
manifest stays the authoritative list of 22, which is what §16.8 asks for.

## Promoted to rules

Applying the rule of two, from this task's evidence:

- **Both ends of a call need types**, not just the caller — added to
  `workflow-determinism.md` and `payloads-and-activities.md`. Second occurrence
  (R-012 fault 2 was the caller; this was the handler).
- **Unlimited retry turns a defect into a hang** — the existing note covered
  workflow tasks; extended to activities, since the symptom and the diagnosis
  differ. Second occurrence.

---

## R-014 — the open question, settled: `field_edits` is not scoped to gaps

**Task 15.** R-011 left this for this task, because widening it changes what
lands in `field_edits`, which this task's validator owns.

**The ruling: the workflow contract is open.** `field_edits` may target any
path — an escalated gap, an optional field, or a field the model already
filled in. Three things say so and nothing says otherwise:

- §9.1 justifies choosing an *update* over a signal on the grounds that "the
  analyst can *edit* field values (correcting data is much of what KYC review
  is)". A contract that only accepts gap paths does not support that sentence.
- §19.3 already requires accepting an edit to an **optional** field. An
  optional field is never a gap, so the narrow reading contradicts a ruling the
  spec makes explicitly.
- §18's nine cuts do not include this one. Narrowing it would be a tenth,
  unstated.

Correcting a value the model read wrongly — a transposed EIN digit, a
misparsed formation date — is the ordinary case in KYC review, not an edge
case. Pinned by `test_an_edit_to_a_field_that_is_not_a_gap_is_accepted`, which
edits one required field and one optional one and reads the merged value back
out of the `status` query.

No code change was needed: `gaps.apply_edits` already walked any path, and the
validator re-checks the whole merged application rather than the edited subset.
The contract was open; nothing had proved it.

**Deferred, deliberately, and named: the console's field table.** The other
half of R-011 is that `web/static/index.html` renders the "N fields extracted
& verified" table read-only, so the demo cannot show the beat this ruling
authorises. That is not settled by this task and should not be smuggled into
it: the table is the console's most designed surface, §13 makes its visual
design Stage 3 work under the `frontend-design` skill, and Task 15's declared
files are the workflow and its tests. Doing it here would mean editing an
890-line page and its test file under a task that claims to touch neither.

**It is now a scoped piece of work, not an open question:** add inputs to the
grouped table, collect them into the same `field_edits` array the gap panel
already builds, and extend `tests/test_console.py`'s
`test_review_payload_matches_review_submission` to cover a non-gap edit. The
validator will accept it today. **Task 18 is the right home** — it is the next
task that opens the console — and if it is not done there, the demo's review
beat stays narrower than §9.1 describes.

---

## R-015 — the core call retries in the workflow, not in the activity policy

**Task 16.** The plan asks for this to be recorded, and it is a real deviation
from §10.2.

**What §10.2 says.** `open_account`: start_to_close 5s, "initial 1s, backoff
2.0, max interval 10s, unlimited attempts". Read literally that is a
`RetryPolicy` on the call site, and the SDK would honour it with no loop.

**What was built.** `maximum_attempts=1` on the activity, wrapped in a
`while True` in the workflow that increments `_core_attempt`, records
`_last_error`, and backs off with `workflow.sleep(min(10, 2 ** (n - 1)))` —
1s, 2s, 4s, 8s, 10s, 10s… That is §10.2's curve exactly, and unlimited as it
requires. Only the location changed.

**Why.** Activity retries are invisible to workflow state — that is the point
of them — but §13 requires the console to show `core_attempt` and `last_error`
*while the retry is happening*, and §12 wants the beat legible on the Timeline
without opening an activity's detail pane. The headline of this entire demo is
a retry the audience can watch. A retry nobody can see does not tell the story,
and there is no way to surface an in-flight activity retry into a query.

Pinned by `test_the_timeout_is_visible_in_status_while_it_retries`, which polls
`status` during the failed attempt and asserts `last_error` reads
`"attempt 1: ..."`. Without the loop that assertion cannot pass by any means.

**The cost, stated plainly.** Each attempt now writes activity-scheduled,
activity-failed and timer events to history rather than being folded into one
activity's retry sequence. §4.3's budget has two orders of magnitude of
headroom, so the cost is real but not close to mattering. The second cost is
subtler: an implementer reading §10.2 will expect a `RetryPolicy` here and find
`maximum_attempts=1`, which reads like the retry was disabled. Hence the
comment at the call site pointing here.

**Unlimited means unlimited.** If the core banking service never answers, this
loop waits forever, and that is correct — §10.2 says unlimited attempts, and a
bank's core coming back in an hour is the normal case. It is not a violation of
§10.3's "every failure path ends in a business status": waiting is not a
failure path. The non-retryable rejection, which is one, completes as
`rejected_by_core`.

**No promotions from this task.** Nothing here has happened twice, and the
rule of two means what it says.

---

## R-016 — the plan's "no timer summary" claim is wrong; §12's label is reachable

**Task 17.** Step 3 instructs: *"`workflow.wait_condition(timeout=...)` does not
accept a `summary`, so the labelled durable timer for §12 comes from the
explicit `workflow.sleep` in Task 16 plus `set_current_details` in Task 18.
Record this as a ruling."*

**Checked rather than recorded.** `inspect.signature(workflow.wait_condition)`
returns `['fn', 'timeout', 'timeout_summary']`. The parameter exists; it is
named `timeout_summary`, not `summary`, which is presumably how the plan
concluded it was absent. `workflow.sleep` takes `summary` — the two differ, and
that is the whole of it.

**So the ruling is the opposite of the one requested.** Both SLA waits now pass
`timeout_summary`, and §12's example label — *"KYC review SLA — 3 days"* — is
what the Timeline shows, from the mechanism §9.2 actually uses. No fallback to
`set_current_details` is needed for this, and Task 18 does not inherit a gap.

**The general point, worth more than the fix.** A ruling that records a
limitation is a claim about the world, and this one would have been wrong in
the permanent record — cited later as the reason the demo's timers are unlabelled.
One `inspect.signature` call settled it. **Check a limitation before logging
it; a plan asking for a ruling is not evidence that the limitation is real.**

## Known weakness — the suite errors intermittently, twice seen, not reproduced

Recording this rather than fixing it, because it has now happened twice and the
rule of two says it stops being noise at two.

**Sighting 1 (after Task 13).** `make test` exited non-zero while its own
summary line read `129 passed, 16 skipped`. Four immediate re-runs were clean.
The output was piped through `tail -2` and the detail was lost.

**Sighting 2 (this task).** `163 passed, 4 skipped, 1 error` — one test short
of the 163 that pass on a clean run, with the failure counted as an **error**
rather than a failure, which in pytest means fixture setup or teardown rather
than the test body. Four immediate re-runs were clean, all 163/4.

**Hypothesis, untested.** `env` and `skip_env` are function-scoped, so the suite
now boots roughly a dozen Temporal servers per run, each claiming ports. A port
or startup race in that churn would present exactly this way: a fixture error,
unreproducible, unrelated to the test that happens to catch it.

**The fix, when someone takes it.** `.claude/rules/testing.md` already says
`start_local` "is shareable via a pytest fixture" — making `env` session-scoped
(with `loop_scope="session"`) would cut the boots to one and remove most of the
race surface. `skip_env` must stay function-scoped: §16.3 says time-skipping
environments cannot be shared. Not done here because the suite is green, the
fault has never been reproduced on demand, and changing fixture scope at the end
of a task trades a rare unexplained error for a fresh class of cross-test
interference. **Task 20 touches the test infrastructure anyway and is the right
place.** If a third sighting lands first, do it then regardless.

**Update (R-017).** The duplicate-collection fix halves the boots on its own —
twelve scenarios were each starting a second `WorkflowEnvironment` — so the
race surface is already smaller than when this was written. That is a
reduction, not a fix: the hypothesis is untested either way, and the
session-scoped `env` above is still the change to make.

**Closed by R-019 — sighting 3 arrived and carried the traceback.**

## R-017 — six defects found reviewing Task 13–17 before merge

A code review of the workflow branch, run against the spec rather than the
plan. All six were live on the branch and none were caught by the 163-test
suite, which is the part worth noticing: every one of them is a *behaviour the
tests asserted loosely enough to miss*.

**1. `escalate` threw away everything the agent had extracted.** The child
returned `ApplicationFields()` on the escalation branch. `prompts.py` steers
the model to escalate on exactly §8.4's missing `dob`, so the demo's headline
beat put the analyst in front of a blank application — and their
`beneficial_owners[1].dob` edit then had no owner 1 to address. No
`field_edits` could recover it, because `apply_edits` cannot append list
members. `Escalation` now carries an optional `application`, the tool schema
and system prompt ask for it on every escalation, and the workflow passes it
through. **The gap between "escalation is a return value, not an exception"
(which the rules say, and which was correctly implemented) and "escalation
carries the work done so far" is where this hid.**

**2. The client-ID chase was recorded once and then silently dropped.**
`notify` keys its records on `(client_key, outcome, recipients, detail)` —
R-005 chose that key deliberately — and the chase's `detail` was
byte-identical on every iteration. Every chase after the first collided with
the first and was discarded, so an unbounded wait produced exactly one
notification. §9.3 also says the timer reminds *and* escalates, and this only
ever reached the onboarding specialist. The detail now carries a chase counter
and the second chase onward reaches the supervisor. **T-TIME-03 passed
throughout: it asserted that a chase exists, not that chases keep arriving.**

**3. The exhausted-attempts path described a review that never happened.** The
detail hard-coded `"rejected N times; last note: ..."`. Three
`ChildWorkflowError`s exhaust the loop without a single human decision, so
that string was simply false — and it dropped `self._last_error`, the only
record of the real cause, from both `OnboardingResult.detail` and the
supervisor's notification. A rejection now records its note into
`_last_error` too, and the exhausted path reports whatever actually happened
last.

**4. A second decision could replace one the workflow had already
acknowledged.** `submit_review`'s validator gated on stage only and the
handler assigned unconditionally. Two updates in one activation are both
*validated* before either handler runs, so both acked `accepted=True` and the
last writer won — an approval silently replaced by a reject. The guard has to
be in the handler, before any `await`, for the check and the assignment to be
one atomic step; the validator keeps a matching check so the ordinary
sequential case is refused before it reaches history. **A validator cannot
enforce a property that depends on other updates in the same activation.**

**5. Escalation was measured from the reminder, not from the gate.** The
second tier waited `sla_escalate - sla_remind`, started *after* the reminder's
`notify` returned, so escalation always landed late by that activity's
duration, and the timeout went zero or negative when `SLA_ESCALATE <=
SLA_REMIND`. Both tiers are now offsets from `_pending_since`. The smallest of
the six in practice — the drift is milliseconds at realistic SLAs — but the
negative-timeout case worked only by accident.

**6. Twelve scenarios ran twice.** The `T_WF_*`/`T_TIME_*` manifest wrappers
delegated to functions named `test_...` in the topic modules, which pytest
collects on their own as well, so each scenario booted a second
`WorkflowEnvironment` for no added coverage. The T-CHILD and T-ACT wrappers
already avoided this by naming their helpers `assert_...`; the workflow
scenarios now do the same. 163 tests → 151, runtime 48s → 30s, and the
manifest IDs are untouched.

**On the tests.** Six new regression tests, each confirmed to fail on the
pre-fix code and pass after — the check that separates a regression test from
a restatement. Three further tests were written, passed against the unfixed
code, and were kept as characterization rather than deleted or dressed up as
pins: an escalation with no application still returning cleanly, a
misconfigured `SLA_ESCALATE <= SLA_REMIND` still firing both tiers, and a late
reject after a completed approval (which the *stage* guard already refused —
the same-activation race is the case the new handler guard actually closes).
**A test that passes before the fix pins nothing; say so rather than counting
it.** Defect 5 needed a deliberately slow `notify` before its drift was
observable at all, and is asserted against the timer duration recorded in
history rather than against wall-clock arrival, so it does not depend on
scheduling luck.

## R-018 — eight defects found reviewing the merged activity and tooling code

Numbered R-018 rather than R-017 on purpose: R-017 is the parallel review of
the Task 13–17 workflow branch, which was in flight on its own branch when
this was written. Two reviews ran at once and the numbers were reserved so the
entries could not collide. **It worked**: this one merged first, R-017 landed
after it, and the merge put both in number order above. The reservation cost
nothing and the alternative — two entries both called R-017 — would have been
unrecoverable in a log that is only useful if its references resolve.

This one covers what was already on `main` — the activities, the fake core
banking service, and the Makefile.

**1. `make verify` — the definition of done — passed a failing suite.** The
gate pipes pytest into `tee`, and the shell hands back **tee's** exit status,
not pytest's. Everything then rested on a grep for "skipped". While skips
remain that is masked, because the skip check fails first; the moment the last
skip is implemented, a suite with real failures prints "VERIFY OK: 22/22
scenarios implemented and passing" and exits 0. Reproduced end to end: a
deliberately failing test, all skips removed, old gate — exit 0 and a green
message. The status now travels through a file, checked before the skip check
(`pipefail` is not POSIX and this Makefile does not choose its shell).

**The earlier ruling on this file closed the wrong half.** *"Closed — `make
verify`'s false green between Tasks 1 and 3"* looked at a gate that printed OK
when nothing was skipped, decided the message "becomes true when the manifest
lands", and closed it when the skip count started working. The skip half was
real. The exit-status half was never looked at, and it is the half that
survives to the end of the build — it only becomes reachable when the last
skip goes. **A gate that has only ever been watched failing one of its two
checks has not been tested; force the other one.**

**2 and 3. `gaps.py` crashed on the escalation input it exists to describe.**
`control_person` is optional and `REQUIRED_FIELD_PATHS` walks *through* it, so
`compute_gaps(ApplicationFields())` took an `AttributeError` on None —
`_get`'s loop assumed every parent exists. `apply_edits` had the same hole,
plus two more: a composite path (`registered_address`) handed a line of text
raised a raw `ValidationError`, and an index past the end of a list raised
`IndexError`. The console renders a free-text box per gap and posts whatever
is typed, so an analyst reached all three from the Approve button.

`_get` now stops at an absent parent, `missing_required` drops a container
whose leaves it is already reporting (a `control_person` row is unfillable; a
`control_person.dob` row is not), and `apply_edits` builds an absent optional
parent so the leaf edit lands, refuses a missing index by name, and converts a
schema failure into a readable `ValueError`. **This contradicts R-011's claim
that `apply_edits` handles any path — it handled every path the happy-path
fixture produces.**

**Left alone deliberately:** `registered_address` and `business_address` are
listed whole in §5.2 and `FieldEdit.value` is a `str`, so no typed text can
build an `Address`. An application missing an entire address is therefore
still unapprovable — it now refuses readably instead of raising. Making it
fillable means listing the address leaves in `REQUIRED_FIELD_PATHS`, which is
a spec change, not a bug fix.

**4. One corrupt file stopped every workflow.** `notify` did an unguarded
`json.loads` on `notifications.json` and a non-atomic `write_text`. A worker
killed mid-write leaves a truncated file; every subsequent `notify` then
raises an unclassified error and retries on the default unlimited policy. Every
terminal status goes through `notify`, so **no workflow could reach a terminal
status** — one half-written file presenting as the whole system hanging, and a
direct breach of "every failure path ends in a business status". Writes now go
through a temp file and `os.replace`; an unreadable log is renamed aside (kept
as evidence) and a new one started.

**5. `call_llm` blocked the event loop.** The synchronous Anthropic client and
`PdfReader` both ran directly inside an `async def`, holding the loop for up to
`_CLIENT_TIMEOUT_SECONDS` (110s) and stalling every other activity on the
worker, its workflow tasks, and its heartbeats. Both legs now go through
`asyncio.to_thread`. **This is the same defect as R-009, and the fourth
instance in this build.** It has now appeared often enough that finding it
should be a checklist item on every `async def`, not a discovery.

**6. A missing API key retried forever.** With no credential resolvable the
SDK constructs happily with `api_key=None` and raises a bare `TypeError` from
`messages.create` — not an `anthropic` error, so it misses every clause in the
classification chain, escapes, and retries unbounded. A missing environment
variable presented as a hung workflow. Now classified non-retryable, with the
`FIXTURE_MODE=1` escape hatch named in the message. The clause is deliberately
narrow (it re-raises a `TypeError` that is not about authentication) so a
genuine bug in the call is not relabelled a credentials problem.

**7. The fixture selector had an off-by-one and a silent clamp.**
`min(len(turns), len(sequence) - 1)` is `-1` for an empty file, which indexes
the empty list and raises `IndexError`; and once the agent runs past the end of
the recording it replayed the last response forever, which presents as the
agent looping to its iteration cap for no visible reason. Both are now
non-retryable errors that say what to do.

**8. Two smaller ones.** `make demo-reset` did not clear `.llm_down`, so a
toggled model outage survived into the next demo — the flag lives beside
`.store`, not inside it, because the path is DOCUMENT_STORE's *parent*, which
defaults to the repo root. It was not in `.gitignore` either. And core
banking's `assign` persisted the client ID and then posted the callback
unguarded, so a gateway hiccup returned a bare 500 with the ID already minted
and the workflow parked in `awaiting_client_id` with no idea one existed. It
now returns a 502 naming the ID and saying to assign again — which is safe,
because `assign_client_id` was already idempotent.

**On the tests.** Sixteen added; fourteen were confirmed to fail on the
pre-fix code. The two that did not are guards rather than pins and are labelled
as such: one holds the new `TypeError` clause narrow, and one pins the
atomic-write path, which cannot observe truncation without an actual crash
mid-write. Suite: 124 passed → 140 passed, 19 skipped unchanged.


## R-019 — the intermittent suite error, closed at sighting 3

This entry closes *"Known weakness — the suite errors intermittently, twice
seen, not reproduced"* above. That entry said the fix belonged to Task 20 **"or
sooner on a third sighting"**. The third sighting arrived on the merge of
`main` into the workflow branch, so this is that clause being honoured rather
than a new decision.

**What the third sighting added.** The first two were recorded as bare counts,
one of them through `tail -2`, with the detail lost. This one carried the
traceback:

    RuntimeError: Failed starting Temporal dev server: Failed connecting to
    test server after 5 seconds, last error: ... ConnectError("tcp connect
    error", 127.0.0.1:42487, ConnectionRefused)

That is the recorded hypothesis, confirmed: a function-scoped `env` boots a dev
server per test, each claiming a port, each racing the next one's startup. It
is a fixture error rather than a test failure for the same reason — the fault
is in setup, and the test that happens to catch it is innocent. **Two sightings
were enough to justify recording it and not enough to diagnose it; the third
was only decisive because it was the one nobody piped through `tail`.** Capture
the error before re-running, not after.

**The fix.** `env` is now `scope="session", loop_scope="session"` — one server
per run instead of roughly a dozen. `.claude/rules/testing.md` already
sanctioned this (*"it is shareable via a pytest fixture"*), so no rule had to
change to permit it; the rule now states the scopes and why they differ.

`skip_env` stays function-scoped, and that asymmetry is the point. §16.3 says
time-skipping environments cannot be shared, and these tests advance the clock
by a year: one shared instance would let whichever test jumped forward first
decide what "now" meant for every test after it — and that failure would
present as another flake, which is precisely the hole this entry came out of.

**The risk the old entry named, and what was actually done about it.** It
warned that changing fixture scope "trades a rare unexplained error for a fresh
class of cross-test interference". That is the right worry and it is testable:
interference from a shared server would show as order-dependence. Four full
runs in random order (`pytest-randomly` is on by default; `make verify` is the
only thing that disables it) came back 177 passed / 4 skipped every time.

Sharing is safe here for a specific, fragile reason worth writing down:
**nothing in the suite shares names.** `run_worker` takes a fresh uuid4 task
queue per test and every workflow id carries a uuid4, so two tests cannot see
each other's workflows even on one server. A test that pins a fixed workflow id
or task queue would break that, silently, and would look like a flake. Both the
fixture docstring and the rule now say so.

**Both scopes are pinned by `tests/test_fixture_scopes.py`,** asserted against
pytest-asyncio's own fixture marker rather than by grepping the source — this
repo has twice failed a source-grepping gate with a docstring, and a scope is a
value that can be read directly. The guard was watched failing: reverting `env`
to function scope fails it, which is the *"a gate nobody has seen fail is not
known to work"* rule applied to the gate added in the same commit.

**What is NOT claimed.** The error was never reproduced on demand, so this is a
fix to the mechanism the traceback names, not a fix confirmed by watching the
fault disappear. Absence over four runs is weak evidence — the fault was always
rare. If it recurs with a session-scoped `env`, the port race was not the cause
and this entry is wrong; the traceback is the thing to capture, again.

---

## R-020 — `.env` is now a supported way to set config; Make reads it, not Python

**Not from a task.** Asked, while picking the work back up locally, whether a
template env file existed to copy the API key into. It did not, and the spec
does not mention one: §17 lists seventeen variables and says nothing about how
they get into the environment. That is a gap rather than one of §18's nine
cuts, so this is a ruling.

**What was added.** `.env.example` at the repo root, tracked, listing every
§17 variable with its default and the demo-profile value beside the three SLA
timers. `.env` is gitignored. `make/common.mk` gained two lines:

    -include $(ROOT)/.env
    export

**Where the loading lives, and why not in Python.** The obvious alternative is
`python-dotenv` inside `config.py`. It was rejected: `config.py` is imported
by `python/workflows/`, where module-level import happens **inside the workflow
sandbox**, and `load_dotenv()` is a filesystem read. That is the determinism
rule, and buying a convenience with a sandbox violation is the wrong trade
when Make can do it for free. Make also covers more ground — the gateway and
the core banking service are separate processes started by recipes here, and
neither imports `config.py`.

**Two properties that had to be checked rather than assumed.**

1. *The suite cannot be turned live by a stale `.env`.* `test` and `verify`
   set `FIXTURE_MODE=1` inline in the recipe's shell command, which beats an
   exported variable. A `.env` carrying `FIXTURE_MODE=0` does not reach them.
2. *A missing `.env` is not an error.* The leading `-` on `include`. A fresh
   clone with no file and no key still reaches `make verify`, which §16.7
   requires.

**The cost, stated because it will surprise someone.** A value in `.env` beats
the same variable already exported in the shell — Make's file assignments win
over the environment unless `-e` or `override` is in play. That is backwards
from how most dotenv loaders behave, so `.env.example`'s header and the README
both say it. The file is also read as Make syntax, not shell: `KEY=value` only,
no quotes, no trailing `# comment` on a value line, `$$` for a literal dollar.
The alternative — writing `?=` in the example so the shell wins — was rejected
for making the file unsourceable by hand and stranger than it is worth.

**Empty is not unset.** `ANTHROPIC_API_KEY=` copied and left blank exports an
empty string, so the SDK sees a key, fails auth, and `llm.py` classifies a 401
as a non-retryable `ClientError` — not the `AuthenticationError` its TypeError
clause raises for genuinely absent credentials. Both are non-retryable and both
name the problem, so this is documented rather than fixed.

---

## R-021 — the tracker: a broken test, and a failed run that read as a finished one

*Renumbered from R-017 when this branch merged `main`. Main's R-017 — the Task
13–17 review — landed in parallel while this branch sat unmerged, so both sides
wrote an R-017, an R-018 and an R-019 with different content. Commit `1ae82f5`'s
message calls this one R-017; history is not rewritten to match.*

**Task 18.**

**1. The plan's test could not pass as written.** It builds
`{l.split(" ", 1)[1]: l[0] for l in out.splitlines() ...}` and then looks up
`lines["KYC review"]`. The current step's line is
`"→ KYC review — awaiting the KYC analyst"`, so splitting on the first space
gives the key `"KYC review — awaiting the KYC analyst"` and the lookup raises
`KeyError`. The marker map is now built by matching each line against
`tracker.STEPS`, which does not care what follows the step name.

**2. The plan's tracker rendered a failed onboarding as seven ticks.** Its
`TERMINAL = {"complete", "manual_intervention", "rejected_by_core"}` marks every
step ✓ for any terminal stage. So an application rejected three times, or turned
down by core banking, showed in the Temporal UI as a completed seven-step
process. That is precisely the confusion R-011 fixed in the console — a finished
process with a bad outcome is not a finished process with a good one — and §10.3
rests on the distinction.

`FAILED_AT` now maps `manual_intervention`→step 2 and `rejected_by_core`→step 3,
the same indices R-011 chose for the console, and the run renders ✓ up to that
step, ✗ at it, ○ after. One `stage` value, two surfaces, **and now the same
reading on both** — which was the point of §12. Pinned by
`test_a_failed_terminal_stage_says_so_rather_than_showing_seven_ticks`.

## R-022 — R-014's deferred half, done: the field table is editable

*Renumbered from R-018 on the same merge — see R-021. Commit `1ae82f5`'s
message calls this one R-018.*

**Task 18**, as R-014 assigned it.

`fieldRows` now emits a dotted `data-path` per cell — `tax_id`,
`beneficial_owners[1].dob`, `control_person.title` — and a click turns the value
into an input. Enter or blur commits into a `corrections` map, Escape abandons.
On approve, corrections join the gap edits in the same `field_edits` array, with
a guard so a field that is both a gap and a table edit is sent once. Edited
cells are marked, so the analyst can see their own delta before approving —
§9.1's audit rule made visible at the point of decision.

**Verified in a real browser, not only by grep.** The console's tests read the
page as text, so they would pass against a page whose JavaScript does not run.
Chromium was driven against the page with the gateway's responses stubbed: open
the collapsed table, correct `tax_id` (not a gap), fill the real gap, attest,
approve — and the intercepted request body carried both entries and no page
errors. The payload is exactly the shape Task 15's validator accepts.

## Promoted to rules

**A test that greps a page proves the string is there, not that the page
works** — added to `testing.md`. Second occurrence: the console's Task 8 suite
has always been substring assertions, and this task added four more of them
before anything checked that the feature functioned. `node --check` on the
extracted script catches a syntax error in seconds; a headless browser catches
the rest.

---

## R-023 — Task 19 is blocked on the API key; the recorder is built and verified as far as it can be

*Renumbered from R-019 on the same merge — see R-021. Commit `5c217c1`'s
message calls this one R-019, and `testing.md`'s promoted `sys.path` rule cites
that number too.*

**Task 19.** §16.7 step 2 records the fixtures by running the extraction loop
live. `ANTHROPIC_API_KEY` is not set in this environment, so the recording did
not happen. What could be done without it was done.

**1. `make fixtures` would have failed on its first line.** `record_fixtures.py`
is the first tool to import from the `python` package, and
`uv run python tools/record_fixtures.py` puts `tools/` on `sys.path`, not the
repo root — so `from python import config` raises `ModuleNotFoundError` before
the key is even checked. pytest never sees this because `pyproject.toml` sets
`pythonpath = ["."]` for the test run only; `make_documents.py` never saw it
because it imports nothing from the package. Fixed with an explicit
`sys.path.insert` and a comment, so the script works via `make` and when run
directly. **Task 20's `capture_histories.py` will hit exactly this** — promoted
to `testing.md` on that basis.

**2. The recorder now says when a recording is unusable.** §8.4's missing date
of birth is the demo's escalation beat, and the plan's Step 4 says that if the
run does not escalate it, fix the prompt and re-record rather than hand-edit.
Nothing said so at the point of recording. The script now prints a warning
naming the failure and the correct remedy, because the person running this is
running it once and will not have the plan open.

**3. The tests skip rather than fail until the fixtures exist.**
`pytest.mark.skipif(not FIXTURES.exists())` with the reason naming
`make fixtures` and the key. The suite stays green and `make verify` stays
correctly red — the five skips are the remaining work, which is what that gate
is for. Committing five failing tests would have made the suite meaningless as
a signal for everything else.

**What is left:** run `make fixtures` with a key set, review the recorded JSON
in the diff, commit it. The suite is keyless from then on. Task 20 needs the
fixtures in place before it can capture histories, so the build is blocked here
until someone supplies the key.

---

## R-024 — two defects the first live run found, both invisible to every stub

**Task 19.** R-023 left this task blocked on the API key. With the key supplied
(R-020's `.env`), `make fixtures` failed twice before it recorded anything, on
two faults that had been sitting in merged, green code. Both were unreachable
from the suite for the same reason, which is the part worth keeping.

### 1. The agent loop ended its transcript on an assistant turn

    anthropic.BadRequestError: 400 — This model does not support assistant
    message prefill. The conversation must end with a user message.

`call_llm` renders an `AgentTurn` with `role="assistant"` as an assistant
message. The loop appended the model's action as an assistant turn on every
iteration, but appended the **tool's result** only when `request_documents`
named an unknown id. So the success path — the normal path — left the
transcript ending on an assistant turn, which is an assistant *prefill*.
Prefill was removed across the 4.6+ family, `claude-sonnet-5` included: it is a
permanent 400, not a transient one.

Iteration 1 always worked (`turns` is empty, so the request is a lone user
message) and iteration 2 always failed. Any run that read a document — again,
the normal path — hit it.

**Fixed at the loop, not at the boundary.** `document_tool_turn()` now records
the result of *every* `request_documents` call, granted ids and unknown ids
alike. That is the correct tool-loop shape independently of the API rule, and
the API rule then falls out of it. Ids only, never text (§8.2), and it also
covers an empty `doc_ids`, which would otherwise send an empty content block —
a different 400 on the same call.

`tools/record_fixtures.py` hand-rolls this loop, because §16.7 records without
a Temporal server, and it had the identical omission. It now imports
`document_tool_turn` rather than keeping a second copy of the rule.

**This changes the child's history shape.** Task 20 captures the T-REPLAY
histories through this loop, so it must run after this fix — a history captured
last week would encode the broken transcript.

### 2. The terminal tools told the model nothing about the payload shape

`submit_extraction` and `escalate` declared `application` and `gaps` as bare
`{"type": "object"}`. Handed no schema, the model answered with `field` instead
of `field_path`, `'Passport'` instead of the `passport` enum, `'30%'` for a
`Decimal`, and a flat string where an `Address` belongs. Pydantic rejected all
of it.

**The failure mode is worse than the error suggests.** §10.2 classifies
MalformedResponse as *retryable*, so in the workflow — rather than in the
recorder's `ActivityEnvironment`, which does not retry — that same impossible
call retries on an unlimited policy. The demo would not have shown an error; it
would have hung, which `workflow-determinism.md` already warns is what a defect
on this path looks like.

`payloads-and-activities.md` had required the fix all along: Pydantic
"generates the JSON schema handed to Claude for structured extraction". It now
does, via `prompts._terminal_payload_schema()`, with `$defs` hoisted to the
schema root where the generated `$ref`s resolve. Generated rather than
transcribed, so a new field on `ApplicationFields` teaches the model about it
in the same commit.

### Why the suite could not have caught either

Every test of `call_llm` hands `_create_message` a payload **that already
matches the Pydantic models**, and every test of the child stubs the activity
out entirely. Both are correct tests of the code they cover, and both are
structurally blind to the two things that broke: the shape of the request that
goes out, and the schema the model is given. Stubs test our side of a contract;
only a live call tests the contract.

Two new tests close the specific holes — the transcript's last turn, and the
schema as it reaches `_create_message` rather than as written in the constant —
and the general lesson is promoted to `testing.md` below.

## Promoted to rules

**A stub proves our side of a contract, not the contract** — added to
`testing.md`. Second occurrence in this family: R-022 promoted *"a test that
greps a page proves the string is there, not that the page works"* for the
console, and this is the same fault one layer down. The remedy is the same
shape too — run the real thing once, deliberately, and assert on what crosses
the boundary.

**Never let the transcript end on an assistant turn** — added to
`payloads-and-activities.md`, on the *"it will bite a task you can name"*
clause: Task 20 replays this loop, and every future tool has to record its
result or reintroduce the same 400.

## R-025 — `make up` started nothing, and said it had

**Task 20.** The first task that needs a live stack, and the stack would not
start. `make up` printed all three URLs and `make status` then reported four
stopped processes.

**The problem.** R-001 fixed half of this and the other half survived, because
only the half `make status` exercised was ever run. `pgrep -f` matches whole
command lines, and the start recipes contain BOTH the guard pattern and the
command they start:

```make
@pgrep -f "[t]emporal server start-dev" >/dev/null 2>&1 || \
	(nohup temporal server start-dev --ui-port 8233 > ... &)
```

R-001's bracket idiom stops the *pattern* from matching itself. It does nothing
about the second occurrence: `nohup temporal server start-dev` is in the same
recipe, so it is in the same command line, and the regex `[t]emporal server
start-dev` matches it. The guard finds the recipe's own shell, concludes the
process is already running, and the `||` branch never fires. Reproduced
directly:

```
$ sh -c 'pgrep -af "[t]emporal server start-dev" || echo NOMATCH; true "nohup temporal server start-dev"'
2852 sh -c pgrep -af "[t]emporal server start-dev" || echo NOMATCH; true "nohup temporal server start-dev"
```

All four processes had it — `[c]ore_banking.app:app` against `uvicorn
core_banking.app:app`, `[w]eb.gateway:app` against `uvicorn web.gateway:app`,
`[p]ython.worker` against `python -m python.worker`. `make demo` was therefore
inert, on stage as much as here. `down`, `kill-worker` and `status` were never
affected: their recipes carry the bracketed pattern and nothing else.

**The ruling.** No regex fixes this — any pattern that matches the real
process's command line also matches the recipe text that starts it, and Make
expands its variables before the shell ever runs, so the literal is always
there. The command has to stop being part of a command line, so it moves into a
file: `make/start.sh <name>`, one `case` arm per process, invoked by each of
the four targets. That process shows up as `sh make/start.sh temporal`, which
no guard pattern matches, and the guard inside the script sees only real
processes.

**Authority.** Spec §14 mandates "`pgrep` guards so targets are idempotent" —
the mechanism, not its location. The guards are still pgrep guards and the
targets are still idempotent; they now also work.

**The cost.** One more file, and `make up` no longer reads as a self-contained
description of what it starts. Worth it: the alternative is a demo entry point
that lies, which is what §10.4's worker-kill beat runs through.

## Promoted to rules

**A `pgrep` guard must not share a command line with the command it guards** —
new file `.claude/rules/stack-and-make.md`, scoped to `Makefile`, `make/**` and
`python/Makefile`. This is the rule of two, clause 1: R-001 and R-025 are the
same fault, eight tasks apart, and the second one hid because the first one's
verification (`make status`) could not reach it. The rule carries the check
that would have caught both — start it, then ask the system, not the recipe.

## R-026 — the fixture recording is indexed by model calls, not by turns

**Task 20.** With the stack finally up, all three onboarding attempts failed
inside a second:

    FixturesExhausted: fixtures/acme-corp.json records 2 responses but the
    agent is on turn 3

**The problem.** `fixture_call_llm` selected its response with
`sequence[len(req.turns)]`. One recorded response is one model CALL, and a call
contributes exactly one *assistant* turn — but the transcript also carries tool
turns. R-024 made `request_documents` record its result on every path, so
iteration 1 leaves two turns behind, and iteration 2 asks for `sequence[2]` of
a two-response recording. The committed fixture is exactly that shape
(`request_documents`, then `submit_extraction`), so **every** fixture-mode run
died on its second call, three attempts deep, and the parent completed as
`manual_intervention` — a business status, correctly, which is why nothing
crashed and nothing looked obviously wrong.

**The ruling.** Count the calls, not the turns:

```python
call = sum(1 for turn in req.turns if turn.role == "assistant")
```

Fixed in the activity rather than by padding the recording: the recorder writes
one entry per call, which is the honest unit, and a fixture edited to line up
with a wrong index is the exact failure §16.7 exists to prevent.

**Why the suite was green.** `test_fixture_mode_advances_with_the_turn_count`
hand-built a transcript of one assistant turn — a shape
`ExtractionAgentWorkflow` never produces after a `request_documents` — and the
implementation agreed with it. The test and the code shared one wrong
assumption about what a turn is, so they confirmed each other. Third occurrence
of R-024's family, and the same shape: everything that touched the loop was a
stub, and the one thing that would have caught it was running the real loop
against the real recording.

**The cost.** Three tests. Two on the activity — the real two-turn shape, and a
tool result not consuming a response — and one that is the general remedy:
`test_the_committed_fixture_drives_the_real_loop` runs the actual child
workflow with the actual `fixture_call_llm` over `fixtures/acme-corp.json` and
asserts two iterations ending in §8.4's gap. All three fail against the old
index; the third is the one that would have found it unprompted.

## R-027 — four defects in the plan's Task 20 code

**Task 20.** The plan supplies `tools/capture_histories.py` and
`tests/test_replay.py` in full. Four things in them do not survive contact with
this repository, and three of the four present as something other than
themselves.

**1. The replayer was handed a random workflow id.** The plan calls
`WorkflowHistory.from_json(str(uuid.uuid4()), ...)`. That first argument is the
**workflow id**, not a label, and the parent derives its child's id from
`workflow.info().workflow_id` (§7). Replaying under an invented id therefore
fails with:

    Nondeterminism error: Child workflow id of scheduled event
    'onboarding-acme-corp-extract-1' does not match child workflow id of
    command '5235fd34-…-extract-1'

— a determinism failure in code nobody had touched, which is the worst possible
false positive for this particular gate. The started event carries the real id;
`_workflow_id()` reads it out of the history rather than deriving it from the
file name, which would drift.

**2. `_save` fetched child histories by id, and ids outlive runs.** Child ids
are derived from the parent id, so `onboarding-acme-corp-extract-2` exists as
soon as *any* earlier run reached attempt 2. The first capture attempt failed
three attempts deep (R-026), and the next capture dutifully filed those dead
children under `happy-path-extract-2.json` and `-3` — a happy path that
records two extra extraction attempts it never made, committed as a
determinism gate. `_save` now reads `ChildWorkflowExecutionStarted` out of the
parent's own history and fetches each child by (id, **run id**).

**3. `_wait` matched the stage it was trying to leave.** The plan polls for a
stage name. After a rejection the workflow is still `awaiting_review` on
attempt 1 until it re-ingests, so the reject-loop scenario's second wait
returned immediately and submitted the approval into attempt 1's already-closed
review. `_wait` now takes a predicate, and that scenario waits for
`awaiting_review AND attempt == 2`.

**4. The manifest wrappers spun their own event loop.** The plan's stubs call
`asyncio.new_event_loop().run_until_complete(...)` inside a sync test. Every
other async scenario in `test_manifest.py` is an `async def` delegating to an
`assert_*` helper, and pytest-asyncio is in auto mode. Followed the file's own
convention.

Also: the tool now `sys.path.insert`s the repo root (`testing.md`'s rule for
`tools/`, which the plan's version would have tripped on immediately), and
`_reset` terminates a leftover open run — the escalation scenario deliberately
leaves one, so without that a second `make histories` wedges on the 409 the
workflow id exists to produce.

**No promotion.** Defects 1 and 2 are specific to replay capture and are
recorded in `histories/README.md`, next to the files they explain. Defect 3 is
already covered by the "hanging test is a retry loop" habit — read the state,
do not assume the transition. Defect 4 is a convention the file states itself.

## R-028 — 23 setup errors that were the demo stack, not the suite

> **Superseded in part by R-030.** The reading below — that the demo stack
> caused it — did not survive the next occurrence, which happened with the
> stack down. The symptom and its shape (one fixture, 23 errors) still
> hold; the cause and the remedy are in R-030.

**Task 20, verification.** `make verify` came back with `184 passed, 23
errors`, every error at fixture *setup*:

    RuntimeError: Failed starting Temporal dev server: Failed connecting to
    test server after 5 seconds … ConnectionRefused

**The cause.** The demo stack was still up from the capture — dev server,
worker, gateway, core banking — and the suite starts a dev server of its own
with a five-second connect budget. Under that much company it lost the race.
The identical command passed with `make down` first: **207 passed, 0 skipped**.

R-019 chased this same message to a different cause (one server per *test*,
racing its own ports) and fixed it by making the `env` fixture session-scoped.
That fix stands; this is a second way to spend the same five seconds, and the
suite cannot do anything about it because the contention is outside it.

**The ruling.** No code change. `make down` before `make verify`, recorded in
`.claude/rules/stack-and-make.md` alongside R-025, because the failure looks
like a broken fixture and is not one — and an agent that reads it as a fixture
bug will "fix" a fixture that was right.

## R-029 — the root Makefile includes rather than forwards; the spec changed

**Task 20, in review.** Reading the Makefile, the reviewer could not find `up`,
`down`, `worker` or `kill-worker` in it — correctly, because the root file held
no recipes at all:

```make
up down status logs demo demo-reset worker kill-worker restart-worker \
gateway core-banking temporal test verify fixtures histories documents clean deps:
	@$(MAKE) --no-print-directory -C python $@
```

One rule with nineteen target names, forwarding each to `python/`, which
included `make/common.mk`, which held the actual recipes. Two hops from a
target's name to what it does, and the name written three times — the rule, the
`.PHONY` line, and `common.mk`.

**The change.** The root `Makefile` is now `include make/common.mk`;
`python/Makefile` stays `include ../make/common.mk`. `common.mk` gained
`.DEFAULT_GOAL := up`, which the forwarder used to carry, and which an include
does not supply on its own — the first target here is `deps`. Nothing forwards,
so no target list exists twice.

`ROOT` already made this work: it resolves through the included file's own path
in `MAKEFILE_LIST`, so it is the repo root from either entry point, and every
recipe uses `$(ROOT)` rather than the working directory. Verified from both:
same default goal, same absolute paths, and a full `up` / `status` /
`demo-reset` / `down` cycle from the root.

**Authority — and this one is different from every other ruling here.** The
rest of this log records decisions taken *within* the spec. This one changes
it: §15's layout line read "`Makefile` — forwards to python/", and a ruling
cannot overrule the binding authority. So the spec was amended first (§14 gains
the one-definition-two-entry-points paragraph and the rejected alternative, §15
the new layout line), then the plan's file table and Task 1 Step 6, then the
code. The decision was the repository owner's, made in review; the ordering is
`DEVELOPMENT-PROCESS.md`'s.

**What the old shape bought, and why it was still worth losing.** Forwarding
made the root file a table of contents: every target visible in one screen. The
multi-SDK story it was for is served better by the include — a `go/Makefile`
is the same one line, and the root does not have to choose which SDK to forward
to. The cost of the old shape was silent: a target added to `common.mk` and not
to the root's list is simply absent, and reports as `No rule to make target`.

**Promoted** to `.claude/rules/stack-and-make.md`, first occurrence, on the
"it will bite a task you can name" clause: Task 21 edits the README's command
list, and re-adding a forwarding rule is exactly the tidy-looking change
someone makes when they want the target names visible at the root again.

## R-030 — R-028's cause was wrong: the dev server start is just flaky

**Task 20, review follow-up.** R-028 blamed the demo stack for 23 setup errors
and prescribed `make down` first. The next `make verify` produced the identical
23 errors **with the stack down**, seconds after it had been stopped. The
explanation was wrong, so it is withdrawn here rather than left to be believed.

**What was actually measured, on one machine on one day:**

| Observation | Result |
|---|---|
| Full suite runs | 6; 2 failed this way, 4 green — same command each time |
| Failures with the demo stack up / down | one each |
| `start_local` standalone, back to back | 5 of 5, **0.21s** each — the 5s budget is 20× generous |
| Consecutive suite runs after the second failure | 3, all `207 passed`, nothing changed |
| Server binary re-downloaded? | No — cached at `/tmp/temporal-sdk-python-1.32.0` |

So: intermittent, environmental, in the spawning of the ephemeral server, and
unrelated to anything the suite or the stack does. It is R-019's message for a
*third* distinct reason, which is worth naming — that message means "a dev
server did not come up in five seconds" and nothing more specific, and each
time it has been tempting to read it as a broken fixture.

**The ruling.** Retry the start once, in the `env` fixture. There is no
configuration fix: the five seconds are compiled into the Rust bridge and
`WorkflowEnvironment.start_local` exposes no timeout parameter (checked against
the installed SDK's signature). The retry is narrow — it matches only
`Failed starting Temporal dev server` and re-raises anything else, so a genuine
fault still fails on its own traceback rather than a confusing second one.

**Why the fixture and not the caller.** Session scope is what makes this worth
fixing rather than tolerating: one failed start errors all 23 dependent tests
at setup, so the blast radius of a hiccup is the entire workflow half of the
suite, and the failure reads as 23 broken tests to whoever finds it. Same
reasoning as R-019, which made this fixture session-scoped in the first place.

**The lesson, which is the part worth keeping.** R-028 was written from two
data points that happened to agree with a plausible story, and the story was
checked only against the run that suggested it. One contrary run and five
minutes of measurement was all it took to disprove. **Before promoting a
diagnosis into `.claude/rules/`, reproduce it deliberately — a rule is read as
settled fact by everyone who comes after, and a wrong one sends them to fix
something that was never broken.**

## R-031 — the same flake, the other fixture; and a green gate I did not read

**Immediately after R-030.** The next `make verify` failed with one error, not
23:

    ERROR at setup of test_T_TIME_01_remind_then_escalate_fire_in_order
    RuntimeError: Failed starting test server: Failed connecting to test
    server after 5 seconds …

R-030 retried `env` (`start_local`, the *dev* server) and stopped there.
`skip_env` calls `start_time_skipping`, which spawns the *test* server — a
different binary and a different message, the same ephemeral spawn against the
same five-second budget compiled into the same bridge. One run was enough to
find it, which says the retry belonged at the shared step from the start.

**The ruling.** `_started_with_one_retry(starter)` takes the starter as an
argument and both fixtures use it; the guard matches either message and
re-raises anything else. Naming one starter in a helper for a fault that
belongs to both was the mistake, and the fix is the shape, not another clause.

**The second half of this, which is worse.** The run that produced this error
still got committed and pushed. The command was:

```
make verify 2>&1 | tail -2 && git add -A && git commit …
```

A pipeline's status is its **last** command's, so `&&` read `tail`'s zero and
proceeded. `make/common.mk` documents this exact trap directly above the
`verify` recipe — it is why the recipe routes pytest's status through a file
rather than through `tee` — and it was still walked into, from outside, on the
gate that trap was documented for. The commit was docs-only and the suite was
one flake short of green, so nothing bad shipped; that is luck, not a process.

**Never gate on a piped command's status.** Redirect to a file and read the
file, or check `${PIPESTATUS[0]}` — and when the gate is `make verify`, run it
bare and look at the last line before committing. Added to
`.claude/rules/stack-and-make.md` beside the flake it hid.

## R-032 — §13.1 was written mid-Stage-3; and "ratified" is not "measured"

**Between Task 20 and Task 21, in review.** §13 fixed the console's functional
surface and closed with "Visual design is Stage 3 work", naming no task to do
it. So the pass never ran: Tasks 8, 11 and 18 each added CSS in passing and
left 284 lines with a coherent palette and no system — fourteen font sizes,
eight weights, no spacing unit, and two breakpoints that disagreed with each
other for no recorded reason.

**Why this is a ruling and not just a task.** The plan had 21 tasks and none of
them covered this, so building it would have been code with no authority behind
it. Per R-029 the order is spec → plan → code: §13.1 was written first (seven
subsections — tokens, type scale, spacing, layout, accessibility, the
light-first divergence, and what is out of scope), then Task 22 was added to
the plan, and only then does any CSS move. Task 22 is numbered last but **runs
before Task 21**, because Task 21 walks the console by hand and writes the
README against what it sees. The number is a label, not a position, exactly as
Task 4 is labelled `SCHEDULE FIRST`.

**The palette was ratified rather than replaced** — deliberately. The colours
Tasks 8/11/18 produced are good, and a visual pass that repaints a working
palette is churn. What was missing was a written system, so every new callsite
invented its own size and spacing.

**And that is where this went wrong.** "Ratified" was done by reading the
stylesheet. Nobody measured it. Three pairs fail §13.1.5's own 4.5:1 floor:

| Pair | Measured | Where |
|---|---|---|
| `--wait` on `--wait-wash` | **4.40:1** | The stage pill in `is-waiting` |
| `#fff` on `--done` | **2.11:1** | `.btn.go`, dark theme |
| `#fff` on `--alert` | **2.52:1** | `.stepper li.is-failed .step-n`, dark |

The first is the worst of the three, and not because of the margin. `--wait` is
the *normal* state — §13.1.1 says so out loud — and the demo sits on that pill
for the entire KYC beat. The two literals fail because `--done` and `--alert`
invert between themes and a hardcoded white cannot follow them; the palette had
`--accent-ink` for exactly this and simply never grew the other two.

**The fix.** `--wait` darkens one step to `#985c09` (4.85:1) — hue and chroma
unchanged, and the only value in the palette that moved. `--done-ink` and
`--alert-ink` join `--accent-ink`, giving 9.01:1 and 7.55:1 in dark. §13.1.1
now says every strong fill carries an ink token, and §13.1.5 says a colour is
not ratified until it has been measured.

**Cost.** The mockup in `docs/design/` and both screenshots had to be re-shot,
because a mockup that no longer matches the spec reads as approved when it is
not — its own README says so.

**What the verification would have caught, and did not.** Task 22's browser
drive loaded the console over `file://`. The page's first act is
`fetch("/api/status/...")`; under that scheme Chromium refuses the request, so
`#review` stays `hidden`, `#detail` stays empty, and the contrast audit skipped
three of its four selectors while the screenshots showed an idle page reading
"Gateway unreachable". The audit ran against a screen the demo never shows. It
now serves the page from a routed `http://` origin with a stubbed status
payload in `awaiting_review`, asserts each selector actually rendered rather
than skipping a missing one, and covers eleven pairs including the strong
fills.

Two of the eight proposed tests could not fail either: the retired-token check
carried trailing colons, so it saw stale *declarations* but not the stale
`var()` *references* that a regex rename across 948 lines actually risks; and
the type-scale audit goes vacuous the moment every size becomes a `var()`.
Ten tests now, with the scale tokens checked against their values.

**Promoted** to `.claude/rules/testing.md`, on the rule of two: this is the
second time a gate has been green against something it could not see. R-022
said grep-level tests pass against a page whose JavaScript throws; this says
they also pass against a page that never reached the state under test, and that
a check which `continue`s past a missing selector is not a check. Both clauses
live beside R-022's, because the next person to write a Playwright audit will
reach for `file://` and for `if not el: continue` in the same sitting.

## R-033 — the responsive block lost the cascade, and only a browser saw it

**Task 22, Step 11 and Step 14.** The plan said "delete the 860px query and
fold `.cols` into the 900px query". Followed literally, that put
`.cols { grid-template-columns: 1fr }` inside a media block at line 192, while
the unconditional `.cols { grid-template-columns: 1.55fr 1fr }` sat at line
307. Identical specificity — `@media` contributes none — so the later rule won
and **the columns never collapsed**. At 820px the console still rendered Case
Actions and Demo Controls side by side.

**Every grep-level test passed.** `test_there_is_exactly_one_breakpoint` saw
exactly one breakpoint. The declaration was present, the value was right, the
selector was right. Nothing in a text search can distinguish a rule that
applies from a rule that is overridden three hundred lines later, because the
difference is not in the text — it is in the order.

Step 14's browser drive caught it: measured `.cols` at 452px + 291px on a
820px viewport, where it should have been one column. Fixed by moving the whole
responsive block to the end of the stylesheet, after every rule it overrides,
and verified at the boundary — 901px gives two columns, 900px gives one.

**Promoted, and it meets the rule of two on its own terms.** This is the third
green gate that could not see what it was guarding: R-022 (tests pass against a
page whose JavaScript throws), R-032 (tests pass against a page that never
reached the state under test), and now a test that passes against a rule which
never applies. The pattern is not "write more greps" — it is that a grep
asserts the presence of text and CSS behaviour is decided by cascade, media
state and DOM state, none of which are text.

The plan's Step 11 is corrected to say *where* the block goes and why. An
eleventh test pins source order — `.cols {` and `.stepper {` must both appear
before `@media (max-width: 900px)` — and it was proven by planting the
regression and watching it fail, because a guard nobody has seen fail is a
guess. That takes the console suite to 31 and the whole suite to 218; the
§16.8 manifest is untouched at 22, since these are ordinary tests and not
scenarios.
