"""§5.4 of the spec."""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel


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
