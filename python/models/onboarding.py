"""§5.6 and §6 of the spec.

Refs are produced inside the workflow by `ingest_documents`, not passed in —
so `ApplicationRequest` carries only the client key and the legal name (§6).
"""
from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel

from python.models.application import ApplicationFields
from python.models.extraction import FieldGap


class ApplicationRequest(BaseModel):
    client_key: str
    legal_name: str


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
    # §10.1.1. `duplicate` means two different things and the console has to
    # be able to say which. Query-only, so free against the replay gate (§13).
    core_duplicate: bool = False      # core banking answered "duplicate"
    core_preexisting: bool = False    # ...on attempt 1: a prior onboarding owns it


class OnboardingResult(BaseModel):
    status: Literal["completed", "manual_intervention", "rejected_by_core",
                    "already_onboarded"]
    client_id: str | None
    attempts: int
    detail: str
