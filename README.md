# Customer Onboarding Demo

A commercial bank onboards a new business client. The process is seven steps,
one of which is AI. It runs on Temporal, and the point of the demo is what
happens when things go wrong.

**Setting up:** [macOS or Linux](#setup-on-macos-or-linux) ·
[Windows](#setup-on-windows). After that everyone follows the same
[walkthrough](#walking-the-demo).

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

## Prerequisites

The same three things on every platform. Only the install command differs.

| What | Why | macOS / Linux | Windows |
|---|---|---|---|
| **Temporal CLI** | One binary carrying both the dev server and the Web UI. Nothing starts without it | `brew install temporal` | **No package manager.** [Download](https://temporal.download/cli/archive/latest?platform=windows&arch=amd64), unzip, and put `temporal.exe` on your `PATH` — see below |
| **uv** | Dependencies, and it builds the virtualenv for you | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | `winget install --id=astral-sh.uv -e` |
| **Python 3.12** | uv can manage this for you | usually already there | `winget install Python.Python.3.12` |

**The Temporal CLI has no winget/Chocolatey/Scoop package** — [Temporal's own
install docs](https://docs.temporal.io/cli/setup-cli) document exactly one route
on Windows, and it is the manual one. Grab
[amd64](https://temporal.download/cli/archive/latest?platform=windows&arch=amd64)
or [arm64](https://temporal.download/cli/archive/latest?platform=windows&arch=arm64),
extract the archive, and add the folder holding `temporal.exe` to your `PATH`.
Reopen Git Bash afterwards so it picks the change up, then check `temporal
--version` answers.

Then check the version, because one number matters:

    temporal --version
    # temporal version 1.8.3 (Server 1.31.2, UI 2.50.1)

**The UI number is the one to read.** §12 sets a floor of **UI v2.34.6**,
because activity summaries on the Timeline — the thing that makes the Temporal
UI read as the business process rather than as a stack trace — do not render
below it. Any recent CLI clears it comfortably. If yours does not, upgrade
rather than debugging a missing summary as a code bug.

### The API key, and running without one

**You do not need a key.** The extraction fixtures are committed, and
`FIXTURE_MODE=1` replays them instead of calling the model. The workflow, the
child, the gaps and the escalation are all identical — the same code path, fed
from `fixtures/acme-corp.json`. Every step is real except the model call.

    cp .env.example .env

Leave `ANTHROPIC_API_KEY` blank and set `FIXTURE_MODE=1`. Put a real key on
that line and drop `FIXTURE_MODE` when you want the live model.

`.env` is gitignored, optional, and `.env.example` lists every §17 knob with
its default — the SLA timers and the demo pacing are discoverable in one place.
**Both `make` and `demo.sh` read it**, so the knobs behave the same whichever
front door you use. A value in `.env` beats one exported in your shell.

The suite never needs a key: `make test` and `make verify` force
`FIXTURE_MODE=1` and never touch the network. A key is required for exactly two
things — driving the demo against the live model, and re-recording fixtures
with `make fixtures`.

## Setup on macOS or Linux

You have `make`, so use it. Install the [prerequisites](#prerequisites), then:

    make deps
    make demo     # → console :8000, Temporal UI :8233, core banking :8001
    make verify   # the definition of done: green, and nothing skipped

`make demo` starts four host processes (§14 — no Docker), each tracked by a pid
file so the targets are idempotent, and `make down` stops them. If the console
comes up but nothing progresses, run `make status` first: a missing CLI shows
there as `temporal : stopped`, and the reason will be in `.run/temporal.log`.

## Setup on Windows

There is no `make` on Windows and you do not need one. `demo.sh` at the repo
root is the entry point — one bash script, no make, and it runs unmodified on
macOS and Linux too.

**1. Check what you have.** Open Git Bash and run:

    git --version
    bash --version

Git for Windows supplies both, and you need Git to clone this repo anyway. If
`bash` is missing, install [Git for Windows](https://gitforwindows.org/) — not
WSL. The point of `demo.sh` is that a full Linux subsystem is not required.

**2. Install the [prerequisites](#prerequisites)** from that table — winget for
uv and Python, and a manual download for the Temporal CLI, which has no
package. Do the CLI first: it is the only one that needs a `PATH` edit and a
fresh terminal.

**3. Set up `.env`** as described [above](#the-api-key-and-running-without-one).
Keyless is fine, and is the right way to start.

**4. Run it:**

    bash ./demo.sh up

That single command installs dependencies on first use, so there is no separate
setup step. Type `bash ./demo.sh up`, **not** `./demo.sh up` — Git on Windows
does not reliably preserve the executable bit, and a bare `./demo.sh` can fail
with a permission error that has nothing to do with the script.

**5. Run the suite** the same way as anywhere else:

    uv run pytest

**6. Do not install `make`.** winget, Chocolatey and Scoop all give you GNU make
*alone*, whose recipes then run under `cmd.exe` and fail on the first `rm -rf`
— in a way that looks like a bug in this repo rather than a missing shell. Only
MSYS2, Cygwin or WSL supply the POSIX tools Make needs underneath it, and each
is a larger install than the demo itself.

**7. WSL, if you want it anyway.** Everything here — `make` included — works
untouched inside WSL, at the cost of a real Linux install and forwarding
`:8000` and `:8233` out to your Windows browser. Reach for it only if you
specifically want the developer-only targets in the
[Commands](#commands) table.

## Walking the demo

Roughly four minutes. Two browser tabs: the console on `:8000`, the Temporal UI
on `:8233`. Everything below has been walked end to end; the numbers are from a
real run.

**Before you start**, reset first — the ambiguous-timeout beat fires once per
ledger, and a stale ledger makes the toggle look broken:

    make demo                 # macOS / Linux
    bash ./demo.sh demo       # Windows, or anywhere

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

4. **Kill the worker** — `make restart-worker`, or
   `bash ./demo.sh restart-worker`. The console keeps polling; the workflow is
   asleep on a durable timer with nothing running. When the worker returns, the
   case is exactly where it was. *"The process outlived the process running
   it."*

5. **Fill the date, tick the attestation, Approve.** Both are enforced twice —
   the button is disabled client-side, and the update validator refuses the
   same thing server-side, so the gate holds against a curl as well as a click.

6. **"Now watch step 4 — in the Temporal UI."** The console shows
   `submitting_to_core` and nothing more while the call is in flight; the retry
   belongs to the activity's `RetryPolicy`, so the workflow is blocked in one
   call and has nothing to report yet. The Temporal UI does: the pending
   `open_account` shows its attempt number climbing and the last failure
   underneath. Afterwards the history keeps the evidence — that activity's
   started event carries `attempt: 2` and the timeout as its last failure, and
   the console reports `Core attempts: 2`.

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
| **Ambiguous timeout** | On by default; the *Slow first core-banking call* toggle in Demo Controls turns it **off** for a clean pass | The pending activity's attempt count in the Temporal UI, then `Core attempts: 2` and **one** account in the ledger |
| **Worker kill** | `make restart-worker` / `bash ./demo.sh restart-worker`, during either durable wait | The case resumes exactly where it was, instantly |
| **Model outage** | The *Model outage* toggle | `call_llm` fails; the agent loop retries and resumes mid-extraction rather than restarting it |

A fourth, if someone asks *"what if we onboard the same client twice?"*: submit
again without resetting. Core banking answers `duplicate` on the **first**
attempt, which means a previous onboarding owns the account — so the workflow
stops at `already_onboarded`, sends no welcome pack, and notifies the
specialist and supervisor rather than the client.

## Commands

Two front doors, one implementation. **Wherever a row below has both columns
filled, the `make` recipe calls `demo.sh`** — there is one behaviour and two
ways to reach it, so the columns cannot drift apart. **`make help`** prints the
left column and is generated from the targets themselves.

| Make | `demo.sh` | What it does |
|---|---|---|
| `make deps` | *(automatic)* | `uv sync`. `demo.sh up` does this itself on first run |
| `make demo` | `bash ./demo.sh demo` | reset state, start all four processes, print the URLs |
| `make up` | `bash ./demo.sh up` | start them *without* resetting — keeps the ledger, so the ambiguous-timeout beat will not re-fire |
| `make down` | `bash ./demo.sh down` | stop everything it started |
| `make status` | `bash ./demo.sh status` | which of the four processes are up |
| `make logs` | `bash ./demo.sh logs` | tail all four process logs from `.run/` |
| `make demo-reset` | `bash ./demo.sh reset` | clear state so you can Submit again — **no restart needed** |
| `make restart-worker` | `bash ./demo.sh restart-worker` | the worker-kill beat |
| `make test` | `uv run pytest` | the suite, under `FIXTURE_MODE=1`; no key needed |
| `make verify` | — | `test` plus the zero-skipped gate: the definition of done |
| `make documents` | — | regenerate the sample PDFs |
| `make fixtures` | — | re-record `fixtures/` against the live model (needs a key) |
| `make histories` | — | re-capture `histories/`, the replay gate's input |
| `make clean` | — | `down` + `reset` |

The four with no `demo.sh` column are developer-only: they need an API key, a
live stack, or both, and the customer path never calls them.

Two things that are easy to trip on:

- **A bare `make` runs `up`**, not `help` — `.DEFAULT_GOAL := up`, because these
  verbs exist for muscle memory across the sibling demos (§14).
- **`up` does not reset the ledger**, and the idempotency key is derived from
  the client key rather than a UUID (§4.1). So the ambiguous-timeout beat fires
  once per ledger: core banking answers `duplicate` before it reaches its delay,
  and the *Slow first core-banking call* toggle then looks broken. Use `demo`,
  which chains the reset. A second onboarding for a client who already has an
  account terminates as `already_onboarded` and says so (§10.1.1).

`histories/` holds the committed replay gate. Re-capture it with
`FIXTURE_MODE=1 make up && make histories` only when the workflows' command
sequence changes on purpose — `histories/README.md` says what that means.

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
| [`docs/superpowers/plans/2026-09-04-customer-onboarding-demo.md`](docs/superpowers/plans/2026-09-04-customer-onboarding-demo.md) | 26 tasks. How the spec gets built. |
| [`docs/RULINGS.md`](docs/RULINGS.md) | The execution log — every deviation from the plan, with its reasoning. Most of the interesting bugs are in here. |
| [`docs/demo-brief.md`](docs/demo-brief.md) | 11 numbered decisions, with the **rejected** alternatives. |
| [`docs/DEVELOPMENT-PROCESS.md`](docs/DEVELOPMENT-PROCESS.md) | The four-stage process this repo follows. |

`docs/design/` holds the console's visual reference, and `histories/` holds
nine captured workflow histories that `tests/test_replay.py` replays on every
run — the gate that catches an innocuous edit breaking determinism.
