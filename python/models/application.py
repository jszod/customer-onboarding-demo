from __future__ import annotations
from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel

IdType = Literal["passport", "drivers_license", "state_id"]


class Address(BaseModel):
    line1: str
    line2: str | None = None
    city: str
    state: str
    postal_code: str
    country: str


class BeneficialOwner(BaseModel):
    full_name: str | None = None
    dob: date | None = None
    ownership_pct: Decimal | None = None
    residential_address: Address | None = None
    id_type: IdType | None = None
    id_number: str | None = None


class ControlPerson(BaseModel):
    full_name: str | None = None
    title: str | None = None
    dob: date | None = None
    residential_address: Address | None = None
    id_type: IdType | None = None
    id_number: str | None = None
    is_authorized_signatory: bool = True


class ApplicationFields(BaseModel):
    legal_name: str | None = None
    dba: str | None = None                 # optional (§5.1)
    entity_type: Literal["LLC", "C_CORP", "S_CORP", "LP", "LLP"] | None = None
    formation_date: date | None = None
    formation_state: str | None = None
    tax_id: str | None = None
    registered_address: Address | None = None
    business_address: Address | None = None
    industry_code: str | None = None
    phone: str | None = None               # optional (§5.1)
    website: str | None = None             # optional (§5.1)
    beneficial_owners: list[BeneficialOwner] = []
    control_person: ControlPerson | None = None
