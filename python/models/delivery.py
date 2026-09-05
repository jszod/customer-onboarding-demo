"""§5.5.1 of the spec.

`send_documents` writes a welcome-pack file under `OUTBOX_DIR` and returns its
path — a reference, not content, consistent with §8.2. `notify` appends to a
notification log the console renders; it does not send real email or SMS.

`notify` is also the activity used for the SLA reminder and escalation in §9.2,
with `recipients` set accordingly — one activity, three callers, rather than
three near-identical activities.
"""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel

from python.models.application import ApplicationFields


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
