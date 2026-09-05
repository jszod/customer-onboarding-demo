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

## Known transient — `make verify`'s message overstates until Task 3

`make verify` prints "VERIFY OK: 22/22 scenarios implemented and passing"
whenever nothing is skipped. Between Task 1 and Task 3 that is a false green:
only `tests/test_config.py` exists, so the gate passes on 4 tests. Task 3 lands
the 22-scenario manifest as skip-marked stubs, at which point the gate fails
with 22 skips and the number means what it says. Not fixed here, because the
message becomes true exactly when the manifest lands and changing it now would
diverge from the plan's text for one task's duration.
