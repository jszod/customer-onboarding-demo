# Customer Onboarding Demo

A Temporal demo: a commercial bank onboards a business client through a
seven-step deterministic workflow containing a bounded AI extraction child
workflow. Headlines the ambiguous-timeout / idempotency failure.

## Current stage — read this first

**Design is complete; no implementation code exists yet.**

| Document | What it is |
|----------|------------|
| `docs/superpowers/specs/2026-09-04-customer-onboarding-design.md` | **The binding authority.** 22 sections. Settles everything. |
| `docs/superpowers/plans/2026-09-04-customer-onboarding-demo.md` | 21 tasks, 127 steps. How the spec gets built. |
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

Nothing below exists until plan Task 1 runs.

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
