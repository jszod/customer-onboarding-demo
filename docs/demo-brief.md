# Demo Brief — Customer Onboarding / Account Opening

Seed material for the spec. Not the spec itself — see
[DEVELOPMENT-PROCESS.md](DEVELOPMENT-PROCESS.md) for how this becomes one.

## Raw meeting notes (2026-09-03)

```
Account opening is probably the accountant
Get docs
People review
Open account (external system)
Receive Get approved client id (from external system)
Send docs
Send notification to customer

Agent usage ideas
Extract information from doc
Fill out forms - create structured data
```

## Working read of the flow

```
1. Collect documents          → customer/accountant uploads
2. Extract + structure        → AI: pull fields out of docs, fill the application
3. Human review               → a person approves the extracted data
4. Open account               → call to external core banking system
5. Receive approved client ID → external system responds (possibly slowly)
6. Send documents             → deliver welcome pack / signed forms
7. Notify customer            → email/SMS confirmation
```

## Why this is a good Temporal demo

Three stories in one flow:

- **Long-running human gate** — step 3 can take days; the workflow sleeps
  durably and survives worker restarts
- **Unreliable external system** — steps 4–5 are a call out to a core banking
  system plus an async callback; retries, timeouts, and idempotency all matter
- **AI as a durable tool** — step 2 is non-deterministic work that must be
  retried, cached in history, and replayed safely

## Open questions for the spec

1. **AI shape** — is the agent driving the process, or a tool the process
   calls? Three candidates:
   - *Deterministic spine + agent sub-workflow*: readable business process
     (1→7) with a bounded ReAct child workflow for extraction/form-filling
     that escalates to a human when it can't fill required fields
   - *Deterministic workflow, AI inside activities*: extraction and
     form-filling are plain activities that happen to call Claude
   - *Agent drives end to end*: ReAct loop owns the process, human approval
     gates the risky tools
2. **The "accountant" line** — read as: the persona is an accountant opening
   an account on a client's behalf, not the end customer self-serving. Changes
   who reviews and who gets notified. **Needs confirmation.**
3. **Real vs. seeded AI** — does extraction call Claude live (needs an API
   key, demo-safe?) or run against seeded fixtures like canonical-ai-demo's
   flight/hotel catalog?
4. **The failure moment** — every good demo has one. What breaks on stage, and
   what does Temporal visibly do about it?
5. **External system model** — synchronous call, async callback, or polling
   for the client ID?
6. **UI** — is there a web surface (like canonical-ai-demo's `web/`) or is it
   CLI/Temporal-UI driven?
7. **SDK scope** — Python-only, or an SDK-agnostic `CONTRACT.md` so Go/Java/TS
   workers can follow?

## Reference material for design

| What | Path | Why |
|------|------|-----|
| Temporal agent harness | `~/src/demos/temporal-agent-harness` | Inner/outer agentic loop design — may settle open question 1 |
| Python samples | `~/src/python/samples-python` | `message_passing`, `updatable_timer`, `polling`, `replay` |
| Canonical AI demo | `~/src/demos/canonical-ai-demo` | Prior art: durable agent loop + deterministic business workflow, `CONTRACT.md`, multi-SDK layout |

## Status

Stage 1 (Design) — in progress, blocked on open question 1.
