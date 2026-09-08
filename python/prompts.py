"""The extraction prompt and the model's tool surface. §8.1, §8.3.

Kept out of `python/workflows/` on purpose: the prompt is an input to the
`call_llm` activity, and editing it must never be able to change what a
workflow replays.
"""
from __future__ import annotations

from copy import deepcopy

from python.models.application import ApplicationFields
from python.models.extraction import FieldGap

SYSTEM = """You are extracting a commercial bank account application from a \
client's supporting documents.

You will be shown a manifest of available documents (id and kind) and the full \
text of any documents you have asked for. Fill as many required fields as the \
documents support.

You have exactly three moves:

- request_documents — ask to read specific documents by id. Use this when a \
field you need is likely to appear in a document you have not read yet. Note \
that a taxpayer identification number appears on BOTH an EIN letter and a W-9, \
so if one is unreadable, try the other.
- submit_extraction — return the application and any fields you could not fill.
- escalate — return the gaps for a human when a required field is genuinely \
absent from every document you have read, and no unread document could \
plausibly contain it. Always include `application` with every field you DID \
manage to fill: the human picks up where you left off, and omitting it makes \
them retype work you have already done.

Never invent a value. A field you cannot find is a gap, and reporting it \
accurately is more useful than guessing. For each gap, record which documents \
you searched."""

def _terminal_payload_schema() -> dict:
    """`submit_extraction` and `escalate` take the same two arguments, and both
    schemas are GENERATED from the Pydantic models rather than written here.

    `payloads-and-activities.md` requires it, and a live run showed what the
    hand-written `{"type": "object"}` cost: told nothing about the shape, the
    model answered with `field` for `field_path`, `'Passport'` for the
    `passport` enum, `'30%'` for a `Decimal` and a flat string where an
    `Address` belongs. Pydantic rejected all of it as MalformedResponse, which
    §10.2 classifies as RETRYABLE -- so in the workflow an impossible call
    retries forever and the extraction hangs instead of failing.

    Generated, so the schema cannot drift from the models: adding a field to
    `ApplicationFields` teaches the model about it in the same commit.

    `$defs` is hoisted to the root because that is where the `$ref`s generated
    inside `application` and `gaps` resolve -- `#/$defs/Address` is relative to
    the top of the schema the API is handed, not to the property it sits under.
    """
    app = deepcopy(ApplicationFields.model_json_schema())
    gap = deepcopy(FieldGap.model_json_schema())
    defs = {**app.pop("$defs", {}), **gap.pop("$defs", {})}
    schema = {"type": "object",
              "properties": {"application": app,
                             "gaps": {"type": "array", "items": gap}},
              "required": ["application", "gaps"]}
    if defs:
        schema["$defs"] = defs
    return schema


TOOLS = [
    {"name": "request_documents",
     "description": "Read specific documents by id before extracting.",
     "input_schema": {
         "type": "object",
         "properties": {
             "doc_ids": {"type": "array", "items": {"type": "string"}},
             "rationale": {"type": "string",
                           "description": "why these documents, in one line"}},
         "required": ["doc_ids", "rationale"]}},
    {"name": "submit_extraction",
     "description": "Return the completed application and any remaining gaps.",
     "input_schema": _terminal_payload_schema()},
    {"name": "escalate",
     "description": "Hand the remaining gaps to a human reviewer, along with "
                    "everything you were able to extract.",
     "input_schema": _terminal_payload_schema()},
]
