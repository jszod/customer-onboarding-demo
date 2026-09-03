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

## Decisions settled (2026-09-03, brainstorming session 1)

### 1. AI shape — deterministic spine + agent child workflow

The parent workflow is the readable business process (1→7). Step 2 is a
bounded ReAct **child workflow** that extracts fields and fills the
application, escalating to a human when it cannot fill a required field.

Why, over the alternatives:

- It is the shape the meeting notes describe — a linear process with AI named
  at exactly one step.
- It is **new prior art.** `canonical-ai-demo` is already agent-outer /
  deterministic-inner (`TravelAgentWorkflow` spawns a deterministic
  `CheckoutWorkflow`). Financial-services buyers want the inversion: an
  auditable process with AI as a contained step whose blast radius they can
  point at. Inverting the nesting yields a second demo rather than a re-theme.
- The child earns its keep. Extraction over arbitrary documents genuinely
  needs a loop (read doc → extract → notice `tax_id` missing → check the
  second doc → still missing → escalate). That escalation is also what feeds
  step 3's review gate. Plain AI-in-activities would make step 2 a single
  Claude call and throw away the "AI can't finish, human finishes it" moment.

Cost accepted: two workflow types instead of one, and a multi-SDK contract
must cover the child's boundary too.

Likely built on `temporal-agent-harness` — it is an installable Python
package (`uv add` from git) providing durable agent workflows, a tool-approval
policy engine that escalates to a human, and a packaged UI. **Harness vs.
hand-rolled loop is not yet decided.**

### 2. Persona — external accountant submits, bank reviews

Three distinct actors:

| Actor | Role |
|-------|------|
| External accountant | Uploads documents on behalf of their client |
| Bank operations analyst | The human who approves the extracted data (step 3) |
| End client | The account holder; notified at step 7 |

The trust asymmetry between submitter and reviewer is *why* the review gate
exists. Step 7 notifies both the accountant and the end client.

### 3. Real vs. seeded AI — live by default, fixture mode for tests

Extraction calls Claude live against committed sample documents. A
`FIXTURE_MODE` switch swaps in recorded responses; that mode is what the test
suite and no-key/offline runs use.

Reasoning:

- **Live-only was never an option.** Replay tests cannot call a live model, so
  a mock exists either way. "Live only" just means it is undocumented.
- **Fully seeded is more work, not less.** Seeding a *catalog* is easy (a
  flight is a row). Seeding a *conversation* is not — the agent loop is
  stateful, so fixtures would need to be keyed to loop state, a little state
  machine that exists only to imitate a model we could have called. Note that
  `canonical-ai-demo` seeds the **tools**, not the model. Same cut here: seed
  the documents and the fake core banking system, keep the model live.
- **Demo-day API risk is the demo.** Step 2's whole pitch is non-deterministic
  work that must be retried and replayed safely. If Claude 429s on stage, the
  audience watches Temporal back off and resume without losing its place.
  `FIXTURE_MODE=1` is the break-glass for a dead network, not the default.

Two constraints this puts on the build:

- Fixtures are **recorded from real runs**, never hand-written — a
  hand-written fixture drifts from real model output and silently stops
  testing anything.
- The switch lives at the **activity boundary**: one `call_llm` activity with
  two implementations, chosen at worker startup. Not an `if` inside the
  workflow, which would be a determinism hazard and would make the two modes
  non-replay-compatible.

### 4. Failure moment — the ambiguous timeout

**Headline:** core banking accepts the `open_account` request, begins creating
the account, and the call times out before the client ID returns. Nobody knows
whether the account exists. A naive system retries and opens a *second*
account for the same customer — in account opening that is a compliance
incident, not a bug.

Temporal's answer is two-part, and legible in about fifteen seconds:

1. The activity retries with an idempotency key derived from the workflow ID,
   so the core system dedupes and returns the *original* account.
2. The workflow then waits durably for the client ID however long it takes.

**Secondary beats**, both nearly free once the above exists:

- **Worker kill** — free at any point; the stock Temporal moment, kept as a
  reach-for-it beat rather than the headline because it proves durability
  abstractly instead of solving a buyer's problem.
- **SLA breach** — the analyst never reviews; a durable timer fires, reminds,
  then escalates. Free once the human gate exists, and the natural home for
  the time-skipping tests.

