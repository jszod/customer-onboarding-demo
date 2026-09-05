# Execution log — rulings made during the build

Spec §19 pre-answers the seven ambiguities judged most likely. This file
records the ones it did not: decisions taken while implementing the plan,
where the spec and plan together left a gap or the plan's own code was wrong.

The plan expects this file to exist — Tasks 16 and 17 both say "record this as
a ruling in the execution log" — but no task creates it. Task 1 does.

Format: one entry per ruling, newest last. Say what was decided, against which
authority, and what it cost.

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
