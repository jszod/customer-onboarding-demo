# Customer Onboarding Demo

A Temporal demo: a commercial bank onboards a business client through a
seven-step deterministic workflow containing a bounded AI extraction child
workflow.

> **Stage note.** Design is complete; implementation has not started. The full
> README — the demo story, the walkthrough, the failure beats — is plan Task 21.
> What follows is the machine setup, which is true today and does not depend on
> any code being written yet.

## Setup

Three things, in this order. Only the first is specific to this demo.

### 1. Temporal CLI

`make demo` starts a local Temporal dev server by shelling out to
`temporal server start-dev` (§14 of the spec — host processes, no Docker), so
the CLI has to be on your `PATH` before anything else works. It ships as a
single binary that bundles both the dev server and the Web UI.

    brew install temporal

Upgrading an existing install is `brew upgrade temporal`. On a machine without
Homebrew, see the [Temporal CLI install
docs](https://docs.temporal.io/cli/setup-cli).

Then confirm the install, and the version floor with it:

    temporal --version
    # temporal version 1.8.3 (Server 1.31.2, UI 2.50.1)

**The UI number is the one that matters.** §12 sets a floor of **UI v2.34.6**,
because activity summaries on the Timeline — the thing that makes the Temporal
UI read as the business process rather than as a stack trace — do not render
below it. Any recent CLI clears that floor comfortably; if you are on an old
install, upgrade rather than debugging a missing summary as a code bug.

You do not start the server by hand. `make demo` does it, guarded by `pgrep` so
it is idempotent, and `make down` stops it. If the console comes up but nothing
progresses, check `make status` first — a missing CLI shows up there as
`temporal : stopped`, and the reason will be in `/tmp/onboarding-temporal.log`.

### 2. uv

Dependencies are managed with [uv](https://docs.astral.sh/uv/); `make deps`
runs `uv sync`.

    curl -LsSf https://astral.sh/uv/install.sh | sh

### 3. `ANTHROPIC_API_KEY` — only if you are re-recording fixtures

The test suite runs keyless. Fixtures for the extraction loop are committed, and
`make test` runs with `FIXTURE_MODE=1`, so a fresh clone can reach
`make verify` with no API key at all.

The key is needed for exactly two things: running the live demo (`make demo`),
and re-recording the fixtures (`make fixtures`, which §16.7 calls the one
prerequisite a human must supply, and only once).

`FIXTURE_MODE=1 make demo` runs the whole stack keyless off the committed
recording — the same path the suite takes, and the mode `make histories`
captures in. Every step is real except the model call.

    cp .env.example .env      # then put the key on the ANTHROPIC_API_KEY line

`make` reads `.env` if it is there and exports it to the worker, gateway and
core banking service. It is gitignored, it is optional — no file and no key
still reaches `make verify` — and `.env.example` lists every §17 knob with its
default, so the SLA timers and the demo profile are discoverable in one place.
A plain `export ANTHROPIC_API_KEY=…` in your shell works just as well; note
that a value in `.env` overrides it.

## Quickstart

    make deps
    make demo     # → console :8000, Temporal UI :8233, core banking :8001
    make verify   # the definition of done: green, and nothing skipped

`histories/` holds the committed replay gate. Re-capture it with
`FIXTURE_MODE=1 make up && make histories` only when the workflows' command
sequence changes on purpose — `histories/README.md` says what that means.

## Commands

**`make help`** prints this list, and it is generated from the targets
themselves rather than maintained by hand, so it cannot fall behind
`make/common.mk`. The table below is the same content for reading on the web.

| | |
|---|---|
| **Setup** | |
| `make deps` | `uv sync` — install everything |
| **Running the demo** | |
| `make demo` | reset state, start all four processes, print the URLs |
| `make up` | start them *without* resetting — keeps the ledger, so the ambiguous-timeout beat will not re-fire |
| `make down` | stop everything this Makefile started |
| `make status` | which of the four processes are up, and on which ports |
| `make logs` | tail all four process logs from `/tmp` |
| `make demo-reset` | clear the ledger, outbox, document store and outage flag |
| `make restart-worker` | the worker-kill beat — prove the workflow survives it |
| **Verifying** | |
| `make test` | run the suite under `FIXTURE_MODE=1`; no API key needed |
| `make verify` | the definition of done: green **and** nothing skipped |
| **Rebuilding inputs** | |
| `make documents` | regenerate the sample PDFs under `documents/` |
| `make fixtures` | re-record `fixtures/` against the live model (needs a key) |
| `make histories` | re-capture `histories/`, the replay gate's input |
| `make clean` | `down` + `demo-reset` |

Two things that are easy to trip on:

- **A bare `make` runs `up`**, not `help` — `.DEFAULT_GOAL := up`, because
  these verbs exist for muscle memory across the sibling demos (§14).
- **`make up` does not reset the ledger**, and the idempotency key is derived
  from the client key rather than a UUID (§4.1). So the ambiguous-timeout beat
  fires once per ledger: core banking answers `duplicate` before it reaches its
  delay, and the "Slow first core-banking call" toggle then looks broken. Use
  `make demo`, which chains `demo-reset`. A second onboarding for a client who
  already has an account now terminates as `already_onboarded` and says so
  (§10.1.1).

## Where the design lives

| Document | What it is |
|----------|------------|
| `docs/superpowers/specs/2026-09-04-customer-onboarding-design.md` | The binding authority. 22 sections. |
| `docs/superpowers/plans/2026-09-04-customer-onboarding-demo.md` | 21 tasks, 127 steps. How the spec gets built. |
| `docs/demo-brief.md` | 11 numbered decisions, with the rejected alternatives. |
| `docs/DEVELOPMENT-PROCESS.md` | The four-stage process this repo follows. |
