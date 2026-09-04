# Customer Onboarding Demo — Design Spec

**Status:** Stage 1 complete, awaiting human approval.
**Date:** 2026-09-04
**Decision history:** [`docs/demo-brief.md`](../../demo-brief.md) — 11 numbered
decisions with the reasoning and the rejected alternatives. This spec is the
binding authority; the brief explains *why*.

This document is self-contained. An implementing agent should not need the
brief to build from it. Where an agent hits a conflict, it consults this spec,
makes a ruling, logs it, and keeps going.

---

## 1. The demo story

A commercial bank onboards a new business client. The process is seven steps,
one of which is AI. Temporal makes three things visible:

1. **A long-running human gate.** KYC review can take days. The workflow sleeps
   durably and survives worker restarts.
2. **An unreliable external system.** The core banking call can time out
   *after* succeeding. Retries plus a stable idempotency key mean exactly one
   account is opened, never two.
3. **AI as a contained, durable tool.** Document extraction is
   non-deterministic work that must be retried, recorded, replayed, and — when
   it cannot finish — handed to a human.

**The headline failure is the ambiguous timeout** (§10.1). Everything else is a
secondary beat.

### Why this is not a re-theme of `canonical-ai-demo`

That demo is **agent-outer / deterministic-inner**: a long-lived ReAct
`TravelAgentWorkflow` spawns a deterministic `CheckoutWorkflow`. This demo is
the **inversion** — an auditable deterministic process that contains a bounded
agent. Financial-services buyers want to point at the non-deterministic part
and see its blast radius. The inversion is the contribution.

## 2. Audience and format

- **Primary:** driven live by a Temporal SE on a customer call, on a laptop.
- **Secondary:** a readable repo someone can clone and run.
- **Not:** a workshop artifact. Runbook choices favour the laptop case (§14).

## 3. Domain and personas

Commercial / business account opening — **not** consumer. Consumer onboarding is
one government ID, which collapses extraction to a single model call with no
plausible gap, and retail review takes minutes rather than days.

| Actor | Role |
|-------|------|
| **Client Onboarding Specialist** | Submits the client's documents; prepares the application (steps 1–2) |
| **KYC/AML Analyst** | The human gate — reviews, edits, approves (step 3) |
| **End client** | The business and its beneficial owners; notified at step 7 |

The Relationship Manager is a real role in commercial banking but is **out of
scope as a named actor** — it would add spec surface without changing a
Temporal primitive.

**Why the gate exists: segregation of duties.** The person who prepares the
application may not be the person who signs off KYC. This is a regulatory
constraint, not a design preference.

**Terminology:** the field is `beneficial_owners`, never "beneficiaries."
A beneficial owner is a natural person owning or controlling ≥25% of a legal
entity. A beneficiary receives assets and is unrelated to account opening.

## 4. Architecture

### 4.1 Identity

| Thing | Value |
|-------|-------|
| Task queue | `customer-onboarding` |
| Parent workflow type | `OnboardingWorkflow` |
| Parent workflow ID | `onboarding-<client-key>` |
| Child workflow type | `ExtractionAgentWorkflow` |
| Child workflow ID | `onboarding-<client-key>-extract-<attempt>` |
| Parent close policy | default (`TERMINATE`) |

**The parent workflow ID is derived from the client key, not a UUID.** Temporal
forbids two open runs sharing an ID, so this buys *one open onboarding per
client* — a real compliance property. Re-running the demo works because the
prior run is closed. Clicking Submit twice surfaces "onboarding already in
progress," which demonstrates the property at zero cost.

### 4.2 Why the extraction agent is a child workflow

`core/patterns.md` warns against child workflows used merely to decompose. Four
reasons apply here:

1. **History isolation** — an agent loop generates many events; the parent's
   history stays a readable seven steps.
2. **Failure isolation** — extraction can fail without failing the onboarding.
3. **Distinct retry policy** — the loop's needs differ from the business
   process's.
4. **Attempt isolation** — when the analyst rejects, the parent starts a *new*
   child with a fresh history rather than resuming a poisoned conversation.
   This is the reason that survives a skeptical reviewer.

### 4.3 No continue-as-new

Parent history is ~7 activities plus a handful of signals and updates. The
child is iteration-capped at `MAX_ITERATIONS`. Neither approaches 10k events.

## 5. Data model

**Rule: every workflow, activity, signal, update, and query takes exactly one
Pydantic model, or nothing — and returns one model, or nothing.** No positional
argument lists anywhere, including single-field payloads.

`core/versioning.md` lists *"changing arguments passed to activities or child
workflows"* as a breaking change. Adding a parameter changes arity and breaks
replay for in-flight runs; adding an optional field to a model does not. This
demo will be edited repeatedly between customer calls, so the rule is not
ceremony.

