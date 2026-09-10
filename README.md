# Customer Onboarding Demo

A commercial bank onboards a new business client. The process is seven steps,
one of which is AI. It runs on Temporal, and the point of the demo is what
happens when things go wrong.

## What this shows

Three things, and the third is the one people remember.

**1. A long-running human gate.** KYC review takes days. The workflow sleeps on
a durable timer through it, survives a worker restart mid-wait, and **never
auto-approves** — a workflow that approved a bank application because a timer
fired would be a compliance incident. The timers remind and escalate; only a
human closes the gate.

**2. AI as a contained, durable tool.** Document extraction is a bounded child
workflow running a hand-rolled agent loop. It is retried, recorded and
replayable like any other work, its attempts are capped, and when it cannot
finish it hands the gap to a human rather than guessing. Here it reads five
documents and finds 22 of 23 required fields — the beneficial owner's date of
birth is in none of them, so the analyst is asked for exactly that one field,
with the reason and the list of documents already searched.

**3. The ambiguous timeout — the headline.** Core banking receives the account
request, **creates the account**, and then fails to answer within the 5-second
timeout. The workflow cannot tell "the request never landed" from "it landed
and the reply was lost". It retries. Because the idempotency key is the
workflow ID — stable across every attempt, never a retry counter — core banking
recognises the repeat and returns `duplicate`. The ledger holds **exactly one
account**.

That last one is the whole demo. Retry alone opens two accounts; retry plus a
stable key opens one.

## The seven steps

| | Step | What happens |
|---|---|---|
| 1 | Collect documents | Five PDFs ingested; refs and hashes enter the workflow, never the content |
| 2 | Extract & structure | The agent child fills the application and reports what it could not find |
| 3 | KYC review | The durable human gate. Days, or seconds on a demo profile |
| 4 | Open account | The ambiguous timeout lives here |
| 5 | Receive client ID | Core banking calls back asynchronously |
| 6 | Send documents | The welcome pack |
| 7 | Notify | Specialist and client, or specialist and supervisor if it ended badly |

Every failure path ends in a **business status**, never a failed workflow. A
failed workflow reads as a bug; a completed one carrying `manual_intervention`,
`rejected_by_core` or `already_onboarded` reads as a process.

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

## Walking the demo

Roughly four minutes. Two browser tabs: the console on `:8000`, the Temporal UI
on `:8233`. Everything below has been walked end to end; the numbers are from a
real run.

**Before you start:** `make demo`, not `make up`. The reset matters — see the
note under Commands.

1. **"Here is the case."** The console shows the client, seven steps, and
   *Not started*. Nothing is running yet; the page polls a workflow that does
   not exist and renders that as an idle state rather than an error.

2. **Press Submit.** Steps 1 and 2 tick over. In the Temporal UI the workflow's
   Current Details shows the same seven steps with `→` on the live one — one
   `stage` value, two surfaces, and both readable *during* the wait rather than
   only afterwards.

3. **"The AI found 22 of 23 fields."** The gap panel opens on the one it could
   not: `beneficial_owners[1].dob`, with the reason and the five documents it
   searched. **Approve is disabled.** This is worth pausing on — the agent did
   not invent a date, and the workflow will not proceed without a human.

4. **Kill the worker.** `make restart-worker`. The console keeps polling; the
   workflow is asleep on a durable timer with nothing running. When the worker
   returns, the case is exactly where it was. *"The process outlived the
   process running it."*

5. **Fill the date, tick the attestation, Approve.** Both are enforced twice —
   the button is disabled client-side, and the update validator refuses the
   same thing server-side, so the gate holds against a curl as well as a click.

6. **"Now watch step 4."** `submitting_to_core` shows `attempt 1`, then
   `attempt 1: activity StartToClose timeout`, then attempt 2. In the Temporal
   UI's Timeline these are two labelled rows: *Submit account request to core
   banking (attempt 1)* and *(attempt 2)*.