**AI escalation is a feature beat, not the crisis.** The agent failing to find
a required field is graceful degradation and belongs in step 2's narration.

## Open questions remaining

5. **External system model** — how does the approved client ID get back into
   the workflow? Submit-side is settled by decision 4 (synchronous call,
   idempotency key, retry policy). The return path is open:
   - *Signal* — core banking POSTs to a gateway endpoint that signals the
     workflow by ID. Most readable, matches what customers build, best picture
     of a workflow sleeping for days at zero cost. SLA timer as fallback.
     **Current recommendation.**
   - *Async activity completion* — `open_account` completes out-of-band via
     task token. More precise for an unreliable callback (one timeout covers
     the whole pending operation, retries if no callback lands), but advanced;
     a reader sees an activity that mysteriously never returns.
   - *Polling* — no callback; infrequent-polling pattern
     (`backoff_coefficient=1`, retries stay out of history). Most realistic
     for legacy cores and fully self-contained with no inbound endpoint, but
     the workflow looks busy rather than idle.

   **This is where session 1 stopped** — user asked to clarify before
   answering.

6. **UI** — is there a web surface (like `canonical-ai-demo`'s `web/`) or is it
   CLI/Temporal-UI driven? Note this interacts with question 5: a signal-based
   return path wants an inbound HTTP endpoint, though `temporal workflow
   signal` covers it CLI-only. It also decides how much the no-API-key setup
   friction from decision 3 actually costs — self-serve repo vs. driven live
   on a call.
7. **SDK scope** — Python-only, or an SDK-agnostic `CONTRACT.md` so Go/Java/TS
   workers can follow?
8. **Agent child implementation** — `temporal-agent-harness` or a hand-rolled
   ReAct loop? Raised by decision 1; not yet asked.

## Design constraints from the Temporal SDK references

Carried forward into the spec; from the `temporal:temporal-developer` skill
references read during session 1.

- **The agent child needs its justification written down.**
  `core/patterns.md` is explicit: *"Do not need to use child workflows simply
  for breaking complex logic down into smaller pieces."* Our reasons hold —
  separate history domain (an agent loop generates many events), failure
  isolation (extraction can fail without failing the onboarding), and a
  distinct retry policy — but the spec must state them or a future reader will
  read the nesting as gratuitous.
- **Document bytes must never flow through workflow history.** 2MB payload
  cap, 4MB gRPC message, aim for <10MB history. The correct pattern is
  activities that accept a *reference*, fetch and process internally, and
  return a reference. No document content in a workflow argument or return.
- **Time-skipping environments cannot be shared between tests.** The suite is
  mostly `WorkflowEnvironment.start_local()` (shareable via a pytest fixture),
  with `start_time_skipping()` reserved for the SLA-timer tests.
- **Disable retries in the LLM client** (`max_retries=0`) and let Temporal own
  all retry behavior.
- **Classify model errors inside the activity** — 401/invalid input/content
  policy as `non_retryable=True`; 429 with `next_retry_delay` parsed from
  headers; 5xx and connection errors retryable. Correct retry behavior then
  falls out of calling the activity.
- **Timeouts** — ~60–120s `start_to_close` for document processing, ~30s for
  simple model calls.
- **Idempotency key sources** — workflow ID, business identifier, or workflow
  ID + activity name + attempt. Decision 4 uses the workflow ID.

## Reference material for design

| What | Path | Why |
|------|------|-----|
| Temporal agent harness | `~/src/demos/temporal-agent-harness` | Inner/outer agentic loop design — may settle open question 1 |
| Python samples | `~/src/python/samples-python` | `message_passing`, `updatable_timer`, `polling`, `replay` |
| Canonical AI demo | `~/src/demos/canonical-ai-demo` | Prior art: durable agent loop + deterministic business workflow, `CONTRACT.md`, multi-SDK layout |

## Status

Stage 1 (Design) — in progress. Questions 1–4 settled; **resume at open
question 5** (external system model), then 6, 7, and 8.

Still ahead in Stage 1 after the questions: 2–3 approaches with trade-offs,
the design presented section by section, then the spec written to
`docs/superpowers/specs/2026-MM-DD-customer-onboarding-design.md`.
