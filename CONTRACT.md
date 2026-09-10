# CONTRACT

The SDK-agnostic wire surface of the customer onboarding demo. Everything here
is a **literal string** or a **JSON shape**. No Python is required to read it.

**A worker in any SDK is "done" when it implements this file.** Nothing else in
the repository is binding on a port: the Python worker under `python/` is one
implementation of this contract, not the definition of it.

**Only one SDK's worker may poll `customer-onboarding` at a time.** Two workers
on one task queue will split tasks between them and each will fail on workflow
types the other registered. To run a port, stop the Python worker first
(`make kill-worker`).

Derived from §4.1, §6 and §6.1 of
`docs/superpowers/specs/2026-09-04-customer-onboarding-design.md`, which is the
binding authority if the two ever disagree.

---

## Identity

| Thing | Value |
|-------|-------|
| Task queue | `customer-onboarding` |
| Parent workflow type | `OnboardingWorkflow` |
| Parent workflow ID | `onboarding-<client-key>` |
| Child workflow type | `ExtractionAgentWorkflow` |
| Child workflow ID | `onboarding-<client-key>-extract-<attempt>` |
| Parent close policy | default (`TERMINATE`) |

The parent workflow ID is derived from the client key, **not a UUID**. Temporal
forbids two open runs sharing an ID, so this buys *one open onboarding per
client* — a compliance property, not tidiness. A port that generates a UUID
here has not implemented this contract.

## Handlers

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

Each primitive is used where it belongs:

| Primitive | Used for | Why not the others |
|-----------|----------|--------------------|
| Update | `submit_review` | needs validation *and* a response |
| Signal | `client_id_received` | external system, fire-and-forget, nothing to return |
| Query | `status` | read-only, drives the console, not recorded in history |

**One argument object per handler.** No positional argument lists anywhere,
including single-field payloads. A port that flattens `IngestRequest` into two
positional arguments is wire-incompatible.

## Payloads

Every payload is a JSON object. `null` is written where a field is nullable;
a field with a default may be omitted. Dates are ISO-8601 (`YYYY-MM-DD`),
timestamps are RFC-3339, and decimals are JSON strings to avoid float drift.

### `ApplicationRequest` — starts the parent

```json
{ "client_key": "acme-corp", "legal_name": "Acme Holdings LLC" }
```

Document refs are produced **inside** the workflow by `ingest_documents`, not
passed in.

### `Address`

```json
{
  "line1": "410 Harbor St", "line2": null, "city": "Boston",
  "state": "MA", "postal_code": "02210", "country": "US"
}
```

### `BeneficialOwner`

```json
{
  "full_name": "Dana Whitfield", "dob": "1978-06-02", "ownership_pct": "55",
  "residential_address": { "…Address…": null },
  "id_type": "passport", "id_number": "X4419223"
}
```

`id_type` is one of `passport`, `drivers_license`, `state_id`.

### `ControlPerson`

`BeneficialOwner`'s fields with `ownership_pct` replaced by `title`, plus
`is_authorized_signatory` (boolean, default `true`).

### `ApplicationFields`

```json
{
  "legal_name": "Acme Holdings LLC", "dba": null, "entity_type": "LLC",
  "formation_date": "2019-03-11", "formation_state": "DE",
  "tax_id": "88-1234567",
  "registered_address": { "…Address…": null },
  "business_address": { "…Address…": null },
  "industry_code": "541611", "phone": null, "website": null,
  "beneficial_owners": [ { "…BeneficialOwner…": null } ],
  "control_person": { "…ControlPerson…": null }
}
```

`entity_type` is one of `LLC`, `C_CORP`, `S_CORP`, `LP`, `LLP`.

**Exactly three fields are optional: `dba`, `phone`, `website`.** Everything
else is required, and the required set is enumerated once — in the Python
implementation at `config.REQUIRED_FIELD_PATHS`. A port must enumerate the same
set in exactly one place of its own, so the console, the gaps list and the
approve rule cannot disagree.

Required paths, including the list-member form:

