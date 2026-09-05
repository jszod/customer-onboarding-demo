"""§5.5 of the spec.

`OpenAccountAck` deliberately does not carry the client ID. That is the point
of the async return path (§9.3); `status: "duplicate"` is the proof the
idempotency key worked and is what the operator points at on stage.
"""
from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel

from python.models.application import ApplicationFields


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
