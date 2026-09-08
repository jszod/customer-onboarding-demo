# Customer Onboarding Demo

A Temporal demo: a commercial bank onboards a business client through a
seven-step deterministic workflow containing a bounded AI extraction child
workflow. Headlines the ambiguous-timeout / idempotency failure.

## Current stage — read this first

**Plan Tasks 1–18 have landed. Task 19 is next.** Skeleton and config, models
and `CONTRACT.md`, the 22-scenario manifest, the design artifact, sample
documents, core banking, the gateway, the console, all four activities, the
extraction child, and the parent's loop and happy path.

Suite: **190 passed, 9 skipped.** Four skips are the T-REPLAY scenarios (Task
20); five are `tests/test_fixtures.py`, skipped until the fixtures are
recorded. That count is the progress bar, and `make verify` is correctly red
until it reaches zero.

**BLOCKED: Task 19 needs `ANTHROPIC_API_KEY`.** `tools/record_fixtures.py` is
written and its guards are verified, but the recording itself has not happened —
it runs the extraction loop live against the real documents (§16.7). Supply the
key with `cp .env.example .env` and fill in the first line (R-020), then run
`make fixtures`, review the recorded JSON in the diff, and commit it.
The suite is keyless from then on. **Task 20 cannot start until this is done**:
`make histories` replays through the fixtures.

**Tasks 19–20 need a Temporal server** (`WorkflowEnvironment.start_local`). The
SDK downloads its own server binaries from `temporal.download` at runtime — the
only download host compiled into the Rust bridge — so that host must be
reachable, or the work must run somewhere it already is. The Temporal CLI is a
separate prerequisite for `make demo`; see the README's Setup section.

| Document | What it is |
|----------|------------|
| `docs/superpowers/specs/2026-09-04-customer-onboarding-design.md` | **The binding authority.** 22 sections. Settles everything. |
| `docs/superpowers/plans/2026-09-04-customer-onboarding-demo.md` | 21 tasks, 127 steps. How the spec gets built. |
| `docs/RULINGS.md` | **The execution log.** Every deviation from the plan, with its reasoning. Its header carries the rule of two — when a ruling gets promoted into `.claude/rules/`. R-014's deferred console work landed in Task 18 as R-022; no open questions remain. **R-021–R-023 were renumbered from R-017–R-019 when the Task 18 branch merged `main`** — two branches wrote those three numbers in parallel, and the commit messages still use the old ones. |
| `docs/demo-brief.md` | 11 numbered decisions with the reasoning and the **rejected** alternatives. |
| `docs/DEVELOPMENT-PROCESS.md` | The four-stage process this repo follows. |

**Do not write implementation code without reading the spec.** When something
in the plan conflicts with the spec, the spec wins. When neither answers,
make a ruling, log it, and keep going — see §19 of the spec, which pre-answers
the seven ambiguities most likely to come up.

## Rules

Directory-scoped rules live in `.claude/rules/` and load when you open files
they cover. The ones that bind everywhere:

- **The spec's §18 lists nine deliberate scope cuts.** Before adding a
  capability that feels missing, check whether it was cut on purpose. Adding
  one back is a decision, not an oversight fix.
- **Never auto-approve the KYC gate on a timeout.** A workflow that approves a
  bank application because a timer fired is a compliance incident. Timers
  remind and escalate; only a human closes that gate.
- **Every failure path ends in a business status**, never a failed workflow.
  A failed workflow reads as a bug; a completed one with a terminal status
  reads as a process.

## Commands

    make deps          # uv sync
    make demo          # reset state, start everything, print URLs
    make up / down / status / logs
    make test          # FIXTURE_MODE=1 — no API key needed
    make verify        # test + assert zero skipped — the definition of done
    make restart-worker
    make demo-reset    # clear ledger, outbox, document store

## Identity

- Task queue: `customer-onboarding`
- Parent: `OnboardingWorkflow`, id `onboarding-<client-key>`
- Child: `ExtractionAgentWorkflow`, id `onboarding-<client-key>-extract-<attempt>`

The parent's workflow ID is derived from the client key, not a UUID — Temporal
then forbids two open onboardings for one client, which is a real compliance
property rather than tidiness.

## The determinism rule

No I/O, no clocks, no randomness in `python/workflows/`. No `requests`,
`httpx`, `datetime.now()`, `time.time()`, or `random`. Use `workflow.now()`
and `workflow.uuid4()`. Everything non-deterministic goes in an activity.
`tests/test_determinism_guard.py` (§16.6) enforces this once Task 3 lands.

Document content never enters workflow history — workflows carry `DocumentRef`s
and doc ids; activities resolve them to text internally (§8.1, §8.2).

The data converter is built in exactly one place, `config.build_data_converter()`
(§17). Worker, gateway, core-banking callback and tests all use it; a mismatch
produces deserialization errors that look like corruption rather than config.

## Layout

- `python/workflows/` — the seven-step parent and the agent child
- `python/activities/` — ingest, llm, core_banking, delivery
- `python/models/` — every Pydantic payload
- `web/` — gateway + console; imports **zero** worker code
- `core_banking/` — the fake external system; never imports `temporalio`
- `tests/` — the 22-scenario manifest (spec §16.8)
- `documents/`, `fixtures/`, `histories/` — committed demo inputs and gates

## Running work autonomously

The plan's **Global Constraints** section is the authoritative rule list for
implementers. Copy it verbatim into every task dispatch — do not assume a
subagent inherits this file.
