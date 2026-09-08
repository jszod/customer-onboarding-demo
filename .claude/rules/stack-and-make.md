---
paths:
  - "Makefile"
  - "make/**"
  - "python/Makefile"
---

# Stack and Make rules

Spec §14. These targets are the demo's entry point: `make demo` is the first
thing that runs on stage and the last thing anybody debugs there.

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

## `make down` before `make verify`

The suite starts its own dev server (`WorkflowEnvironment.start_local`, one per
run) and gives it five seconds to answer. A demo stack running alongside it —
server, worker, gateway, core banking — is enough to lose that race on a busy
machine: 23 tests erroring at *setup* with

    Failed starting Temporal dev server: Failed connecting to test server
    after 5 seconds … ConnectionRefused

which is the same symptom R-019 chased, from a different cause. Nothing was
wrong with the tests; the same command passed with the stack down. So take the
stack down before running the suite, and read a setup-time connection error as
contention rather than as a broken fixture.

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
