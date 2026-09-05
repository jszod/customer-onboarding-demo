from __future__ import annotations
from typing import Annotated, Literal
from pydantic import BaseModel, Field

from python.models.application import ApplicationFields
from python.models.documents import DocumentManifest


class FieldGap(BaseModel):
    field_path: str
    reason: str
    documents_searched: list[str] = []


class ExtractionRequest(BaseModel):
    client_key: str
    legal_name: str
    manifest: DocumentManifest
    attempt: int
    prior_gaps: list[FieldGap] = []
    analyst_note: str | None = None


class ExtractionResult(BaseModel):
    application: ApplicationFields
    gaps: list[FieldGap] = []
    iterations: int = 0
    escalated: bool = False


class AgentTurn(BaseModel):
    role: Literal["assistant", "tool"]
    content: str


class LLMRequest(BaseModel):
    model: str
    manifest: DocumentManifest
    requested_doc_ids: list[str] = []
    turns: list[AgentTurn] = []
    required_field_paths: list[str] = []
    prior_gaps: list[FieldGap] = []
    analyst_note: str | None = None


class DocumentRequest(BaseModel):
    kind: Literal["request_documents"] = "request_documents"
    doc_ids: list[str]
    rationale: str


class ExtractionSubmission(BaseModel):
    kind: Literal["submit_extraction"] = "submit_extraction"
    application: ApplicationFields
    gaps: list[FieldGap] = []


class Escalation(BaseModel):
    kind: Literal["escalate"] = "escalate"
    gaps: list[FieldGap] = []


AgentAction = Annotated[DocumentRequest | ExtractionSubmission | Escalation,
                        Field(discriminator="kind")]


class LLMResponse(BaseModel):
    action: AgentAction
    turn: AgentTurn
    usage: dict[str, int] = {}
