"""The extraction prompt and the model's tool surface. §8.1, §8.3.

Kept out of `python/workflows/` on purpose: the prompt is an input to the
`call_llm` activity, and editing it must never be able to change what a
workflow replays.
"""

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
     "input_schema": {"type": "object",
                      "properties": {"application": {"type": "object"},
                                     "gaps": {"type": "array",
                                              "items": {"type": "object"}}},
                      "required": ["application", "gaps"]}},
    {"name": "escalate",
     "description": "Hand the remaining gaps to a human reviewer, along with "
                    "everything you were able to extract.",
     "input_schema": {"type": "object",
                      "properties": {"application": {"type": "object"},
                                     "gaps": {"type": "array",
                                              "items": {"type": "object"}}},
                      "required": ["application", "gaps"]}},
]