`pydantic_data_converter` is used on client and worker.

### 5.1 Application data

```python
class Address(BaseModel):
    line1: str; line2: str | None; city: str; state: str; postal_code: str; country: str

class BeneficialOwner(BaseModel):          # all required
    full_name: str | None
    dob: date | None
    ownership_pct: Decimal | None
    residential_address: Address | None
    id_type: Literal["passport", "drivers_license", "state_id"] | None
    id_number: str | None

class ControlPerson(BaseModel):            # all required
    full_name: str | None
    title: str | None
    dob: date | None
    residential_address: Address | None
    id_type: Literal["passport", "drivers_license", "state_id"] | None
    id_number: str | None
    is_authorized_signatory: bool = True   # a flag, not a duplicate block

class ApplicationFields(BaseModel):
    legal_name: str | None                 # required
    dba: str | None                        # optional
    entity_type: Literal["LLC", "C_CORP", "S_CORP", "LP", "LLP"] | None   # required
    formation_date: date | None            # required
    formation_state: str | None            # required
    tax_id: str | None                     # required
    registered_address: Address | None     # required
    business_address: Address | None       # required
    industry_code: str | None              # required
    phone: str | None                      # optional
    website: str | None                    # optional
    beneficial_owners: list[BeneficialOwner] = []      # ≥1 required
    control_person: ControlPerson | None               # required
```

Every field is `| None` because extraction may not fill it. **Required vs.
optional is declared in exactly one place**, `REQUIRED_FIELD_PATHS` — a
module-level tuple of dotted paths (e.g. `beneficial_owners[].dob`). `gaps` is
computed from it, and the `submit_review` validator reads the same tuple, so
the console, the gaps list, and the approve rule can never disagree.

**Exactly three fields are optional:** `dba`, `phone`, `website`. Everything
else in `ApplicationFields`, `BeneficialOwner`, and `ControlPerson` is
required — including every owner's `id_type` and `id_number`, because CIP
requires identification for each beneficial owner.

Grounded in CIP (name, address, TIN, DOB for individuals) and BOI (owners ≥25%
plus a control person).

### 5.2 Documents

```python
class DocumentRef(BaseModel):
    doc_id: str                            # stable slug, e.g. "ein-letter"
    kind: Literal["articles_of_incorporation", "business_license",
                  "ein_letter", "w9", "ownership_declaration"]
    uri: str                               # store-relative path
    sha256: str
    page_count: int

class DocumentManifest(BaseModel):
    refs: list[DocumentRef]
```

Document → field mapping. This is what gives the agent loop something genuine
to do:

| Document | Fields it carries |
|----------|-------------------|
| `articles_of_incorporation` | legal_name, entity_type, formation_date, formation_state, registered_address |
| `business_license` | dba, business_address, industry_code |
| `ein_letter` | tax_id |
| `w9` | tax_id, legal_name *(confirmation)* |
| `ownership_declaration` | beneficial_owners[], control_person |

**`tax_id` appears in two documents.** If the EIN letter is illegible the
correct behaviour is to consult the W-9 — reasoning that arises from the data,
not from a script.

### 5.3 Extraction

```python
class FieldGap(BaseModel):
    field_path: str                        # "beneficial_owners[1].dob"
    reason: str
    documents_searched: list[str]

class ExtractionRequest(BaseModel):
    client_key: str
    legal_name: str
    manifest: DocumentManifest
    attempt: int
    prior_gaps: list[FieldGap] = []
    analyst_note: str | None = None

class ExtractionResult(BaseModel):
    application: ApplicationFields
    gaps: list[FieldGap]
    iterations: int
    escalated: bool
```

### 5.4 Review

```python
class FieldEdit(BaseModel):
    field_path: str
    value: str                             # coerced against the schema on merge
    
class ReviewSubmission(BaseModel):
    decision: Literal["approve", "reject"]
    analyst_id: str
    note: str | None = None
    field_edits: list[FieldEdit] = []
    attested: bool = False

class ReviewAck(BaseModel):
    accepted: bool
    stage: str
```

### 5.5 Core banking

```python
class OpenAccountRequest(BaseModel):
    idempotency_key: str                   # == parent workflow ID
    application: ApplicationFields

class OpenAccountAck(BaseModel):
    request_id: str
    status: Literal["accepted", "duplicate"]

class ClientIdAssignment(BaseModel):
    client_id: str
    core_ref: str
    assigned_at: datetime
```

`OpenAccountAck` deliberately **does not** carry the client ID. That is the
point of the async return path. `status: "duplicate"` is the proof the
idempotency key worked and is what the operator points at on stage.

### 5.6 Status and result

