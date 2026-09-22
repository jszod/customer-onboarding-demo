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
- **Third — the fallback audience:** the customer, **in the event this demo is
  never built.** If the call falls back to a generic canned AI demo, the design
  itself is still worth walking a customer through. That reader has no runbook
  and no code — only diagrams and reasoning. §21 specifies that deliverable.
- **Fourth — the customer who runs it, on Windows.** Added after the build: the
  repo is handed to a customer who clones it and drives it himself, on a machine
  with no `make`, no POSIX shell guaranteed, and no one beside him to debug it.
  He is not the fallback audience above — that reader only reads. This one
  executes, and every assumption the runbook makes is his problem. §14.1 is his
  entry point.
- **Not:** a workshop artifact. Runbook choices favour the laptop case (§14).

**The fourth audience is why §14 has two front doors.** It arrived late, and
late arrival is the point: §14's original targets were written for one laptop
belonging to the person who wrote them, and every POSIX assumption in them was
free. Handing the repo to someone else made twelve of those assumptions visible
at once.

**The third audience has a scheduling consequence, stated here because it is
counter-intuitive:** the customer-shareable artifact must be built **early**,
not as final polish. Its entire purpose is to survive the demo not being
completed, so producing it last guarantees it is absent in precisely the
scenario it exists for. See §20.2, track E.

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

### 4.3 No continue-as-new, and why this is not an entity workflow

**The distinction is whether the workflow terminates.** An entity workflow's
lifetime is the lifetime of a *thing* — a subscription, a cart, a customer
relationship. It has no natural end, receives events indefinitely, and
accumulates history forever, so it needs continue-as-new to reset.

`OnboardingWorkflow`'s lifetime is the lifetime of a *process instance*. It
starts on submission, runs seven steps, and completes with `OnboardingResult`.
One application, one run, then done.

The days-long waits make it *feel* like an entity workflow, but waiting is not
accumulating: a workflow blocked on `wait_condition` for a week adds **zero**
events while it waits.

**The event budget.** Activities produce ~3 events each.

| Per attempt | Events |
|-------------|--------|
| `ingest_documents` | ~3 |
| child workflow start + completion | ~4 |
| SLA timers (started + fired/cancelled) | ~4 |
| `submit_review` update | ~3 |
| **subtotal** | **~14** |

Three attempts worst case ≈ 42, plus the tail (`open_account`,
`send_documents`, `notify`, the client-ID signal, workflow start/complete) ≈
15. **Under 100 events**, against a 10,000-event concern threshold — two orders
of magnitude of headroom.

**Two facts make that hold, and both matter:**

1. **Activity retries are free.** `core/patterns.md`, in the polling section:
   *"Individual Activity retries are not recorded in Workflow History."* So
   `open_account` retrying twenty times against a dead core banking service
   costs no history growth. This is why the headline failure (§10.1) cannot
   threaten the bound.
2. **Inline workflow tools produce no events.** §8.1's tools are function calls
   mutating workflow state — not activities, not commands, nothing in history.
   The child's history is only its `call_llm` activities: 8 iterations × ~3
   events ≈ 24.

**`MAX_ATTEMPTS` and `MAX_ITERATIONS` are therefore load-bearing in two ways** —
business rules *and* the history bound. They are not arbitrary limits. Removing
either invalidates this section, and continue-as-new would then need
reconsidering.

**For contrast, what an entity workflow would be here:** a
`ClientRelationshipWorkflow` living for the life of the customer, handling
periodic KYC refresh (banks re-review clients every 1–3 years), address
changes, adverse-media hits, and beneficial-ownership updates. Unbounded events
over years — that one genuinely needs continue-as-new, and it would start an
`OnboardingWorkflow` as a child on day one. A plausible follow-up demo, and the
clean illustration of the difference.

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

class IngestRequest(BaseModel):
    client_key: str
    attempt: int                           # working dir is per-attempt
```

`ingest_documents` copies from `documents/<client_key>/` into
`<DOCUMENT_STORE>/<client_key>/<attempt>/`, hashes each file, and returns the
manifest. A per-attempt working directory is what lets a rejected attempt pick
up newly added documents without disturbing the previous attempt's refs — which
remain valid for replay.

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

### 5.3.1 The model call

```python
class AgentTurn(BaseModel):                # one structured turn, ~1-2KB
    role: Literal["assistant", "tool"]
    content: str

class LLMRequest(BaseModel):
    model: str
    manifest: DocumentManifest             # ids + kinds only
    requested_doc_ids: list[str]           # activity resolves these to text
    turns: list[AgentTurn]
    required_field_paths: list[str]
    prior_gaps: list[FieldGap] = []
    analyst_note: str | None = None

class DocumentRequest(BaseModel):
    kind: Literal["request_documents"] = "request_documents"
    doc_ids: list[str]
    rationale: str

class ExtractionSubmission(BaseModel):
    kind: Literal["submit_extraction"] = "submit_extraction"
    application: ApplicationFields
    gaps: list[FieldGap]

class Escalation(BaseModel):
    kind: Literal["escalate"] = "escalate"
    gaps: list[FieldGap]

class LLMResponse(BaseModel):
    action: DocumentRequest | ExtractionSubmission | Escalation   # discriminated on `kind`
    turn: AgentTurn
    usage: dict[str, int]                  # logged for cost tracking
```

`LLMRequest` carries **document ids, never document text.** The activity
resolves `requested_doc_ids` against the store on every call. `LLMResponse` is
already coerced and validated by the activity (§8.3), so the workflow
dispatches on `action.kind` and stores the result — it never parses.

`usage` is logged at activity level per `core/ai-patterns.md`'s cost-tracking
guidance.

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
    attempt: int = 1        # activity.info().attempt — which try answered (§10.1.1)

class ClientIdAssignment(BaseModel):
    client_id: str
    core_ref: str
    assigned_at: datetime
```

### 5.5.1 Delivery

```python
class SendDocumentsRequest(BaseModel):
    client_key: str
    client_id: str
    legal_name: str
    application: ApplicationFields         # final, post-merge

class SendDocumentsResult(BaseModel):
    packet_uri: str                        # written under OUTBOX_DIR
    page_count: int

class NotifyRequest(BaseModel):
    client_key: str
    client_id: str | None
    outcome: Literal["completed", "manual_intervention", "rejected_by_core"]
    recipients: list[Literal["onboarding_specialist", "end_client", "supervisor"]]
    packet_uri: str | None = None
    detail: str

class NotifyResult(BaseModel):
    delivered_to: list[str]
```

