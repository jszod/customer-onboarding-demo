---
paths:
  - "Makefile"
  - "make/**"
  - "python/Makefile"
---

# Stack and Make rules

Spec §14. These targets are the demo's entry point: `make demo` is the first
thing that runs on stage and the last thing anybody debugs there.

## One definition, many entry points

Every target lives in `make/common.mk`. The root `Makefile` and
`python/Makefile` are one-line includes of it, and a second SDK's makefile
would be a third. **Do not add a forwarding rule** — a root rule that lists the
targets and re-invokes `$(MAKE) -C python $@` writes the list a second time (a
third, with `.PHONY`), and a target added to `common.mk` but missed in the copy
is then absent with nothing but `No rule to make target` to say so. That shape
was the original one and the spec now rejects it explicitly (R-029).

Two consequences worth knowing:

- **Recipes must not depend on the working directory.** `make` may be invoked
  from the repo root or from `python/`. Use `$(ROOT)`, which resolves through
  this file's own entry in `MAKEFILE_LIST` and is absolute from either.
- **`.DEFAULT_GOAL := up` lives in `common.mk`.** An include contributes no
  first target to inherit as the default, and the first target here is `deps`.

## The command-line-matching guard is retired — Task 26 replaced it with pid files

This section used to describe a whole-command-line-matching guard (a `case`
arm per process in `make/start.sh`) that stopped the guard from matching its
own recipe. That hazard is gone by construction now, not by carefulness: every
process target is `@$(ROOT)/demo.sh <verb>`, and `demo.sh` tracks liveness with
a recorded pid in `.run/<name>.pid`, checked with `kill -0`, never by scanning
command lines. There is no pattern to self-match because there is no pattern.

This has happened twice — R-001 (`make status` reported four running processes
in a container with no Temporal CLI installed) and R-025 (`make up` started
nothing and printed the URLs anyway, found only when Task 20 needed a live
stack). The second one hid for eight tasks because the first one's fix was
verified with `make status`, whose recipe had no start command in it.
`make/start.sh` (R-025's fix) is itself gone as of Task 26 — its reason for
existing, giving the start command a file to live in so no guard's command
line could contain it, is moot once nothing greps command lines at all. See
R-038 and `demo.sh`'s own header comment for the two facts that replaced it:
the venv interpreter is started directly (never through `uv run`, which forks
a child that owns the port `$!` does not record), and `nohup` is what keeps
`$!` correct.

Windows-under-Git-Bash is why command-line scanning could never have come
back: that shell has no procps, so the tool the old guard depended on does not
exist there at all.

## Verify a process target by asking the system, not the recipe

A start target that prints "started" has proved nothing. The check is:

```
make up && sleep 5 && make status      # then look at the log
tail .run/worker.log                   # "worker polling customer-onboarding"
curl -s localhost:8001/ledger          # the service answers
```

`make status` is a genuinely independent reading — it asks the OS whether the
recorded pid is alive, not whether the recipe printed something — and the log
says which mode the worker came up in (`call_llm implementation:
fixture_call_llm`), which is the other thing that silently changes what a run
means.

## 23 tests erroring at setup is one fixture, and it is the machine

    Failed starting Temporal dev server: Failed connecting to test server
    after 5 seconds … ConnectionRefused

The suite starts its own dev server (`WorkflowEnvironment.start_local`) and the
bridge gives it five seconds to answer. When that fails, the session-scoped
`env` fixture fails once and all 23 tests that depend on it error at *setup* —
one environmental hiccup wearing the costume of 23 broken tests.

It is intermittent and it is not the demo stack: it happened both with the
stack up and with it down, and three consecutive clean runs followed with
nothing changed (R-030 has the measurements). `conftest.py` retries the start
once, which is the only lever — the budget is compiled into the Rust bridge and
neither starter takes a timeout argument.

Both ephemeral servers do this. `start_local` says "Failed starting Temporal
dev server" and `start_time_skipping` says "Failed starting **test** server";
they are different binaries with the same five seconds. `_started_with_one_retry`
takes the starter as an argument for that reason — retrying one and not the
other bought exactly one run (R-031). One error at setup is `skip_env`;
twenty-three is `env`.

## Never gate on a piped command's exit status

    make verify 2>&1 | tail -2 && git commit …      # WRONG — that is tail's zero

A pipeline's status is its last command's, so this commits over a red suite.
`make/common.mk` carries the same trap in prose above the `verify` recipe — it
routes pytest's status through a file rather than `tee` for exactly this — and
it has still caught someone from the outside since (R-031). Run `make verify`
bare and read its last line, or redirect to a file and check that, or use
`${PIPESTATUS[0]}`.

So if you see it: it is not a broken fixture and there is nothing to fix in the
test. Run it again. If it survives the retry *and* a re-run, look at the
machine — load, file descriptors, a port range in use — not at the suite.
Taking the demo stack down first is still good hygiene (it is four processes
competing for the same machine), but it is not the cause and it is not a fix.

## `make up` runs keyless only if you tell it to

The suite forces `FIXTURE_MODE=1`; the stack does not. `make up` starts a
worker in whatever mode the environment says, so a stack brought up without a
key and without `FIXTURE_MODE=1` fails on the first model call — classified,
non-retryable, and visible only in the worker log.

Bring it up as `FIXTURE_MODE=1 make up` unless you mean to spend a key. That is
also the mode `make histories` must capture in: a captured history is a record
of a reproducible run, and the recorded fixtures are what make it one.

## `.env` is read by Make, not by Python

`make/common.mk` does `-include .env` then `export`, so every recipe's
subprocess inherits it (R-020). Nothing in `python/` reads a `.env` file. A
variable that must reach the worker has to be in that file or in the
environment of the `make` invocation — setting it inside a recipe's shell
reaches nothing else.

## A stale worker presents as an HTTP timeout, not as stale code

`make up` and `make demo` guard the worker with a recorded pid, so **they will
not restart a worker that is already running** — by design, the guard is what
makes the targets idempotent. The cost is that a worker keeps the classes it
imported at startup. Change a model and the running worker still holds the
old one.

The symptom is not an import error. In R-037 a worker predating an added field
raised `AttributeError: 'OpenAccountAck' object has no attribute 'attempt'`,
which failed the **workflow task** — and workflow tasks retry forever. So the
`status` query could never be served, and what surfaced was
`httpx.ReadTimeout` on a status poll 30 seconds later, in a tool that had not
changed.

After editing anything under `python/`, `make restart-worker`. If a stack
behaves as though your change is not there, check the worker's start time
against the file's mtime before debugging the code:

    ps -o lstart= -p $(cat .run/worker.pid)
    stat -f '%Sm' python/models/whatever.py

**And pass the mode to the target that starts the worker.** `FIXTURE_MODE=1
make histories` sets it for the capture tool, not for the worker a separate
`make restart-worker` just started — that one came up live. R-037 captured a
whole set of histories against the real API that way. `grep 'call_llm
implementation' .run/worker.log` is the one-line check, and it is worth
running before every capture.
