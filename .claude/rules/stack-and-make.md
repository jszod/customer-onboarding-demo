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

## A `pgrep` guard must not share a command line with the command it guards

`pgrep -f` matches **whole command lines**, and a recipe is a command line. A
recipe that both greps for a pattern and contains the command it would start
matches its own shell:

```make
# BROKEN — the guard finds itself, every time
@pgrep -f "[t]emporal server start-dev" >/dev/null 2>&1 || \
	(nohup temporal server start-dev --ui-port 8233 > /tmp/x.log 2>&1 &)
```

The bracket idiom (`[t]emporal`) stops the *pattern* from self-matching. It
does nothing about the start command sitting three words later in the same
line. No regex fixes this — anything that matches the real process matches the
text that starts it — and Make expands variables before the shell runs, so
splitting the literal does not help either.

**So the start command lives in `make/start.sh`, one `case` arm per process,
and the recipe just calls it.** A file's contents are not a command line: the
script runs as `sh make/start.sh temporal`, which no guard matches.

This has happened twice — R-001 (`make status` reported four running processes
in a container with no Temporal CLI installed) and R-025 (`make up` started
nothing and printed the URLs anyway, found only when Task 20 needed a live
stack). The second one hid for eight tasks because the first one's fix was
verified with `make status`, whose recipe has no start command in it.

## Verify a process target by asking the system, not the recipe

A start target that prints "started" has proved nothing. The check is:

```
make up && sleep 5 && make status      # then look at the log
tail /tmp/onboarding-worker.log        # "worker polling customer-onboarding"
curl -s localhost:8001/ledger          # the service answers
```

`make status` is a genuinely independent reading — its recipe contains only the
bracketed patterns — and the log says which mode the worker came up in
(`call_llm implementation: fixture_call_llm`), which is the other thing that
silently changes what a run means.

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