```python
class OnboardingStatus(BaseModel):
    stage: Literal["ingesting", "extracting", "awaiting_review",
                   "submitting_to_core", "awaiting_client_id",
                   "sending_documents", "notifying", "complete",
                   "manual_intervention", "rejected_by_core"]
    attempt: int
    application: ApplicationFields | None
    gaps: list[FieldGap]
    pending_since: datetime | None
    core_attempt: int
    last_error: str | None
    core_request_id: str | None
    client_id: str | None
    extraction_iterations: int

class OnboardingResult(BaseModel):
    status: Literal["completed", "manual_intervention", "rejected_by_core"]
    client_id: str | None
    attempts: int
    detail: str
```

## 6. The wire surface

This table is the content of `CONTRACT.md`. Names are literal strings; a worker
in any SDK matches them exactly.

| Handler | Kind | Argument | Returns |
|---------|------|----------|---------|
| `OnboardingWorkflow` | workflow | `ApplicationRequest` | `OnboardingResult` |
| `ExtractionAgentWorkflow` | workflow | `ExtractionRequest` | `ExtractionResult` |
| `submit_review` | **update** | `ReviewSubmission` | `ReviewAck` |
| `client_id_received` | **signal** | `ClientIdAssignment` | — |
| `status` | **query** | — | `OnboardingStatus` |
| `ingest_documents` | activity | `IngestRequest` | `DocumentManifest` |
| `call_llm` | activity | `LLMRequest` | `LLMResponse` |
| `open_account` | activity | `OpenAccountRequest` | `OpenAccountAck` |
| `send_documents` | activity | `SendDocumentsRequest` | `SendDocumentsResult` |
| `notify` | activity | `NotifyRequest` | `NotifyResult` |

```python
class ApplicationRequest(BaseModel):
    client_key: str
    legal_name: str
```

Refs are produced **inside** the workflow by `ingest_documents`, not passed in.

### 6.1 Gateway HTTP surface

The gateway is the only thing that talks to Temporal. It imports **zero**
worker code — it drives workflows by the string names above.

| Endpoint | Purpose |
|----------|---------|
| `POST /applications` | Body `{client_key}`. Starts `OnboardingWorkflow` with ID `onboarding-<client-key>`. Returns 409 `{error: "already in progress"}` when Temporal rejects the duplicate ID |
| `GET /api/status/{client_key}` | Proxies the `status` query; returns `OnboardingStatus` |
| `POST /api/review/{client_key}` | Body `ReviewSubmission`. Sends the `submit_review` update; returns `ReviewAck`, or 422 with the validator's rejection message |
| `POST /callbacks/client-id` | Body `ClientIdAssignment` plus `client_key`. Called **by the core banking service**; sends the `client_id_received` signal |
| `POST /api/control` | Forwards demo toggles (slow-first-call, forced rejection) to the core banking service, and sets the LLM-outage flag |
| `GET /` | Serves the console |

The 409 on a duplicate start is not an error path to hide — it is the
demonstration of §4.1's workflow-ID property, and the console surfaces it as
*"onboarding already in progress for acme-corp."*

**Each primitive is used where it belongs, and the choice is defensible:**

| Primitive | Used for | Why not the others |
|-----------|----------|--------------------|
| Update | `submit_review` | needs validation *and* a response |
| Signal | `client_id_received` | external system, fire-and-forget, nothing to return |
| Query | `status` | read-only, drives the console, not recorded in history |

## 7. Process flow

Steps 1–3 are a **loop**, not a straight line.

```python
attempt = 1
while attempt <= MAX_ATTEMPTS:
    manifest = await ingest_documents(...)        # re-runs each attempt
    result   = await extraction_child(attempt)
    review   = await self._await_review()         # §9
    if review.decision == "approve":
        break
    attempt += 1
else:
    return OnboardingResult(status="manual_intervention", ...)

application = merge(result.application, review.field_edits)
ack         = await open_account(...)             # §10.1
await self._await_client_id()                     # §9.3
await send_documents(...)
await notify(...)
return OnboardingResult(status="completed", client_id=..., ...)
```

`ingest_documents` re-running per attempt is load-bearing: when the analyst
rejects with *"you're missing the EIN letter,"* the specialist drops the file
into the store and the next attempt picks it up. **Added documents work
through the reject loop, without a signal-based intake path.**

## 8. The extraction agent child

A hand-rolled ReAct loop adapted from
`canonical-ai-demo/python/workflows/agent.py` — its `_think()`, `_dispatch()`
and `_await_confirmation()` methods, minus the conversational surface
(transcript, chat updates, queries), because this child is a bounded batch job,
not a chat. `temporal-agent-harness` was rejected: it is explicitly
experimental with changing APIs, and the single feature we would want (human
escalation) is a `wait_condition` we already have. The child-workflow boundary
in §4.2 *is* the compatibility layer if we later swap it in — a swap changes
one file and touches neither the parent nor `CONTRACT.md`.