`send_documents` writes a welcome-pack file under `OUTBOX_DIR` and returns its
path — a **reference, not content**, consistent with §8.2. `notify` appends to
a notification log the console renders; it does not send real email or SMS.

`notify` is also the activity used for the SLA reminder and escalation in §9.2,
with `recipients` set accordingly — one activity, three callers, rather than
three near-identical activities.

Both are idempotent by construction: `send_documents` writes to a
deterministic path derived from `client_key` and `client_id`, so a retry
overwrites rather than duplicating, and `notify` appends a record keyed by
`(client_key, outcome, recipients)`.

`OpenAccountAck` deliberately **does not** carry the client ID. That is the
point of the async return path. `status: "duplicate"` is the proof the
idempotency key worked and is what the operator points at on stage.

### 5.6 Status and result

```python
class OnboardingStatus(BaseModel):
    stage: Literal["ingesting", "extracting", "awaiting_review",
                   "submitting_to_core", "awaiting_client_id",
                   "sending_documents", "notifying", "complete",
                   "manual_intervention", "rejected_by_core",
                   "already_onboarded"]
    attempt: int
    application: ApplicationFields | None
    gaps: list[FieldGap]
    pending_since: datetime | None
    core_attempt: int
    last_error: str | None
    core_request_id: str | None
    client_id: str | None
    extraction_iterations: int
    core_duplicate: bool = False      # core banking answered "duplicate"
    core_preexisting: bool = False    # ...on attempt 1 (§10.1.1)

class OnboardingResult(BaseModel):
    status: Literal["completed", "manual_intervention", "rejected_by_core",
                    "already_onboarded"]
    client_id: str | None
    attempts: int
    detail: str
```

`core_duplicate` and `core_preexisting` are **query-only**: queries are never
recorded in history (§13), so they are free against the §16.5 replay gate.
`already_onboarded` widens two `Literal`s, which is also replay-safe — the
`"completed"` already in the committed histories stays a valid member. See
§10.1.1 for why the two duplicate cases must not be conflated.

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
workflow tool.

| Tool | Kind | Effect | I/O? |
|------|------|--------|------|
| `request_documents(doc_ids)` | inline | appends ids to `requested_docs` in workflow state | **none** |
| `submit_extraction(application, gaps)` | inline, terminal | stores the result, ends the loop | **none** |
| `escalate(gaps)` | inline, terminal | sets `escalated=True`, ends the loop | **none** |

**No tool performs I/O. Nothing here reads the disk.** This is the first thing
a reviewer will challenge — "shouldn't anything that can fail be an activity?"
— so the answer is stated rather than left to inference.

`core/ai-patterns.md` draws exactly this line:

- **Pattern 2** — *"Tools which are non-deterministic and/or heavy actions
  (file system, hitting APIs, etc.) should be placed in activities."*
- **Pattern 3** — *"tools which mutate agent state and are deterministic (like
  TODO tools, just updating a hash map) typically belong in the workflow code
  rather than an activity."*

All three tools above are Pattern 3 — hash-map updates against workflow state.
The file system is touched only by `call_llm`, which is Pattern 2: an activity
with a 120s timeout and a retry policy, so a failed or slow document read
retries rather than breaking the loop.

Validation of `doc_ids` against the manifest is likewise a pure check — the
manifest is already in workflow state. An unknown id returns an error to the
model as a tool result; it is not an exception.

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
- **`call_llm` returns validated models. The workflow never parses raw model
  output.** Coercing the model's structure into `ApplicationFields` — dates,
  decimals, enums — happens inside the activity, so:
  - the workflow only ever stores structures already known-good;
  - malformed model output is a **retryable activity failure**, which is the
    correct handling, rather than an exception raised in workflow code;
  - no parsing logic sits on the determinism-critical path, where a
    locale- or clock-dependent parse would be a latent replay bug.

  `LLMResponse` therefore carries a discriminated union — a document request, a
  completed extraction, or an escalation — each already typed. The workflow
  dispatches on it and does nothing else.
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

**The retry is §10.2's activity `RetryPolicy`, and nothing else.** No
workflow-level loop. An earlier build moved the retry into a `while True` in
the workflow so the console could show the attempt count live; that was
abandoned as more confusing than the visibility was worth — an implementer read
§10.2, found `maximum_attempts=1` at the call site, and reasonably concluded
retry had been disabled. See R-037, which supersedes R-015.

The consequence is deliberate and worth stating: **the retry is watched in the
Temporal UI, not in the console.** A pending activity's attempt number and last
failure are something the platform already shows, natively, without being
asked — which for a Temporal demo is the better place for them anyway. The
console reports how many attempts it *took*, after the fact, from
`OpenAccountAck.attempt`.

**The beat fires once per ledger.** The idempotency key is the workflow ID,
which §4.1 derives from the client key rather than a UUID — so it is the *same
key on every run*. Core banking answers `duplicate` before it reaches the
delay, which is correct (a fast duplicate is the proof the key worked) but
means the slow call cannot fire a second time for the same client until the
ledger is cleared. `make demo` chains `demo-reset`; `make up` alone does not.
§14 says so in the runbook, because the toggle otherwise looks broken.

### 10.1.1 `duplicate` means two different things

`status: "duplicate"` is returned in two situations that the workflow can
distinguish and must not conflate.

| `ack.attempt` | What happened | What it means |
|--------------|---------------|---------------|
| **≥ 2** | Our own earlier call created the account; the answer was lost | §10.1's beat, working. Proceed. |
| **1** | A **previous onboarding** for this client already owns the account | Nothing in this run created anything |

**The attempt number comes back on the ack**, from `activity.info().attempt`
inside the activity. With the retry owned by the activity's `RetryPolicy` the
workflow cannot count attempts itself — it sees one call and one result — so
the activity reports which attempt answered.

This is **not** §10.1's trap. That trap is deriving the *idempotency key* from
`activity.info().attempt`, which breaks the key's stability and produces the
duplicate account the design exists to prevent. Reading the same value to
*report* which attempt succeeded changes no behaviour and is the only way the
two duplicate cases can be told apart once the loop is gone.

The second case is reachable in business terms, not just as a demo artifact: a
workflow ID of `onboarding-<client-key>` stops two *open* onboardings for one
client, but nothing stops a second one after the first completes.