7. **"How many accounts did we just open?"** `curl -s localhost:8001/ledger`
   → **one**. Then the payoff: *"The first call succeeded. We just never heard
   back. The retry carried the same idempotency key, so the core recognised it
   and returned `duplicate`."* The console says so too.

8. **Return client ID**, and the case completes with the account number.

## The failure beats

Three, each triggerable on demand. The first is the headline; the other two are
§10.4's secondary beats.

| Beat | How to trigger | What to point at |
|---|---|---|
| **Ambiguous timeout** | On by default; the *Slow first core-banking call* toggle in Demo Controls turns it **off** for a clean pass | Two attempts in the Timeline, one account in the ledger |
| **Worker kill** | `make restart-worker` during either durable wait | The case resumes exactly where it was, instantly |
| **Model outage** | The *Model outage* toggle | `call_llm` fails; the agent loop retries and resumes mid-extraction rather than restarting it |

A fourth, if someone asks *"what if we onboard the same client twice?"*: submit
again without resetting. Core banking answers `duplicate` on the **first**
attempt, which means a previous onboarding owns the account — so the workflow
stops at `already_onboarded`, sends no welcome pack, and notifies the
specialist and supervisor rather than the client.

## Running it without an API key

`FIXTURE_MODE=1` replays a committed recording of the extraction instead of
calling the model. The workflow, the child, the gaps and the escalation are all
identical — it is the same code path, driven from `fixtures/acme-corp.json`.

    FIXTURE_MODE=1 make demo     # the whole demo, keyless
    make verify                  # always keyless; the suite forces it

`make test` and `make verify` force `FIXTURE_MODE=1` and never touch the
network, so a fresh clone reaches a green suite with no key at all. A key is
needed for exactly two things: driving the demo live, and re-recording the
fixtures with `make fixtures`.

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

## Talking through it without running it

If the laptop will not cooperate, or the conversation is a design review rather
than a demo, these two stand on their own:

- **[`TALK_TRACK.md`](TALK_TRACK.md)** — the narration, written to be read
  aloud, and to still make sense to someone reading it afterwards with nobody
  to ask.
- **[`docs/DESIGN-DIAGRAMS.md`](docs/DESIGN-DIAGRAMS.md)** — three annotated
  diagrams: how the process fits together, the failure that matters, and
  what is inside the AI step.

## Adding another SDK

**[`CONTRACT.md`](CONTRACT.md)** is the wire surface written SDK-agnostically —
workflow IDs, the task queue, every signal, query and update name, and the
payload shapes. A Go, Java or TypeScript worker implements that contract and
polls the same task queue; nothing in `web/` or `core_banking/` changes,
because neither imports worker code. Only one worker can poll at a time, which
is why this repo ships one (§18).

## Where the design lives

Written in that order, and the spec wins where they disagree.

| Document | What it is |
|----------|------------|
| [`docs/superpowers/specs/2026-09-04-customer-onboarding-design.md`](docs/superpowers/specs/2026-09-04-customer-onboarding-design.md) | **The binding authority.** 22 sections; settles everything. |
| [`docs/superpowers/plans/2026-09-04-customer-onboarding-demo.md`](docs/superpowers/plans/2026-09-04-customer-onboarding-demo.md) | 24 tasks. How the spec gets built. |
| [`docs/RULINGS.md`](docs/RULINGS.md) | The execution log — every deviation from the plan, with its reasoning. Most of the interesting bugs are in here. |
| [`docs/demo-brief.md`](docs/demo-brief.md) | 11 numbered decisions, with the **rejected** alternatives. |
| [`docs/DEVELOPMENT-PROCESS.md`](docs/DEVELOPMENT-PROCESS.md) | The four-stage process this repo follows. |

`docs/design/` holds the console's visual reference, and `histories/` holds
nine captured workflow histories that `tests/test_replay.py` replays on every
run — the gate that catches an innocuous edit breaking determinism.
