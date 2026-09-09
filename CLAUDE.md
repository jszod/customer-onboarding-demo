# Customer Onboarding Demo

A Temporal demo: a commercial bank onboards a business client through a
seven-step deterministic workflow containing a bounded AI extraction child
workflow. Headlines the ambiguous-timeout / idempotency failure.

## Current stage — read this first

**Plan Tasks 1–20 have landed. Task 21 is next — the last one.** Skeleton and
config, models and `CONTRACT.md`, the 22-scenario manifest, the design
artifact, sample documents, core banking, the gateway, the console, all four
activities, the extraction child, the parent's loop and happy path, the
recorded fixtures, and the committed histories with their replay gate.

Suite: **207 passed, 0 skipped — `make verify` says `VERIFY OK: 22/22`.** The
manifest is complete, so the progress bar is spent: from here a skip is a
regression, not remaining work.

**Two pieces of work remain, and only one of them is in the plan.**

1. **Task 21** — final verification and growing the README. The plan's last
   task; it consumes everything and produces nothing new.
2. **The console's visual design** — **§13.1 is now written**; the code has not
   caught up. The spec fixes a six-size type scale, three font weights, a 4px
   spacing unit, sibling-convention token names, one breakpoint at 900px, a
   scrolling stepper, and `:focus-visible` on everything. `web/static/index.html`
   still carries the thirteen sizes and eight weights it accumulated across
   Tasks 8, 11 and 18. **This is not yet a plan task** — spec → plan → code, so
   it needs a task written before it is built.

Constraints any visual pass inherits: `tests/test_console.py` pins 20
behaviours, including light/dark adaptation and **no external scripts or
stylesheets** — no CDN fonts, no Tailwind. And those tests grep the page as
text, so they pass against a page whose JavaScript throws; drive it in a real
browser before believing it (`.claude/rules/testing.md`, R-022).

**Changing the design means changing the spec first.** R-029 is the worked
example: the root `Makefile` shape moved spec → plan → code, in that order,
because a ruling cannot overrule the binding authority. §13.1 followed the
same order — the spec was amended before any CSS moved.

**Task 20 was the first task to run the live stack, and it found three
things.** `make up` had never started anything (R-025 — the guard matched its
own recipe), fixture mode died on the second model call of every real run
(R-026), and four defects in the plan's own Task 20 code (R-027). Read those
three before touching `make/`, `fixture_call_llm`, or the capture tool.

**Where the work lives.** Branch `claude/next-work-item-imsbdj`, pushed, six
commits ahead of `main`, no PR opened. Working tree clean. Local prerequisites
are the README's Setup: the Temporal CLI (`make demo` and `make histories`
shell out to it), `uv`, and **no API key** — the fixtures are committed, so
`make verify` runs on a fresh clone as-is.

**`make/` changed shape after Task 20.** The root `Makefile` is now
`include make/common.mk` rather than a rule forwarding nineteen target names to
`python/`; every target is defined once, in `common.mk`, and `python/Makefile`
is the same include from one directory down. The spec was amended first (§14,
§15) — see R-029, and `.claude/rules/stack-and-make.md` for why not to
reintroduce forwarding.

**The replay gate is now the sharpest thing in the suite.** `histories/` holds
nine captured histories and `tests/test_replay.py` replays every one. A red
replay test is a claim about the *code* — re-capturing to make it green is how
the gate stops guarding. Both gates have been watched failing: the grep guard
on an inserted `random()`, and the replayer on an extra timer it cannot see.

`fixtures/acme-corp.json` is recorded and committed, so the suite is keyless.
Two iterations: `request_documents`, then `submit_extraction` reporting
`beneficial_owners[1].dob` — §8.4's deliberate gap, which is the escalation
beat. Re-record (`make fixtures`, needs a key in `.env`) only if the prompt,
`ApplicationFields`, or the document set changes.

**Read R-024 before touching the agent loop or `prompts.TOOLS`.** The first
live run failed twice on defects that were merged and green: the transcript
ended on an assistant turn (a permanent 400 — prefill is gone on every 4.6+
model), and the terminal tools declared `{"type": "object"}` for their
payloads, which retries forever rather than failing. Both rules are now
promoted into `.claude/rules/`.

**The suite needs a Temporal server** (`WorkflowEnvironment.start_local`). The
SDK downloads its own server binaries from `temporal.download` at runtime — the
only download host compiled into the Rust bridge — so that host must be
reachable, or the work must run somewhere it already is. The Temporal CLI is a
separate prerequisite for `make demo` and `make histories`; see the README's
Setup section. Same host, so a container that can run the suite can be given
the CLI too.

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

## Prior art — check it before inventing anything

This repo is one of five sibling demos, and the spec borrows from them at named
points rather than starting clean. **Read the relevant one before designing a
subsystem from scratch.** All of these are on disk; add one to a session with
`/add-dir`. `.claude/settings.local.json` already grants `Read()` on
`canonical-ai-demo`.

| Repo | Path | What to take from it |
|------|------|----------------------|
| **Canonical AI demo** | `~/src/demos/canonical-ai-demo` | The closest relative. `python/workflows/agent.py` seeds our agent child's `_think()`/`_dispatch()` shape (spec §8); `make/common.mk` seeds the `pgrep` guards (§14); its `python/` split seeds our layout (§15); its `TALK_TRACK.md` is the precedent for §21. Its `web/index.html` is 377 lines and the only sibling console of comparable ambition. |
| **Temporal agent harness** | `~/src/demos/temporal-agent-harness` | Inner/outer agentic loop design. `ui/src/app.css` is 71 lines and the **best-organised token set of any sibling** — numbered ramps (`--surface-0..3`, `--text-1..3`), semantic state colours, and a `--focus-ring` token ours lacks. |
| **Order management demo** | `~/src/demos/temporal-order-management-demo` | Multi-SDK layout. Its `ui/static/style.css` is *not* worth following — `font-family: sans-serif`, no tokens. |
| **Money transfer demo** | `~/src/demos/money-transfer-demo` | Multi-SDK repo shape. No console. |
| **SDK samples** | `~/src/python/samples-python` (also `../go/samples-go`, `../typescript/samples-typescript`, `../java/samples-java`) | `message_passing` (signals/queries/updates), `updatable_timer` (durable SLA timers), `polling`, `schedules`, `replay` (the determinism gate). |

Longer versions of this table live in `docs/demo-brief.md` (§"Reference
material for design") and `docs/DEVELOPMENT-PROCESS.md` (§"Reference
material") — they were there from Stage 1, but not here, so sessions kept
rediscovering them.

**Borrow the pattern, not the declaration.** Our console carries
`font-feature-settings: "cv05", "ss01"`, copied from `canonical-ai-demo`, whose
stack leads with `Inter` where those character variants exist. Ours leads with
`ui-sans-serif`, so they do nothing. When you lift CSS, lift what it depends on
or drop it.

**Where we deliberately diverge, §1 says so.** `canonical-ai-demo` is
agent-outer / deterministic-inner; this demo is the inversion. That is the
contribution, not an accident — check §1 and §18 before "aligning" anything
back.

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