**Attempting the call is still correct in both cases.** There is no pre-check
and there should not be one — asking idempotently *is* the safe way to find
out whether an account exists, and a pre-check would introduce the
read-then-write race the idempotency key exists to remove.

**A first-attempt duplicate terminates the workflow as `already_onboarded`.**
The client-ID wait (step 5) and the welcome pack (step 6) are skipped: sending
a pack and telling a client about an account they have held for months is wrong
however it is displayed. It is **not** a workflow failure (§10.3) — it is a
terminal business status.

Step 7 still runs, and that is the point rather than an exception. `_finish`
notifies on every terminal status, and for anything other than `completed` the
recipients are the **onboarding specialist and supervisor, never the end
client** (§5.5.1). So the outcome is exactly what a bank wants from a repeat
onboarding attempt on an existing client: nothing sent to the customer, and a
record in front of the two people who need to see it.

`OnboardingStatus` carries `core_duplicate` and `core_preexisting` so the
console can state which of the two happened. Both are query-only fields:
queries are never recorded in history (§13), so they cost nothing against the
§16.5 replay gate. Adding `already_onboarded` to the two `Literal`s is
likewise replay-safe — widening a union does not invalidate the `"completed"`
already recorded in the committed histories.

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

`submitting_to_core` is a **visible stage**, and once the call resolves the
console reports `core_attempt` — how many tries it took, read off
`OpenAccountAck.attempt`.

**It does not show the retry while the retry is in flight, and that is a
deliberate trade.** The retry belongs to the activity's `RetryPolicy` (§10.2),
and an in-flight activity retry cannot be surfaced into a workflow query by any
means — the workflow is blocked in one `execute_activity` call and knows
nothing until it returns. An earlier build did drive the retry from a workflow
loop to get exactly this, and the confusion it caused at the call site
outweighed the gain (R-037, superseding R-015).

**So the retry is narrated in the Temporal UI**, which shows a pending
activity's attempt number and last failure without being asked. For a Temporal
demo that is the stronger move: the platform is doing the work, so the platform
is where you watch it happen. §14's runbook has the two tabs open regardless.

**Refresh:** poll the `status` query every 2s. Queries are not recorded in
history, so this is free. The `workflow_streams` contrib module is the
documented upgrade path if token-level streaming is ever wanted; it is
over-machinery for coarse state.

§13 fixes the **functional** surface. §13.1 fixes the **visual** system.

### 13.1 Visual system

Written after Tasks 8, 11 and 18 had each added CSS in passing. The palette
those tasks produced is deliberate and is **ratified here rather than
replaced**; what was missing was a written system, so every new callsite
invented its own size and spacing. This section exists to stop that drift.

**Principles**, derived from §2's primary audience — an SE driving the page
live on a laptop in a customer call:

1. **Scanned, not read.** State must be legible from across a meeting room.
2. **Colour *and* shape, always.** Every state is carried by at least two
   channels — a fill plus a border, a tint plus a glyph. A bad projector
   flattens hue, and roughly 1 in 12 men cannot separate our `--done` green
   from our `--alert` red. Colour alone is never the signal.
3. **The page is a document, not an app shell.** It scrolls. No fixed
   full-height panes, no internal scroll regions except where §13.1's
   responsive rules require one.

#### 13.1.1 Tokens

Naming follows `temporal-agent-harness/ui/src/app.css` — numbered surface and
text ramps rather than ad-hoc names. **Values are ours and unchanged, with the
two exceptions §13.1.5 forces** — both marked in the table.

| Token | Light | Dark | Use |
|-------|-------|------|-----|
| `--surface-0` | `#f4f2ee` | `#0e1014` | Page ground |
| `--surface-1` | `#ffffff` | `#171a20` | Panels, cards |
| `--surface-2` | `#faf9f6` | `#1d212a` | Recessed rows, inputs, chips |
| `--text-1` | `#14161b` | `#eef0f4` | Primary text |
| `--text-2` | `#5d6472` | `#99a1b2` | Secondary text, labels, meta |
| `--border` | `#e3e0d8` | `#272c36` | Default hairline |
| `--border-strong` | `#cfcbc0` | `#38404e` | Control outlines, chips |
| `--accent` / `--accent-ink` / `--accent-wash` | `#2a4b9b` / `#ffffff` / `#eaeffb` | `#7fa3ff` / `#0e1014` / `#1b2436` | In-progress, primary action, focus |
| `--done` / `--done-ink` / `--done-wash` | `#16755a` / `#ffffff` / `#e6f3ee` | `#4ac79b` / `#0e1014` / `#142b25` | Completed step, verified field |
| `--wait` / `--wait-wash` | **`#985c09`** / `#fbf1e0` | `#e8ad4a` / `#2c2415` | Durable wait — the **normal** state |
| `--alert` / `--alert-ink` / `--alert-wash` | `#ab2020` / `#ffffff` / `#fbebe9` | `#ff7b72` / `#0e1014` / `#2e1a1a` | Gap, failure, terminal rejection |
| `--focus-ring` | `--accent` @ 40% | `--accent` @ 45% | `:focus-visible` outline |
| `--control-bg` / `--control-hover` | `#ffffff` / `#f4f2ee` | `#0f1318` / `#18202a` | Button and input fills — `.btn`, `input.cell-edit` |

**Every strong fill carries an ink token.** `--accent-ink` already existed;
`--done-ink` and `--alert-ink` are new, and they are not cosmetic. The
stylesheet Tasks 8/11/18 produced sets `color: #fff` literally on `.btn.go`
(over `--done`) and on `.stepper li.is-failed .step-n` (over `--alert`). Those
two hardcodes are fine in light and **fail badly in dark** — white on `#4ac79b`
is 2.11:1 and white on `#ff7b72` is 2.52:1, against §13.1.5's 4.5:1 floor. With
the ink tokens they read 9.01:1 and 7.55:1. `--wait` needs no ink token: it is
never used as a fill, only as text on `--wait-wash`.

**`--wait` is the one value that changed.** `#a1620a` on `--wait-wash` measures
4.40:1 — under the floor, on the pill that carries the *normal* state and that
the demo sits on for the whole KYC beat. `#985c09` is the smallest darkening
that clears it: 4.85:1 on `--wait-wash`, 5.43:1 on `--surface-1`, 4.85:1 on
`--surface-0`. Hue and chroma are unchanged; nothing else in the palette moves.

