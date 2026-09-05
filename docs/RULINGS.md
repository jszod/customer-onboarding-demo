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
