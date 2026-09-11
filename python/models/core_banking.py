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
    # §10.1.1. Which try answered, from `activity.info().attempt`. The retry is
    # §10.2's activity policy, so the workflow sees one call and one result and
    # cannot count attempts itself -- and it must, because `duplicate` on
    # attempt 1 means a PREVIOUS onboarding owns the account while `duplicate`
    # on a later attempt means our own call landed and the answer was lost.
    #
    # Reading the attempt number is safe. Deriving the IDEMPOTENCY KEY from it
    # is §10.1's trap and produces the duplicate account this design prevents.
    attempt: int = 1


class ClientIdAssignment(BaseModel):
    client_id: str
    core_ref: str
    assigned_at: datetime