**`--surface-2` versus `--control-bg`.** Both look like "input background", and
the split is deliberate: `--surface-2` is a *recess* in a panel (the gap input,
the chip, `.review-actions`), `--control-bg` is a *raised control* (`.btn`,
`input.cell-edit`). They are the same value in light and deliberately different
in dark, where a raised control sits darker than the panel behind it.

Both themes are **opaque**. `temporal-agent-harness` builds borders from
`rgba(255,255,255,.08)`, which is correct over a fixed dark ground and
invisible on paper; a dual-theme page cannot use that trick. This is the one
place the inherited structure had to be re-derived rather than copied.

**Two text levels, not three.** The sibling convention has `--text-1..3`. This
page has exactly two roles — primary and secondary — and every current use of
the old `--muted` is the same role. A third level is added when a third role
appears, not before.

**`--done` / `--wait` / `--alert`, not `--success` / `--warning` / `--error`.**
A deliberate departure from the sibling names, because the semantics differ: a
durable wait at the KYC gate is the *expected* path (§9.1), often for days.
Naming it `warning` would tell the viewer something is wrong at the exact
moment the demo is claiming the opposite.

#### 13.1.2 Type scale

Six sizes. The thirteen `font-size` declarations Tasks 8–18 produced (11, 11.5,
12, 12.5, 13, 13.5, 14, 14.5, 15, 15.5, 17, 19, 21px) collapse as follows — the
half-pixel steps were never distinguishable at projector distance.

| Token | Size | Replaces | Use |
|-------|------|----------|-----|
| `--fs-eyebrow` | 11px | 11, 11.5, 12 | Uppercase labels, chips, footnote |
| `--fs-meta` | 13px | 12.5, 13 | Secondary text, sub-labels, `.tui-link` |
| `--fs-ui` | 14px | 13.5, 14 | Table text, step labels, messages |
| `--fs-body` | 15px | 14.5, 15, 15.5 | Controls, buttons, body copy, inputs |
| `--fs-title` | 17px | 17 | Panel headings, `.fact-v` |
| `--fs-display` | 21px | 19, 21 | Client name, current-stage title |

**A fourteenth size hides in a shorthand.** `body` declares
`font: 16px/1.5 …`, which no `font-size:` census sees, so the document base is
16px and not on the scale. It becomes `--fs-body` (15px). Anything without an
explicit size therefore shrinks by 1px — in practice the `.action .txt` copy
and any unstyled text node; every heading and label is explicitly sized and is
unaffected. This is a real rendering change, listed with the other two in Task
22's Step 1, and it is why the type-scale test must also reject a size hidden
in a `font:` shorthand rather than only auditing `font-size:`.

**Weights: 500, 600, 700.** Replacing eight (500, 520, 560, 600, 620, 640,
680, 700). The `ui-sans-serif` stack resolves to a non-variable system face on
most machines, so `520` and `560` render identically to `500` — five of the
eight distinctions existed only in the stylesheet. 500 is body, 600 is headings
and labels, 700 is eyebrows and tabular numerals.

**Delete `font-feature-settings: "cv05", "ss01"`.** Copied from
`canonical-ai-demo`, whose stack leads with `Inter`, where those character
variants exist. Ours leads with `ui-sans-serif`; the declaration is inert.
Either lift the font too or drop the declaration — this spec drops it, because
self-hosting a webfont to gain two character variants fails the cost test, and
§13's no-external-stylesheets rule forbids a CDN.

#### 13.1.3 Spacing and radius

**4px base unit**, tokens `--sp-1` (4px) through `--sp-8` (32px). The sixteen
ad-hoc padding/margin/gap values — 2, 3, 5, 6, 7, 9, 10, 11, 13, 14, 15, 17,
18, 22, 26 and 34px — all round into it: nearest multiple of 4, rounding **up**
on an exact tie. `--radius` stays 10px for panels; `--radius-sm` is 8px for
controls, chips and steps.

`width`, `height`, `inset` and `top` are component dimensions, not spacing, and
stay off the grid — the 34px brand mark, the 21px step numeral and the 17px
checkboxes are sizes.

#### 13.1.4 Layout and responsive rules

Regions, top to bottom: `.topbar` (brand, client, stage pill, Temporal UI
link), the seven-step `.stepper`, the current-stage `.detail` panel, the
`.review` panel when the gate is open, then `.cols` — actions beside demo
controls — and a footnote. Content is capped at **1180px** and centred.

**One breakpoint: 900px.** Replacing the current 900px/860px disagreement,
which had no reason behind it. Below 900px, `.cols` collapses to one column.

**The stepper scrolls; it does not wrap.** Below 900px it becomes
`repeat(7, minmax(96px, 1fr))` inside an `overflow-x: auto` track. The current
rule collapses seven columns to four, which leaves an orphan row of three and
destroys the one thing the stepper exists to communicate — position within a
seven-step whole (§12). A horizontal scroll preserves the metaphor at the cost
of a gesture; wrapping preserves the gesture at the cost of the meaning.

#### 13.1.5 Accessibility

- **`:focus-visible` on every interactive element** using `--focus-ring` —
  buttons, links, checkboxes, text inputs and the editable table cells.
  Currently only `.gap input[type=text]` has any focus treatment, which makes
  the review gate unusable by keyboard.
- **4.5:1 minimum text contrast** in both themes — including text on the
  `-wash` fills *and* on the strong `--done` / `--alert` / `--accent` fills.
  Three pairs failed when this section was first written, all three because the
  values were ratified from the stylesheet without being measured: `--wait` on
  `--wait-wash` at 4.40:1, and the two literal `#fff` fills at 2.11:1 and
  2.52:1 in dark. §13.1.1 fixes all three. **A colour is not ratified until it
  has been measured** — the audit belongs in Task 22's browser drive, not in a
  grep test, because only the browser knows what actually sits behind an
  element.
- **`prefers-reduced-motion: reduce`** disables all animation, not only the
  stage pill's pulse. Already correct for `.pill::before`; the rule generalises.
- **`color-scheme`** stays declared on `:root` in both themes so form controls
  and scrollbars follow.

#### 13.1.6 Why light-first, when the siblings are dark-only

`canonical-ai-demo` and `temporal-agent-harness` are both dark-only. This
console is light-first with a dark theme, for two reasons: `test_console.py`
pins light/dark adaptation as a behaviour, and §2's audience is a laptop
screen in a lit meeting room, where a light page survives glare and a
projector's raised black floor better than a dark one.

