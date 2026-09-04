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
1. Collect documents          → onboarding specialist uploads
2. Extract + structure        → AI: pull fields out of docs, fill the application
3. Human review               → KYC analyst approves the extracted data
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

### 2. Persona — bank-internal: Onboarding Specialist submits, KYC Analyst approves

> **Revised 2026-09-04.** Session 1 read the raw note "Account opening is
> probably the accountant" as an *external* accountant acting for a client.
> Research into how business account opening actually works says that is a
> mis-transcription — most likely "the account manager" or "the onboarding
> specialist". Either way the persona is **bank-internal.** See
> [Persona research](#persona-research-2026-09-04) below.

Three distinct actors:

| Actor | Role |
|-------|------|
| Client Onboarding Specialist | Uploads the client's documents, prepares and validates the application (steps 1–2) |
| KYC/AML Analyst | The human gate — reviews the extracted data and approves (step 3) |
| End client | The business and its beneficial owners; notified at step 7 |

The Relationship Manager is a real fourth role — client-facing, chases
documents — but is deliberately **out of scope as a named actor.** Adding them
costs spec surface without changing a single Temporal primitive.

**Why the review gate exists: segregation of duties.** The person who prepares
the application is not permitted to be the person who signs off KYC. That is a
regulatory constraint the audience already lives with, not a design choice
that needs defending. (Session 1 justified the gate by trust asymmetry between
an outside accountant and the bank — a much softer argument.)

**Knock-on effect — the document set gets better.** Retail onboarding gives
thin extraction material (passport plus utility bill). Business account
opening gives articles of incorporation, business license, EIN letter, W-9, and
beneficial-ownership declarations. Genuinely multi-document: a field like
`tax_id`, or a 25%-owner's date of birth, plausibly lives in a different file
than expected, or is missing entirely. This is what makes the decision-1 agent
loop and the escalation beat credible rather than staged.

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

## Decisions settled (2026-09-04, brainstorming session 2)

### 5. Client ID return path — signal

Submit side was already settled by decision 4: synchronous call, idempotency
key derived from the workflow ID, retry policy. The return path is a
**signal** — core banking POSTs to a gateway endpoint that signals the
workflow by ID. The SLA timer is the fallback if the callback never arrives.

Chosen over:

- *Async activity completion* — more precise (one timeout covers the whole
  pending operation, retries if no callback lands), but a reader of the
  workflow file sees an activity that mysteriously never returns. Bad for a
  teaching demo.
- *Polling* — most realistic for legacy cores and needs no inbound endpoint,
  but the workflow looks busy rather than idle, which loses the "asleep for
  days at zero cost" point.

### 6. UI — single-page operator console

Decision 5 already forces a gateway with an inbound endpoint, so the question
was how many pages, not whether to have a web surface. **One page, three
controls, one per actor:**

| Control | Actor | What it does |
|---------|-------|--------------|
| "Submit application for Acme Corp" | Onboarding Specialist | POSTs the client key; gateway loads sample docs and starts the workflow |
| Review & approve form | KYC Analyst | Shows extracted fields, signals approval |
| "Return client ID" | Core banking | Fires the decision-5 callback signal |

**Document intake:** `POST /applications {client: "acme-corp"}` — the gateway
reads the baked-in `documents/acme-corp/` directory, writes to a document
store, mints refs, and starts the workflow **with refs only** (never bytes —
2MB payload cap). No multipart, no file picker, no upload widget. Real
drag-and-drop is future work and needs no backend change.

Store: a local directory behind a docker volume suffices; MinIO if it should
look like S3.

**Worker-kill stays CLI** — killing a process is more convincing at a terminal
than behind a button. Temporal UI carries the durability narrative.

### 7. SDK scope — Python only, `CONTRACT.md` written alongside

Build the Python worker only. No Go/Java/TS workers now. But write the
SDK-agnostic contract — task queue, workflow IDs, signal/update/query names,
payload shapes — from the start, because:

- Those names must be decided in the spec regardless; one table costs nothing.
- Retrofitting later means reverse-engineering names already baked into code,
  which is how the sibling demos ended up doing it.

### 8. Agent child — hand-rolled, adapted from canonical-ai-demo

A hand-rolled ReAct loop, not `temporal-agent-harness`.

**What canonical gives us.** `canonical-ai-demo/python/workflows/agent.py` has
the pieces already: `_think()` wrapping `call_llm` in an activity,
`_dispatch()` routing tool calls, `_run_plain_tool()`, and
`_await_confirmation()` (its own comment: *"survives a worker restart and
costs nothing while waiting"*). Plus `activities/llm.py`, 120 lines, with
error classification done. We take those and **drop** its conversational
surface — transcript, chat updates, queries — because our child is a bounded
batch job, not a chat. Our loop ends up smaller than its 447 lines.

**What we give up.** The harness's standardized event stream (live-watch and
replay-what-the-agent-did observability) and its policy engine's sophistication
— layered rules, per-tool allow-lists, "approve and stop asking." We need
*one* approval gate: a `workflow.wait_condition`, about ten lines. Code Mode,
callback tools, multi-agent composition, typed agent interfaces, and the
Gemini / OpenAI-Agents / Pydantic-AI integrations are all off this demo's
path. The genuine loss is the observability stream — partially recovered by
decision 9.

**Swapping to the harness later is cheap, but not because we designed for it.**
The harness is invasive where it touches (`@agent.defn`, `AgentWorkflowRunner`,
`@agent.activity_tool_defn`) — you rewrite the file rather than adapt into it.
That is fine, because **the child-workflow boundary from decision 1 already is
the compatibility layer**: the parent starts a child with a typed input and
gets a typed result, so a swap changes one file and touches neither the parent
nor `CONTRACT.md`. Designing to the harness's experimental API would buy
nothing the boundary does not already provide.

Also weighed: the harness is explicitly experimental with changing APIs — a
recurring maintenance tax on a demo that gets re-run on calls.

### 9. Label every step with User Metadata

Temporal's **User Metadata** feature, applied throughout. Temporal's own blog
post [Label your agent steps](https://temporal.io/blog/label-your-agent-steps)
describes exactly our problem: an agent loop produces N indistinguishable
`call_llm` activities.

| Where | API | Limit |
|-------|-----|-------|
| Workflow start | `static_summary=`, `static_details=` | 200 bytes / 20KB |
| During execution | `workflow.set_current_details(...)` | — |
| Activity | `execute_activity(..., summary=...)` | 200 bytes |
| Timer | `workflow.sleep(..., summary=...)` | 200 bytes |

Markdown, excluding images/HTML/scripts.

Applied here:

- Parent: `static_summary="Onboard Acme Corp — business account"`, and
  `set_current_details()` updated per stage so the two long waits read as
  *"Awaiting KYC review"* and *"Awaiting client ID from core banking"* rather
  than as an idle workflow.
- Activities: `summary="Extract fields from articles of incorporation"`,
  `summary="Submit account request to core banking"`.
- Timer: `workflow.sleep(..., summary="KYC review SLA — 7 days")`.
- Agent child: each iteration labelled with its step and gap —
  *"Extract — attempt 2, tax_id missing"*.

**This is a spec requirement, not polish.** Decision 6 made the Temporal UI
the primary observability surface, and this partially recovers the harness
event stream given up in decision 8.

**Version floor:** activity summaries on the Timeline require **Temporal UI
v2.34.6 or later** — the spec must pin a minimum server/UI version.

Sources: [Enriching the UI — Python](https://docs.temporal.io/develop/python/platform/enriching-ui),
[Label your agent steps](https://temporal.io/blog/label-your-agent-steps)

## Persona research (2026-09-04)

Quick web research to settle whether "the accountant" in the raw notes was a
typo. It was.

**The standard cast in commercial / business account opening:**

| Role | What they do |
|------|--------------|
| Relationship Manager | Owns the client relationship, guides them through onboarding, handles compliance queries, chases documents |
| Client Onboarding Specialist / Onboarding Manager | Operational owner — collects information, prepares and validates documentation, keys the application into internal systems, coordinates across teams |
| KYC/AML Analyst | Processes new client and account-opening forms, runs due-diligence searches, performs reviews by risk tier |
| Treasury Management Officer, Implementation Coordinator, Portfolio Manager | Larger banks only; specialist partners the onboarding specialist pulls in |

**Why the external-accountant reading was rejected.** It is not fictional —
accountants do act as agents for small-business clients — but federal
Beneficial Ownership Information (BOI) rules require the bank to identify and
verify the individuals who own or control the business, and those people
generally must verify themselves. So an external accountant cannot be the sole
submitter. That drags a legal wrinkle into the demo that has nothing to do
with what the demo is teaching.

Sources:
[Velvet Jobs — KYC/account opening job descriptions](https://www.velvetjobs.com/job-descriptions/account-opening),
[Fifth Third — Client On-Boarding Specialist](https://jobgether.com/offer/69fd66fff77bd301986731b8-client-on-boarding-specialist),
[nCino — commercial onboarding](https://www.ncino.com/blog/how-leading-banks-are-turning-commercial-onboarding-into-their-next-revenue-driver),
[Bank of America — onboarding requirements](https://business.bofa.com/content/dam/boamlimages/documents/articles/B2_025/BofA_Onboarding_Requirements.pdf),
[Grasshopper — opening a business bank account](https://www.grasshopper.bank/who-we-are/blog/a-comprehensive-guide-to-opening-a-business-bank-account/),
[SVB — understanding KYC compliance](https://www.svb.com/startup-insights/startup-strategy/understanding-kyc-compliance/)

## Open questions remaining

None. All design questions are settled — decisions 1–4 in session 1,
decisions 5–9 in session 2.

Next step is not another question, it is the rest of Stage 1: approaches with
trade-offs where any remain, the design presented section by section, then the
spec written to `docs/superpowers/specs/`.

Details deferred to the spec (mechanics, not open design questions):

- Which sample client(s) ship in `documents/` and the exact field schema the
  extraction targets
- Document store choice — local directory behind a docker volume vs. MinIO
- SLA timer duration and what escalation actually does
- Minimum Temporal server / UI version to pin (≥ UI v2.34.6 for activity
  summaries on the Timeline — see decision 9)

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

Stage 1 (Design) — questions complete. Decisions 1–4 from session 1
(2026-09-03), 5–9 from session 2 (2026-09-04); decision 2 revised in session 2.

**Resume at:** the sectioned design walkthrough, then write the spec to
`docs/superpowers/specs/2026-MM-DD-customer-onboarding-design.md`. Hard gate
still stands — no code until that spec is approved.