### 8.1 The loop

**The child has exactly one activity: `call_llm`.** Every tool is an inline
workflow tool, because every tool mutates only agent state — which
`core/ai-patterns.md` Pattern 3 places in workflow code, not activities.

| Tool | Kind | Effect |
|------|------|--------|
| `request_documents(doc_ids)` | inline | appends to `requested_docs` in workflow state |
| `submit_extraction(application, gaps)` | inline, terminal | ends the loop |
| `escalate(gaps)` | inline, terminal | ends the loop with `escalated=True` |

Loop:

1. `call_llm` is called with the **manifest** (doc ids + kinds) plus the text of
   documents already in `requested_docs`.
2. The model either requests more documents, or submits, or escalates.
3. On a request, the doc ids are appended to workflow state and the loop
   repeats.
4. Terminates on `submit_extraction`, `escalate`, or `MAX_ITERATIONS`.

**This is the design that keeps documents out of history.** Workflow state
holds a list of doc *ids* — a few bytes. The `call_llm` activity resolves those
ids to text from the store on every call. Document content never appears in a
workflow argument, a return value, or a tool result.

Reaching `MAX_ITERATIONS` without a terminal tool is treated as
`escalated=True` with whatever gaps are known. **The child does not raise.**

### 8.2 Rules

- **"The AI couldn't do it" is a successful child returning gaps, not a failed
  child.** Escalation is a return value, never an exception. Getting this
  backwards makes a compliance-normal outcome (a missing DOB) surface as a red
  failed workflow.
- **The conversation stays in the child.** Structured turns are a couple of KB
  each and belong in child history — that is what makes the child's timeline
  readable in the Temporal UI, and it is the `temporal-agent-harness` event
  stream recovered for free.
- **The child returns `ExtractionResult` only.** No messages cross to the
  parent.
- **"Why is this field missing?" is answered by `FieldGap`**, not by the
  transcript. The transcript's audience is the demo operator.
- **Any future activity-backed tool caps its result at 4KB** before it enters
  workflow state, with the full result retrievable from the store.

### 8.3 Model configuration

- Default model `claude-sonnet-5` (`MODEL` env), for stage latency.
  `claude-opus-5` is supported for harder document sets.
- **Client retries disabled** (`max_retries=0`) — Temporal owns all retry
  behaviour.
- Structured output via Pydantic response schemas.
- Sample documents are **text-layer PDFs**; `call_llm` extracts text with
  `pypdf` internally. Vision over page images is a documented upgrade, not the
  default — text extraction is more reliable on stage.
- Prompt caching is an activity-internal concern and therefore invisible to the
  workflow; it cannot affect determinism. Enabling it is an optimisation, not a
  design change.

### 8.4 The deliberate gap

The `acme-corp` document set is complete **except one beneficial owner's
`dob`**. Ownership declarations routinely list names and percentages without
dates of birth, so the gap is realistic rather than contrived. The agent
requests every document, fails to find it, and escalates. The analyst fills it
at the review gate — so the AI's limit and the segregation-of-duties gate land
on the same field.

## 9. Human-in-the-loop surface

### 9.1 The review gate

`submit_review` is an **update**, not a signal, because the analyst can *edit*
field values (correcting data is much of what KYC review is), and edits need
synchronous validation. An update **validator** rejects malformed input before
it enters history; a signal would let bad data land and force the workflow to
cope afterwards.

**Validator rules** (format and internal consistency only — validators must not
block or mutate, so no activities and no I/O):

1. `decision` is `approve` or `reject`.
2. On `approve`: **every required field must be non-empty after applying
   `field_edits`.** This is what forces the analyst to fill the escalated
   `dob`.
3. On `approve`: `attested` must be `true`.
4. `tax_id` matches the EIN shape `\d{2}-\d{7}`.
5. `sum(ownership_pct) <= 100` — **≤, not ==**, because owners below 25% are
   not listed.
6. On `reject`: `note` must be non-empty.

Anything requiring I/O ("does this EIN exist in the registry?") is an activity
*after* the update is accepted.

**Audit rule: never overwrite the AI's output in place.**
`ExtractionResult.application` is what the model produced;
`ReviewSubmission.field_edits` is the human delta; the final application is the
merge. Both are already in history, so the trail is free — and *"here is what
the model said, here is what the human changed, here is who changed it"* is the
compliance story.

### 9.2 SLA policy

The gate races the review against a tiered timer:

| Elapsed | Action |
|---------|--------|
| `SLA_REMIND` | remind the assigned analyst; keep waiting |
| `SLA_ESCALATE` | escalate to a supervisor; keep waiting |
| ever | **never auto-approve** |