Recorded here so the divergence reads as a decision. Aligning the three demos
on one visual language is a legitimate future call — it is a change to this
section, not a bug to be fixed in CSS.

#### 13.1.7 Out of scope

No webfonts, no icon set, no CSS framework, no build step — §13's tests forbid
external scripts and stylesheets, and the page stays a single self-contained
`web/static/index.html`. A component library, a theme toggle (the OS setting is
honoured instead), and animated stage transitions are all rejected: none of
them changes what the demo demonstrates.

## 14. Runbook

**Host processes, no Docker.** Four processes driven by a Makefile:

| Process | Command | Port |
|---------|---------|------|
| Temporal dev server | `temporal server start-dev --ui-port 8233` | 7233 / UI 8233 |
| Worker | the venv interpreter directly: `python -m python.worker` | — |
| Gateway + console | the venv interpreter directly: `python -m uvicorn web.gateway:app --port 8000` | 8000 |
| Fake core banking | the venv interpreter directly: `python -m uvicorn core_banking.app:app --port 8001` | 8001 |

Never `uv run <cmd>` — §14.1 explains why: it forks a child that binds the
port, so the pid `demo.sh` records is not the process holding it.

Pattern borrowed from `canonical-ai-demo/make/common.mk`: idempotent start
targets, background processes with logs under a temp directory, and `up`
printing the URLs.

**Two halves of that pattern were dropped, and §14.1 says why.** Canonical
guards with `pgrep` and stops with `pkill -f`, and this repo copied both. The
guard cost it R-001 and R-025 — a recipe containing both the pattern and the
command it guards matches its own shell, and `make up` printed the URLs having
started nothing for eight tasks. The pattern is also the one thing Git Bash
cannot supply, which made it the blocker for §2's fourth audience. PID files
replace both. Idempotence and the log directory survive; the mechanism does
not.

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
| `restart-worker` | the worker-kill beat — stop, then start the worker back up, proving the workflow survives it. **Not** a bare `kill` — ambiguity mid-demo is bad |
| `test` | run the suite — the verification gate (§16) |
| `verify` | `test` plus `skipped == 0`; the machine-checkable definition of done (§16.8) |
| `demo-reset` | clear the ledger, outbox, and working document store |
| `client-id` | fire the callback from the CLI, as a fallback if the console button misbehaves on stage. **Never built** — found by the §14.1 sweep. The gateway endpoint exists (`POST /api/assign/{client_key}`); no target ever called it. Worth more to §2's fourth audience than to the SE who can open a browser, so it is a candidate for `demo.sh` rather than for `make` |
| `fixtures` | re-record extraction fixtures from a live run |
| `histories` | capture workflow histories for replay tests |
| `clean` | `down` keeps state; `clean` removes it |

**What would flip this to Docker:** turning the repo into a self-serve customer
artifact, or a workshop where fifteen laptops' Python installs cannot be
debugged. If that happens, follow canonical's precedent — Dockerfiles under
`docker/` for deployment, kept out of the local dev path.