```
legal_name, entity_type, formation_date, formation_state, tax_id,
registered_address, business_address, industry_code,
beneficial_owners,
beneficial_owners[].full_name, beneficial_owners[].dob,
beneficial_owners[].ownership_pct, beneficial_owners[].residential_address,
beneficial_owners[].id_type, beneficial_owners[].id_number,
control_person,
control_person.full_name, control_person.title, control_person.dob,
control_person.residential_address, control_person.id_type,
control_person.id_number
```

`beneficial_owners[].dob` expands to one path per owner index — the gap the
demo turns on is `beneficial_owners[1].dob`.

### `DocumentRef` / `DocumentManifest` / `IngestRequest`

```json
{
  "doc_id": "ownership-declaration", "kind": "ownership_declaration",
  "uri": "acme-corp/1/ownership-declaration.pdf",
  "sha256": "0000…", "page_count": 1
}
```

```json
{ "refs": [ { "…DocumentRef…": null } ] }
```

```json
{ "client_key": "acme-corp", "attempt": 1 }
```

`kind` is one of `articles_of_incorporation`, `business_license`, `ein_letter`,
`w9`, `ownership_declaration`.

**Document content never crosses the wire.** Workflows carry refs and doc ids;
activities resolve them to text internally.

### `FieldGap`

```json
{
  "field_path": "beneficial_owners[1].dob",
  "reason": "beneficial_owners[1].dob not found in any supplied document",
  "documents_searched": ["ownership_declaration"]
}
```

### `ExtractionRequest` / `ExtractionResult`

```json
{
  "client_key": "acme-corp", "legal_name": "Acme Holdings LLC",
  "manifest": { "…DocumentManifest…": null }, "attempt": 1,
  "prior_gaps": [], "analyst_note": null
}
```

```json
{
  "application": { "…ApplicationFields…": null },
  "gaps": [], "iterations": 0, "escalated": false
}
```

**Escalation is a return value, never an exception**: `escalated: true`.

### `AgentTurn` / `LLMRequest` / `LLMResponse`

```json
{ "role": "assistant", "content": "checking the W-9" }
```

`role` is `assistant` or `tool`.

```json
{
  "model": "claude-sonnet-5", "manifest": { "…DocumentManifest…": null },
  "requested_doc_ids": [], "turns": [], "required_field_paths": [],
  "prior_gaps": [], "analyst_note": null
}
```

```json
{
  "action": { "…AgentAction…": null },
  "turn": { "…AgentTurn…": null },
  "usage": { "input_tokens": 10, "output_tokens": 5 }
}
```

`action` is a **discriminated union on `kind`**. The workflow dispatches on
`kind` and never parses raw model output:

```json
{ "kind": "request_documents", "doc_ids": ["w9"], "rationale": "tax_id not in ein_letter" }
{ "kind": "submit_extraction", "application": { "…" : null }, "gaps": [] }
{ "kind": "escalate", "gaps": [] }
```

`call_llm` returns validated models. A port that hands raw text back to the
workflow has not implemented this contract.

### `FieldEdit` / `ReviewSubmission` / `ReviewAck`

```json
{ "field_path": "beneficial_owners[1].dob", "value": "1985-01-01" }
```

`value` is always a JSON string and is coerced against the schema on merge.

```json
{
  "decision": "approve", "analyst_id": "kyc-analyst-1", "note": null,
  "field_edits": [], "attested": false
}
```

```json
{ "accepted": true, "stage": "submitting_to_core" }
```

`decision` is `approve` or `reject`. Merging edits **returns a new application
rather than overwriting the AI's output in place** — the audit rule.

### `OpenAccountRequest` / `OpenAccountAck` / `ClientIdAssignment`

```json
{ "idempotency_key": "onboarding-acme-corp", "application": { "…": null } }
```

**The idempotency key is the parent workflow ID**, stable across every retry.
A port that derives it from the activity attempt number has reintroduced the
bug this demo exists to show.

```json
{ "request_id": "REQ-1", "status": "accepted" }
```

`status` is `accepted` or `duplicate`. `OpenAccountAck` deliberately **does
not** carry the client ID — that is the point of the async return path, and
`duplicate` is the proof the idempotency key worked.