**The workflow must never approve a KYC application because a timer fired.**
That is a compliance incident and it is exactly the shortcut a well-meaning
implementer reaches for. The workflow waits indefinitely; only a human closes
this gate. §16 pins this with a test.

The timer restarts per attempt.

**Deliberately cut:** the `updatable_timer` pattern (analyst requests an
extension). The tiered timer already tells the durable-timer story; an
extension signal adds contract surface for a beat we do not need.

### 9.3 The client-ID wait

`client_id_received` is a **signal** — the core banking system POSTs to a
gateway endpoint which signals the workflow by ID. `CLIENT_ID_SLA` is a
fallback timer that reminds and escalates on the same never-give-up basis.

Rejected alternatives: *async activity completion* (more precise, but a reader
of the workflow file sees an activity that mysteriously never returns — bad for
a teaching demo) and *polling* (most realistic for legacy cores, but the
workflow looks busy rather than idle, losing the "asleep for days at zero
cost" point).

## 10. Failure behaviour

### 10.1 The headline: the ambiguous timeout

`open_account` has a deliberately short `start_to_close_timeout` of **5s**. The
fake core banking service, on the **first** call for a given idempotency key,
sleeps **10s and still creates the account**. A second call with the same key
returns immediately with `status="duplicate"` and the original `request_id`.

On stage:

1. Attempt 1 times out — visible in the UI as an activity timeout with a retry
   scheduled.
2. Attempt 2 returns `duplicate` immediately.
3. The core banking ledger holds **one** account.

**The teaching point:** a `start_to_close_timeout` firing does **not** cancel
the server's work. That is the entire source of the ambiguity — the work
happened, the answer was lost. Retry alone creates a second account; retry
*plus a stable key* is the fix.

**The trap, stated so an implementer does not walk into it:** the idempotency
key is the **parent workflow ID**, stable across every retry. Deriving it from
`activity.info().attempt` — the intuitive move, since the SDK exposes it —
defeats the mechanism and produces exactly the duplicate it was meant to
prevent.

Slow-first-call is the **default** behaviour so the beat happens on every run;
a console toggle disables it for a clean pass.

### 10.2 Retry policies

| Activity | `start_to_close` | Retry | Non-retryable |
|----------|------------------|-------|---------------|
| `ingest_documents` | 30s | default | file missing / unreadable |
| `call_llm` | 120s | default; 429 sets `next_retry_delay` from headers | 401, content policy, invalid input |
| `open_account` | **5s** | initial 1s, backoff 2.0, max interval 10s, unlimited attempts | core rejects the application (business 4xx) |
| `send_documents` | 60s | default | — |
| `notify` | 30s | default | — |

`call_llm` at 120s follows the document-processing band in
`core/ai-patterns.md`, not the 30s simple-call band.

**Error classification lives inside the activity**, raising
`ApplicationError(..., non_retryable=True)` — not in `non_retryable_error_types`
at the call site. One source of truth, and correct retry behaviour then falls
out of merely calling the activity.

### 10.3 Failure is not workflow failure

**Every path ends in a business status.** A failed workflow reads as a bug; a
completed workflow with a terminal status reads as a process.

| Condition | Outcome |
|-----------|---------|
| Core rejects the application (non-retryable) | complete with `rejected_by_core` |
| `ChildWorkflowError` | counts as a spent attempt |
| `MAX_ATTEMPTS` exhausted | complete with `manual_intervention`, then `notify` |
| Extraction cannot fill a required field | **not a failure** — `escalated=True`, gaps to the analyst |

Copy canonical's `_failure_message(e: ActivityError | ChildWorkflowError)`
helper for turning caught errors into human text.

### 10.4 Secondary beats

- **Worker kill** — most effective during either durable wait, where resume is
  instant and unambiguous. Mid-activity also works but you wait out the
  timeout first, which is less crisp.
- **LLM outage** — a console toggle that makes `call_llm` fail, so the agent
  loop visibly retries and resumes. Adopted from canonical's LLM API switch.

## 11. The fake core banking system

A separate FastAPI service (§14), because it must be killable independently and
must hold state the workflow cannot see.

| Endpoint | Behaviour |
|----------|-----------|
| `POST /accounts` | Body `OpenAccountRequest`. First call per `idempotency_key`: sleep `CORE_SLOW_MS` (default 10000), create the account, return `accepted`. Subsequent calls with the same key: return `duplicate` with the original `request_id`, immediately |
| `POST /accounts/{request_id}/assign` | Operator-triggered; POSTs `ClientIdAssignment` to the gateway's `/callbacks/client-id`, which sends the signal |
| `GET /ledger` | Returns all accounts — the proof surface for "exactly one" |
| `POST /control` | Toggles `slow_first_call` and forced rejection |

The idempotency ledger is a SQLite file so it survives a service restart;
`make demo-reset` clears it.

## 12. Observability

**Every step is labelled with User Metadata.** This is a requirement, not
polish: the Temporal UI is the primary observability surface (§13 keeps the
console deliberately minimal), and labelling recovers the
`temporal-agent-harness` event stream given up in §8.

| Where | API | Limit |
|-------|-----|-------|
| Workflow start | `static_summary`, `static_details` | 200B / 20KB |
| During execution | `workflow.set_current_details(...)` | — |
| Activity | `execute_activity(..., summary=...)` | 200B |
| Timer | `workflow.sleep(..., summary=...)` | 200B |

- `static_summary`: `"Onboard Acme Holdings LLC — business account"`
- `static_details`: set once at start — client key, document count and kinds,
  the required-field count, and the configured SLA values. It is immutable, so
  it holds what will not change; the tracker goes in current details.
- `set_current_details`: the **progress tracker**, rewritten per stage —
  a markdown list of all seven steps with `✓` for done, `→` for current, `○`
  for pending, plus the current gap. Uses `✓`/`→`/`○` rather than markdown
  task lists, since task-list rendering is not guaranteed.
- Activity summaries: `"Collect 5 documents for Acme Corp"`,
  `"Extract — iteration 3, requesting w9"`,
  `"Submit account request to core banking"`.
- Timer summaries: `"KYC review SLA — 3 days"`.

**Version floor: Temporal UI v2.34.6 or later** — activity summaries on the
Timeline require it.

The console renders the same `stage` value as a horizontal stepper. **One
source, two surfaces, nothing built twice.**

## 13. The operator console

A single page served by the gateway. Three controls, one per actor:

| Control | Actor | Behaviour |
|---------|-------|-----------|
| "Submit application for Acme Corp" | Onboarding Specialist | `POST /applications` with the client key |
| Review & approve form | KYC Analyst | `submit_review` update |
| "Return client ID" | Core banking | triggers `POST /accounts/{id}/assign` |

Plus a demo-controls area: slow-first-call toggle, LLM-outage toggle.

**Layout:** a horizontal seven-step stepper at the top (from `stage`), and
below it a **gap-first review panel** — "1 field needs you" with the
`FieldGap` reason and `documents_searched`, an input for the value, an
attestation checkbox, and Approve / Reject. The extracted fields that *are*
filled collapse to one line ("28 fields extracted & verified") and expand into
an application-grouped table (Business / Beneficial owners / Control person).

Rationale: gap-first puts human attention where it is needed and foregrounds
the escalation beat; the expanded application-grouped view is what an analyst
actually recognises. Both render from the same `status` payload, so this is a
rendering choice, not a contract change. A document-centric view (fields
grouped by source document) was rejected — its provenance value is already
carried by `FieldGap.documents_searched`, without building a document viewer.

`submitting_to_core` is a **visible stage** showing `core_attempt` and
`last_error`, so the headline retry is legible without switching to the
Temporal UI.

**Refresh:** poll the `status` query every 2s. Queries are not recorded in
history, so this is free. The `workflow_streams` contrib module is the
documented upgrade path if token-level streaming is ever wanted; it is
over-machinery for coarse state.

**Visual design is Stage 3 work**, via the `frontend-design` skill. This spec
fixes the functional surface only.

## 14. Runbook

**Host processes, no Docker.** Four processes driven by a Makefile:

| Process | Command | Port |
|---------|---------|------|
| Temporal dev server | `temporal server start-dev --ui-port 8233` | 7233 / UI 8233 |
| Worker | `uv run python -m worker` | — |
| Gateway + console | `uv run uvicorn web.gateway:app --port 8000` | 8000 |
| Fake core banking | `uv run uvicorn core_banking.app:app --port 8001` | 8001 |

Pattern from `canonical-ai-demo/make/common.mk`: `pgrep` guards so targets are
idempotent, `nohup` with logs under `/tmp`, `pkill -f` on `down`, and `up`
printing the URLs.

**Why no Docker.** Canonical's compose file exists solely for Postgres, and
this demo has no Postgres — Temporal is the state store, documents are a
directory, and the core banking ledger is SQLite. Copying the sibling pattern
faithfully leaves nothing to containerise. Docker's real payoff is letting a
stranger run the repo with only Docker installed, which is not the primary use
case (§2), and `uv.lock` already pins the environment.

**Targets:**

| Target | Purpose |
|--------|---------|
| `up` / `down` / `status` / `logs` | canonical's verbs, for muscle memory across demos |
| `demo` | reset state, start everything, print the URLs |
| `worker` / `kill-worker` / `restart-worker` | the worker-kill beat. **Not** a bare `kill` — ambiguity mid-demo is bad |
| `test` | the verification gate (§16) |
| `demo-reset` | clear the ledger, outbox, and working document store |
| `client-id` | fire the callback from the CLI, as a fallback if the console button misbehaves on stage |
| `fixtures` | re-record extraction fixtures from a live run |
| `histories` | capture workflow histories for replay tests |
| `clean` | `down` keeps state; `clean` removes it |

**What would flip this to Docker:** turning the repo into a self-serve customer
artifact, or a workshop where fifteen laptops' Python installs cannot be
debugged. If that happens, follow canonical's precedent — Dockerfiles under
`docker/` for deployment, kept out of the local dev path.

## 15. Repository layout

Mirrors `canonical-ai-demo`'s split so a second SDK can be added without
moving anything.

```
CLAUDE.md                  run/test commands, task queue, IDs, determinism rule
CONTRACT.md                the §6 wire surface, SDK-agnostic
Makefile                   forwards to python/
make/common.mk             shared process management
documents/acme-corp/       committed sample PDFs (text-layer)
fixtures/                  recorded call_llm responses
histories/                 committed workflow histories for replay tests
python/
  worker.py
  config.py                env, data converter construction
  models/                  every Pydantic model in §5
  workflows/onboarding.py  the parent — no I/O, no clocks, no randomness
  workflows/extraction.py  the agent child
  activities/              ingest, llm, core_banking, delivery
  prompts.py
web/
  gateway.py               SDK-agnostic; drives workflows by string name
  static/                  the console
core_banking/app.py        the fake external system
tests/
outbox/                    generated welcome packs (gitignored)
```

`web/` and `core_banking/` import **zero** worker code — they drive Temporal by
string name, which is what makes `CONTRACT.md` real rather than aspirational.

## 16. Verification gate

`make test` **must run with `FIXTURE_MODE=1` and no API key**, so it works in CI
and for anyone cloning cold. `make test-live` is a separate opt-in that
exercises the live model path.

### 16.1 Activity unit tests (`ActivityEnvironment`)

- `ingest_documents` — copies files, returns refs; missing file raises
  non-retryable
- `call_llm` error classification — 401 → non-retryable, 429 → sets
  `next_retry_delay`, 5xx → retryable. Tested with an injected fake client,
  never by calling the API
- `open_account` — two calls with the same idempotency key: the second returns
  `duplicate`. **This is the headline's correctness test**

### 16.2 Workflow tests (`WorkflowEnvironment.start_local()`, shared fixture)

- Happy path, with a stub child returning a canned `ExtractionResult`
- Reject → attempt increments and `ingest_documents` re-runs
- `MAX_ATTEMPTS` exhausted → `manual_intervention`
- Approve with a required field empty → **validator rejects the update**
- Approve without `attested` → validator rejects
- `sum(ownership_pct) > 100` → validator rejects
- Timeout-then-duplicate → workflow proceeds and the ledger holds exactly one
  account
- Core rejects → `rejected_by_core`
- `ChildWorkflowError` → counted as a spent attempt

### 16.3 Time-skipping tests (`start_time_skipping()`)

Not shared between tests — the reference is explicit that these environments
cannot be reused.

- Remind fires at `SLA_REMIND`, escalate at `SLA_ESCALATE`, workflow still
  waiting
- **Advance far past both and assert the stage is still `awaiting_review`** —
  this is the test that enforces §9.2's never-auto-approve rule. The rule is
  worthless without it
- `CLIENT_ID_SLA` fallback fires and does not abandon the workflow

### 16.4 Child workflow tests (fixture mode)

- EIN letter illegible → the loop requests the W-9 and finds `tax_id`. **If
  this regresses, the demo's most interesting moment dies silently**
- `dob` absent everywhere → `escalated=True` with `documents_searched`
  populated
- `MAX_ITERATIONS` reached → `escalated=True`, no exception

### 16.5 Replay tests (`Replayer`)

The highest-value gate. Committed histories under `histories/` for: happy path,
reject loop, timeout-retry, escalation. Generated by `make histories` via
`temporal workflow show --output json`, regenerated deliberately and committed.

This catches the failure mode an autonomous agent causes most often — an
innocent-looking edit to workflow code that breaks determinism.

### 16.6 Determinism guardrails

The Python SDK's workflow sandbox catches most illegal I/O at runtime. A
grep-based CI check covers the rest: no `requests`, `httpx`,
`datetime.now()`, `time.time()`, or `random` under `python/workflows/`. Use
`workflow.now()` and `workflow.uuid4()` instead.

### 16.7 Fixture bootstrap order

Fixtures are **recorded from real runs, never hand-written** — a hand-written
fixture drifts from real model output and silently stops testing anything.
Record once with an API key (`make fixtures`), commit them, and from then on
nobody needs a key to run the suite.

**Stage 2 consequence: task 1 is this harness, not a feature.** Everything
downstream gates on it.

## 17. Configuration

| Variable | Default | Demo profile |
|----------|---------|--------------|
| `TEMPORAL_ADDRESS` | `localhost:7233` | — |
| `TASK_QUEUE` | `customer-onboarding` | — |
| `MODEL` | `claude-sonnet-5` | — |
| `ANTHROPIC_API_KEY` | — | required unless `FIXTURE_MODE=1` |
| `FIXTURE_MODE` | `0` | `1` in tests and offline runs |
| `MAX_ATTEMPTS` | `3` | — |
| `MAX_ITERATIONS` | `8` | — |
| `SLA_REMIND` | `3d` | `30s` |
| `SLA_ESCALATE` | `7d` | `60s` |
| `CLIENT_ID_SLA` | `1d` | `45s` |
| `CORE_SLOW_MS` | `10000` | — |
| `DOCUMENT_STORE` | `./.store` | — |
| `CORE_BANKING_URL` | `http://localhost:8001` | — |
| `GATEWAY_URL` | `http://localhost:8000` | — |
| `OUTBOX_DIR` | `./outbox` | — |
| `PAYLOAD_CODEC` | `off` | — |

`CORE_BANKING_URL` is read by the worker (the `open_account` activity);
`GATEWAY_URL` is read by the core banking service so it knows where to POST the
client-ID callback.

**The data converter is constructed in exactly one place**, `config.build_data_converter()`,
selected by `PAYLOAD_CODEC`. This is the seam described in §18.

## 18. Non-goals and stated scope cuts

Each of these will be asked about. The spec states the cut and where it would
attach, because *"yes, here is how, we cut it deliberately"* is a far better
answer than silence.

| Cut | Why | Where it would attach |
|-----|-----|----------------------|
| **Document trickle** — workflow starts at application creation, then waits for documents to arrive by signal over weeks, chasing the client | Adds a second long-running wait and a second timer story; §1 commits to one headline failure | A signal loop before step 2, with its own SLA. Partially covered already: the reject loop re-ingests, so added documents work |
| **`PayloadCodec` encryption** | Would turn the Temporal UI into ciphertext, destroying the primary observability surface (§12). The sharpest form of the question is already answered: documents never enter Temporal at all, only refs | `config.build_data_converter()` plus a codec server and `--codec-endpoint` on the UI and CLI. **The strongest candidate for the next increment** — encryption at rest is table stakes in a bank's evaluation |
| **Multi-SDK workers** | 4× the build for no additional teaching value; only one worker can poll the queue at a time | `CONTRACT.md` is written now precisely so Go/Java/TS workers can be added by parallel agents later |
| **`updatable_timer`** | The tiered timer already tells the durable-timer story | §9.2, as an extension signal |
| **Real drag-and-drop upload** | Needs multipart and a file picker for no teaching gain | `POST /applications` already exists; only the front end changes |
| **Vision over document images** | Text-layer extraction is more reliable on stage | Inside `call_llm` (§8.3) |
| **`workflow_streams`** | Console needs coarse state, not tokens | §13 refresh |
| **Relationship Manager as an actor** | No Temporal primitive changes | §3 |
| **A second sample client** | One is enough to tell the story | `documents/<client-key>/` |

## 19. Rulings an implementing agent may need

Ranked by likelihood of being hit:

1. **If a required field's dotted path is ambiguous for list members**, use
   `beneficial_owners[].dob` in `REQUIRED_FIELD_PATHS` and expand per index
   when computing gaps.
2. **If the model returns a field the schema does not have**, drop it and record
   a `FieldGap`-shaped note in the child's history. Do not extend the schema at
   runtime.
3. **If `field_edits` targets an optional field**, accept it — the validator
   only *requires* the required set.
4. **If the analyst rejects on the final attempt**, complete with
   `manual_intervention`; do not start a fourth child.
5. **If `client_id_received` arrives twice**, the second is ignored — first
   assignment wins, and the duplicate is logged.
6. **If `client_id_received` arrives before `open_account` completes**, buffer
   it in workflow state and consume it when the wait is reached. Signals can
   arrive at any time.
7. **If the store is missing a document listed in the manifest**, that is a
   non-retryable `ingest_documents` failure → the attempt is spent.

## 20. Open items

None. Every question raised in Stage 1 is settled above or explicitly cut in
§18. If an implementing agent finds a genuine gap, the ruling procedure is:
consult this spec, decide, log the ruling, keep going.