**That trigger has since fired, and the answer is still no.** The repo is now
handed to a customer who runs it himself (§2's fourth audience) — which is
exactly the first clause above. Docker was reconsidered on those terms and
declined, and §18 carries the re-argued cut. The short version: the reason §18
originally gave for the cut is void, but three others survive, and one
container to run one dev server and three Python processes is a heavier ask of
a Windows user than the two installs he needs anyway. The *second* clause has
not fired — this is one customer's laptop, not fifteen.

### 14.1 `demo.sh` — the entry point that assumes nothing

§2's fourth audience has no `make`. Windows ships none, and the routes that
install it (winget, Chocolatey, Scoop) deliver GNU make alone, which then runs
its recipes through `cmd.exe` and fails on the first `rm -rf` — a failure that
reads as this repo's bug rather than as a missing toolchain. The routes that
*would* work (MSYS2, Cygwin, WSL) are each a larger install than the demo.

So the stack gets a second front door: **`demo.sh` at the repo root**, with
subcommands `up`, `down`, `status`, `reset` and `restart-worker`.

    bash ./demo.sh up

Invoked as `bash ./demo.sh`, not `./demo.sh`: Git for Windows does not reliably
preserve the executable bit, and a permission error on the first command is a
bad first impression.

**`make` becomes a wrapper.** Every recipe in `make/common.mk` calls
`demo.sh`, so there is one implementation and two ways to reach it. Indirection
through Make is a smell and is accepted here for one reason: the alternative is
two definitions of the same behaviours, and this build has already paid for
that twice — R-035 (`DEMO_STEP_MS` forced in one recipe and not the other) and
the `demo-reset` help entry that existed but could not be found.

**PID files replace `pgrep` and `pkill`.** This is what makes the script run in
Git Bash, which ships `rm`, `tail`, `grep`, `nohup`, `kill` and `mkdir` but not
`procps`. Each process writes its PID on start; `status` and `down` read those
files. Two consequences beyond portability:

- **`make/start.sh` folds into `demo.sh`.** That file exists *only* because
  `pgrep -f` matches whole command lines, so a recipe containing both the guard
  and the command it guards matches its own shell (R-001, R-025 — `make up`
  started nothing for eight tasks). PID files remove the class of bug, so the
  file's reason for existing goes with it.
- **A PID file can be stale.** A killed process leaves the file behind, so
  `status` must check liveness rather than existence, and a stale file must not
  make `up` refuse to start. Trading one failure mode for another only helps if
  the new one is handled.

**`.gitattributes` carries `*.sh text eol=lf`, and it is not optional.** Git for
Windows defaults to `core.autocrlf=true`, so without it the customer clones the
repo and his first command returns
`/bin/bash^M: bad interpreter: No such file or directory`. It would be the
first thing he hits, before any of this works, and it would look like our
defect.

**The risk worth stating: `uv run` spawns a child.** `uv run uvicorn …` means
`uv` starts `python`, so recording `uv`'s PID and killing it can orphan the
python process still holding port 8000 — and the symptom appears one step
later, as the *next* `up` failing on a bound port. The script records the PID
that owns the port, and the check is cycling `up`/`down` twice in a row rather
than reading the code.

**The Temporal CLI is a manual install on Windows, and the README must not
pretend otherwise.** [Temporal's own docs](https://docs.temporal.io/cli/setup-cli)
document exactly one Windows route — download the archive from
`temporal.download`, extract it, and put `temporal.exe` on `PATH`. There is no
winget, Chocolatey or Scoop package. An earlier draft of the README and of
`demo.sh`'s error message both invented `winget install Temporal.Temporal`,
which would have failed on the customer's very first command (R-039). `uv` does
have a documented winget id, `astral-sh.uv`; the two are not the same case.
`tests/test_readme.py` pins the distinction.

**Windows keeps the Make-only targets it does not need.** `fixtures`,
`histories` and `documents` stay Make-only: they need an API key and a live
stack, the customer never calls them, and putting them in `demo.sh` doubles its
surface for an audience that will not use it. §16.7 and §16.5 remain developer
workflows. `test` and `verify` need no script at all — `uv run pytest` is
already cross-platform.

**Every target is defined once, in `make/common.mk`, and entry points include
it.** The root `Makefile` is `include make/common.mk`; `python/Makefile` is
`include ../make/common.mk`; a second SDK's `go/Makefile` would be the same
line again. Each recipe derives the repo root from the included file's own path
and works from any directory, so where you invoke `make` does not change what
it does.

The rejected alternative is a root `Makefile` that *forwards* each target to
`python/` with `$(MAKE) -C python $@`. It works, and it costs a second copy of
the target list at the root (a third, counting `.PHONY`) plus a hop between the
name and the recipe. A target added to `common.mk` and not to the root list is
then simply missing, with no error to say so. Naming a target twice to reach it
once is the coupling this split exists to avoid.

## 15. Repository layout

Mirrors `canonical-ai-demo`'s split so a second SDK can be added without
moving anything.

```
CLAUDE.md                  run/test commands, task queue, IDs, determinism rule
CONTRACT.md                the §6 wire surface, SDK-agnostic
TALK_TRACK.md              the narration for a live or design-only walkthrough
docs/DESIGN-DIAGRAMS.md    three annotated mermaid diagrams (§21)
demo.sh                    the entry point that assumes nothing (§14.1)
.gitattributes             `*.sh text eol=lf` — without it Windows clones break demo.sh
Makefile                   one line: `include make/common.mk`
make/common.mk             every target, defined once; each recipe calls demo.sh
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

### 16.0 Stubs vs. fixtures — two different things

These are distinct, and the rules differ. Conflating them makes §16.7 read as
banning both, which would force the workflow tests to call a live model.

| | **Stub** | **Fixture** |
|---|---|---|
| What | A canned value a test constructs inline | A recorded real model response, replayed from `fixtures/` |
| Hand-written? | **Yes — correct and expected** | **Never** |
| Tests what | Control flow: does the workflow branch correctly given input X | Realism: does the loop actually find `tax_id` in the W-9 |
| Example | §16.2's stub child returning a canned `ExtractionResult` | §16.4's recorded `LLMResponse` sequence |
| Lives in | The test file | `fixtures/`, committed |

**"Never hand-written" applies only to fixtures.** A hand-written fixture
drifts from real model output and silently stops testing anything, while
looking like it still does. A hand-written stub is just a test double and is
the right tool for asserting branch behaviour.

`FIXTURE_MODE=1` selects the fixture-backed `call_llm` implementation. It has
nothing to do with stubs, which are ordinary test code.

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

Fixtures — not stubs; see §16.0 — are **recorded from real runs, never
hand-written.** A hand-written fixture drifts from real model output and
silently stops testing anything while still appearing to.

Order, and it matters because each step depends on the previous one:

1. **Generate the sample documents.** `documents/acme-corp/` — text-layer PDFs
   for articles of incorporation, business license, EIN letter, W-9, and the
   ownership declaration, with §8.4's deliberate missing `dob`. Produced from
   templates by an implementing agent; no manual authoring.
2. **Record the fixtures.** `make fixtures` runs the extraction loop live and
   writes the response sequence to `fixtures/`. Requires
   `ANTHROPIC_API_KEY` in the environment — **the one prerequisite a human must
   supply**, and only once.
3. **Commit documents and fixtures.** From here the suite runs keyless forever.
4. **Capture histories.** `make histories` (§16.5), which needs the fixtures in
   place so the runs are reproducible.

Steps 1, 2 and 4 are all agent-executable. Nothing on this list requires a
human to author content by hand.

**Re-record when, and only when:** the prompt changes, `ApplicationFields`
changes, or the document set changes. A fixture that no longer matches the
current prompt is worse than no fixture, so `make fixtures` is a deliberate act
and its output is reviewed in the diff.

### 16.8 The scenario manifest — the definition of done

**The twenty-three scenarios below are exhaustive. The build is complete when
all twenty-three pass and none are skipped.** This exists so completeness is a
*command*, not a judgement an agent makes about its own work. Prose an agent
must re-read and self-assess against is how a run ends with six tests written
and a confident report of success.

**`T-WF-10` was added after the build began**, when running the demo exposed
§10.1.1 — that `duplicate` means two different things and the workflow was
conflating them. It is the only addition, and the one the rule in
`.claude/rules/testing.md` anticipates: *"Adding a scenario is allowed: add a
row with a new ID and log the addition as a ruling. Silently dropping one is
not."* The original set was twenty-two, which is what Task 1 stubbed and what
every task before Task 22 was measured against.

**Task 1 writes all twenty-two as `@pytest.mark.skip` stubs**, named by ID,
with the scenario text as the docstring. Every subsequent turn can then run
`make test` and read remaining skips as remaining work.

| ID | Scenario | §  |
|----|----------|----|
| `T-ACT-01` | `ingest_documents` copies files and returns refs; missing file raises non-retryable | 16.1 |
| `T-ACT-02` | `call_llm` error classification: 401 non-retryable, 429 sets `next_retry_delay`, 5xx retryable | 16.1 |
| `T-ACT-03` | `open_account` twice with the same idempotency key: second returns `duplicate` | 16.1 |
| `T-WF-01` | Happy path completes with `status="completed"` and a client ID | 16.2 |
| `T-WF-02` | Reject increments `attempt` and re-runs `ingest_documents` | 16.2 |
| `T-WF-03` | `MAX_ATTEMPTS` exhausted → `manual_intervention` | 16.2 |
| `T-WF-04` | Approve with a required field empty → validator rejects the update | 16.2 |
| `T-WF-05` | Approve without `attested` → validator rejects | 16.2 |
| `T-WF-06` | `sum(ownership_pct) > 100` → validator rejects | 16.2 |
| `T-WF-07` | Timeout then duplicate → workflow proceeds, ledger holds exactly one account | 16.2 |
| `T-WF-08` | Core rejects the application → `rejected_by_core` | 16.2 |
| `T-WF-09` | `ChildWorkflowError` counts as a spent attempt | 16.2 |
| `T-WF-10` | Duplicate on the **first** core attempt → `already_onboarded`, delivery skipped | 16.2 |
| `T-TIME-01` | Remind fires at `SLA_REMIND`, escalate at `SLA_ESCALATE`, workflow still waiting | 16.3 |
| `T-TIME-02` | **Far past both SLAs, stage is still `awaiting_review`** — never auto-approves | 16.3 |
| `T-TIME-03` | `CLIENT_ID_SLA` fires and does not abandon the workflow | 16.3 |
| `T-CHILD-01` | EIN letter illegible → the loop requests the W-9 and finds `tax_id` | 16.4 |
| `T-CHILD-02` | `dob` absent everywhere → `escalated=True` with `documents_searched` populated | 16.4 |
| `T-CHILD-03` | `MAX_ITERATIONS` reached → `escalated=True`, no exception raised | 16.4 |
| `T-REPLAY-01` | Happy-path history replays clean | 16.5 |
| `T-REPLAY-02` | Reject-loop history replays clean | 16.5 |
| `T-REPLAY-03` | Timeout-retry history replays clean | 16.5 |
| `T-REPLAY-04` | Escalation history replays clean | 16.5 |

The four `T-REPLAY-*` rows are one scenario per committed history, generated
together in §16.7 step 4.

**`make verify` asserts `skipped == 0` and all tests pass.** That is the
machine-checkable finish line — the thing `DEVELOPMENT-PROCESS.md` calls the
executable verification gate.

**The wrinkle, stated so nobody trips on it.** A pre-written stub cannot import
modules that do not exist yet, so all twenty-two start as skip-marked
placeholders — a *manifest*, not TDD. Each task then converts its own stubs
into real failing tests and makes them pass. TDD holds *within* a task; the
manifest gives the global checklist *between* tasks.

**Adding a scenario is allowed; silently dropping one is not.** If an
implementing agent finds a case this list misses, it adds a row with a new ID
and logs the addition as a ruling (§19). Removing a row requires the same, with
the reason.

**Stage 2 consequence: task 1 is this harness and this manifest, not a
feature.** Everything downstream gates on it.

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
| `DEMO_STEP_MS` | `0` | `1500` |
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

### 17.1 `DEMO_STEP_MS` — pacing the stages so they can be watched

§2's primary audience is an SE driving the page live on a customer call. The
stubbed stages complete in milliseconds, so the stepper jumps from 1 to 3
before anyone has read it — and *visible progress through a long process* is
the whole point being demonstrated. `DEMO_STEP_MS` pads the fast stages.
Default `0`: `make test` and `make verify` are unaffected.

**The delay goes inside the activity, never in the workflow.** A
`workflow.sleep()` between steps would emit `TimerStarted` / `TimerFired` into
every execution, invalidating all nine committed histories and forcing a
re-capture of the §16.5 replay gate — the gate's whole value is that it is not
re-captured to make it pass. Activity *duration* adds no events at all;
`ActivityTaskScheduled/Started/Completed` are already there. It is also the
better picture: a padded activity shows as **Running** on the Timeline carrying
its `static_summary` (§12), which is the observability story, where a bare
timer illustrates nothing.

**`await asyncio.sleep()`, never `time.sleep()`.** Every activity here is
`async def` and the worker registers no `activity_executor`, so they share the
event loop; a blocking sleep would stall every other activity, every workflow
task and the pollers. Temporal's own guidance is explicit that `time.sleep` in
an `async def` activity "can block the entire system from doing anything".
`core_banking/app.py` does use `time.sleep` for `CORE_SLOW_MS` and is correct
to — its routes are sync `def`, which FastAPI runs in a threadpool. The
precedent does not transfer.

| Stage | Activity | Multiplier | At `1500` |
|-------|----------|-----------:|----------:|
| 1 Collect docs | `ingest_documents` | 2× | 3.0s |
| 2 Extract | `fixture_call_llm` **only** | 1× per iteration | 1.5s |
| 6 Send docs | `send_documents` | 1× | 1.5s |
| 7 Notify | `notify` | 0.5× | 0.75s |

Multipliers rather than one flat value, so the beats vary instead of landing
on a suspiciously identical rhythm; ingest is longest because it is five
documents.

**Step 2 is padded under `FIXTURE_MODE` only.** A live extraction already takes
real seconds per iteration, so padding it there would slow the demo down for no
illustrative gain. `live_call_llm` is untouched.

**Steps 3, 4 and 5 get nothing.** The KYC gate and the client-ID wait are
already long and already the point, and `open_account` must not be touched at
all: its 5s `start_to_close_timeout` **is** the ambiguous-timeout beat (§10.1),
and padding it would either eat the margin or fire the timeout spuriously.
`CORE_SLOW_MS` is the deliberate, purposeful version of a slow core, and it
lives on the core-banking side.

## 18. Non-goals and stated scope cuts

Each of these will be asked about. The spec states the cut and where it would
attach, because *"yes, here is how, we cut it deliberately"* is a far better
answer than silence.

| Cut | Why | Where it would attach |
|-----|-----|----------------------|
| **Document trickle** — workflow starts at application creation, then waits for documents to arrive by signal over weeks, chasing the client | Adds a second long-running wait and a second timer story; §1 commits to one headline failure | A signal loop before step 2, with its own SLA. Partially covered already: the reject loop re-ingests, so added documents work |
| **Docker** | Re-decided, not inherited. §14's own trigger — *"turning the repo into a self-serve customer artifact"* — fired when §2's fourth audience appeared, so the original reason for this cut ("a stranger running the repo with only Docker installed is not the primary use case") is **void**. Three reasons survive it. There is still nothing to containerise: Temporal is the state store, documents are a directory, the ledger is SQLite — canonical's compose file exists for a Postgres this demo does not have. Docker Desktop is a larger install than the two the customer needs anyway (`uv`, the Temporal CLI), and carries commercial licensing questions a bank's laptop may not clear. And it would hide the thing §14 is demonstrating: four host processes you can kill individually, which is what makes the worker-kill beat legible. **What would still flip it:** the workshop case in §14 — many laptops whose Python installs cannot be debugged one at a time | `docker/` per canonical's precedent, kept out of the local dev path |
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

## 20. Parallelization structure

**Input to Stage 2, not the plan itself.** The task breakdown is
`superpowers:writing-plans`' job. What follows are the dependency facts that
are *design* information, recorded so a planner does not have to infer them —
inference is where parallel plans go wrong.

### 20.1 What is genuinely independent

Three components import **zero** worker code and depend only on §5 models and
the §6 contract. This is not incidental; it is why §15 splits the tree this
way and what decision 7's `CONTRACT.md` buys.

| Component | Depends on | Does **not** depend on |
|-----------|------------|------------------------|
| `web/` (gateway + console) | §6 wire surface, §6.1 endpoints, §5.6 `OnboardingStatus`, `ReviewSubmission` | any workflow or activity implementation |
| `core_banking/` | `OpenAccountRequest`, `OpenAccountAck`, `ClientIdAssignment`, §11 behaviour | Temporal entirely — it only speaks HTTP |
| `documents/acme-corp/` | §5.2 document kinds, §8.4 deliberate gap | all code |

`core_banking/` is the strongest case: it never imports `temporalio` at all.

### 20.2 The dependency shape

```
Task 1 (sequential — everything gates on it)
  §5 models · §16.8 scenario manifest as skipped stubs · §17 config
  · Makefile + make/common.mk skeleton
                              │
   ┌──────────────┬───────────┴────────────┬────────────────────┬──────────────────┐
   A: worker      B: gateway + console     C: core banking      D: sample docs     E: design artifact
   workflows/     web/gateway.py           core_banking/app.py  documents/         docs/DESIGN-DIAGRAMS.md
   activities/    web/static/                                   acme-corp/         TALK_TRACK.md
   prompts.py                                                                      (§21)
   └──────────────┴───────────┬────────────┴────────────────────┴──────────────────┘
                              │
              fixtures (needs A + D)          §16.7 step 2
                              │
              histories (needs A + B + C)     §16.7 step 4
                              │
              T-REPLAY-01…04                  §16.5
```

**Why the tail is sequential:** fixtures require a working loop and real
documents; histories require a runnable end-to-end stack; replay tests require
committed histories. No amount of parallelism compresses that chain — it is a
genuine data dependency, not a scheduling artifact.

**Track E depends on nothing but this spec**, so it can start immediately and
in parallel with task 1. It is the only track that must complete even if every
other track is abandoned (§2, §21), so a planner should schedule it **first
among the parallel tracks**, not last.

**Track A is itself splittable** — `workflows/onboarding.py` and
`workflows/extraction.py` meet only at `ExtractionRequest`/`ExtractionResult`
(§5.3), which task 1 already fixed. The parent can be built against a stub
child (§16.0) while the child is built independently. This is decision 1's
child-workflow boundary paying off a second time.

### 20.3 Shared-file hazards

Worktree isolation prevents agents from disturbing each other's working tree
but does **not** prevent merge conflicts. These files are touched by more than
one track and should be written once in task 1, then treated as append-only:

| File | Why it collides |
|------|-----------------|
| `python/models/` | every track imports it |
| `Makefile`, `make/common.mk` | each track wants to add its own target |
| `python/config.py` | each track adds env vars |
| `CONTRACT.md` | derived from §6; write once, do not let tracks edit it |
| `pyproject.toml` | each track adds dependencies |

**Rule: task 1 writes these completely, including targets and env vars for
components that do not exist yet.** A stub target that fails with "not
implemented" is cheaper than three agents editing the same Makefile.

## 21. The customer-shareable design artifact

**Purpose:** if this demo is never built, the design is still worth walking a
customer through. The call falls back to a generic canned AI demo, and this
artifact is what gets shared and narrated instead. **A design in prose is not
sufficient for that conversation** — it needs pictures.

Built early (§2, §20.2 track E). Depends only on this spec.

### 21.1 Deliverables

| File | Contents |
|------|----------|
| `docs/DESIGN-DIAGRAMS.md` | Three mermaid diagrams with numbered callouts |
| `TALK_TRACK.md` | The narration — follows `canonical-ai-demo`'s precedent |
| Published Artifact | The same content as a private page with a shareable link |

**Mermaid is the single source.** It is text, so it versions and reviews in a
diff; it renders on GitHub; and Artifacts render mermaid natively, so the
shareable page uses the same source rather than a second copy that drifts.

### 21.2 The three diagrams

**1. Topology** — the main picture. Must show:

- `OnboardingWorkflow` with its seven steps, and which are activities
- `ExtractionAgentWorkflow` as a child, with the attempt loop back to step 2
- The signal / update / query surface (§6), labelled by primitive
- The external systems: core banking, the document store, Claude
- Which boundaries carry **refs rather than content** (§8.2)

**2. The ambiguous-timeout sequence** — the headline (§10.1). A sequence
diagram across analyst → workflow → `open_account` → core banking, showing the
5s timeout firing while the server keeps working, the retry with the same
idempotency key, the `duplicate` response, and the ledger holding one account.
This is the diagram that sells the design; it earns its own page.

**3. The agent loop** — request documents → `call_llm` → extract → gap →
escalate, with **activity vs. inline clearly distinguished** (§8.1), because
"only one thing here is an activity" is the point a technical audience will
ask about.

### 21.3 Annotation requirement

Every diagram carries **numbered callouts** keyed to short explanations. A
diagram that only makes sense with the author in the room fails the purpose in
§2 — the fallback audience may read it after the call, or without a Temporal SE
present.

Each callout answers *why this shape*, not *what this is*. "Child workflow so a
rejected attempt gets fresh history" beats "child workflow."

### 21.4 What this artifact must not become

- **Not the spec.** No retry-policy tables, no env vars, no repo layout. It
  answers *what is the design and why*, in the language of the business
  process.
- **Not a Temporal tutorial.** Primitives are named where they explain a
  decision, not enumerated for their own sake.
- **Not dependent on the demo running.** No screenshots of the console or the
  Temporal UI, because in the fallback scenario neither exists.

## 22. Open items

None. Every question raised in Stage 1 is settled above or explicitly cut in
§18. If an implementing agent finds a genuine gap, the ruling procedure is:
consult this spec, decide, log the ruling, keep going.