```json
{ "client_id": "CL-1", "core_ref": "CORE-9", "assigned_at": "2026-09-05T14:03:00Z" }
```

### `SendDocumentsRequest` / `SendDocumentsResult` / `NotifyRequest` / `NotifyResult`

```json
{
  "client_key": "acme-corp", "client_id": "CL-1",
  "legal_name": "Acme Holdings LLC", "application": { "…": null }
}
```

```json
{ "packet_uri": "acme-corp/CL-1.txt", "page_count": 1 }
```

```json
{
  "client_key": "acme-corp", "client_id": "CL-1", "outcome": "completed",
  "recipients": ["onboarding_specialist"], "packet_uri": "acme-corp/CL-1.txt",
  "detail": "onboarding complete"
}
```

```json
{ "delivered_to": ["onboarding_specialist"] }
```

`outcome` is one of `completed`, `manual_intervention`, `rejected_by_core`,
`already_onboarded`.
`recipients` entries are `onboarding_specialist`, `end_client`, `supervisor`.
`notify` is one activity with three callers — the terminal notification, the
SLA reminder and the escalation — distinguished by `recipients`.

Both are idempotent by construction: `send_documents` writes to a deterministic
path derived from `client_key` and `client_id`, so a retry overwrites rather
than duplicating; `notify` appends a record keyed by
`(client_key, outcome, recipients)`.

### `OnboardingStatus` — returned by the `status` query

```json
{
  "stage": "awaiting_review", "attempt": 1, "application": null, "gaps": [],
  "pending_since": null, "core_attempt": 0, "last_error": null,
  "core_request_id": null, "client_id": null, "extraction_iterations": 0
}
```

`stage` is one of `ingesting`, `extracting`, `awaiting_review`,
`submitting_to_core`, `awaiting_client_id`, `sending_documents`, `notifying`,
`complete`, `manual_intervention`, `rejected_by_core`, `already_onboarded`.

`already_onboarded` is terminal: core banking answered `duplicate` on the
**first** attempt, so a previous onboarding owns the account and this run
created nothing (§10.1.1). The status also carries `core_duplicate` and
`core_preexisting` so a client can tell that case from the retry case, where
the same `duplicate` means our own call landed and the answer was lost.

### `OnboardingResult` — returned by the parent workflow

```json
{
  "status": "completed", "client_id": "CL-1", "attempts": 1,
  "detail": "onboarding complete"
}
```

`status` is one of `completed`, `manual_intervention`, `rejected_by_core`,
`already_onboarded`.
**Every failure path ends in one of these**, never a failed workflow.

## Gateway HTTP surface

The gateway is the only thing that talks to Temporal. It imports **zero**
worker code — it drives workflows by the string names above, so it serves any
SDK's worker unchanged.

| Endpoint | Purpose |
|----------|---------|
| `POST /applications` | Body `{client_key}`. Starts `OnboardingWorkflow` with ID `onboarding-<client-key>`. Returns 409 `{error: "already in progress"}` when Temporal rejects the duplicate ID |
| `GET /api/status/{client_key}` | Proxies the `status` query; returns `OnboardingStatus` |
| `POST /api/review/{client_key}` | Body `ReviewSubmission`. Sends the `submit_review` update; returns `ReviewAck`, or 422 with the validator's rejection message |
| `POST /callbacks/client-id` | Body `ClientIdAssignment` plus `client_key`. Called **by the core banking service**; sends the `client_id_received` signal |
| `POST /api/control` | Forwards demo toggles (slow-first-call, forced rejection) to the core banking service, and sets the LLM-outage flag |
| `GET /` | Serves the console |

The 409 on a duplicate start is not an error path to hide — it is the
demonstration of the workflow-ID property, and the console surfaces it as
*"onboarding already in progress for acme-corp."*

## Data converter

Every process that talks to Temporal — worker, gateway, core-banking callback,
tests — must use the same payload conversion. In the Python implementation that
is `pydantic_data_converter`, constructed in exactly one place. A port must
match the JSON encoding above; a mismatch produces deserialization errors that
look like corruption rather than configuration.
