from __future__ import annotations
from typing import Literal
from pydantic import BaseModel

DocumentKind = Literal["articles_of_incorporation", "business_license",
                       "ein_letter", "w9", "ownership_declaration"]


class DocumentRef(BaseModel):
    doc_id: str
    kind: DocumentKind
    uri: str
    sha256: str
    page_count: int


class DocumentManifest(BaseModel):
    refs: list[DocumentRef] = []


class IngestRequest(BaseModel):
    client_key: str
    attempt: int
