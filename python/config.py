"""Single source of configuration. §17 of the spec.

The data converter is constructed ONLY here (§17) so that enabling a
PayloadCodec later is configuration rather than surgery (§18).
"""
from __future__ import annotations

import asyncio
import os
import re
from datetime import timedelta
from pathlib import Path

from pydantic import BaseModel
from temporalio.converter import DataConverter

_DURATION = re.compile(r"^(\d+)([smhd])$")
_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


def _duration(raw: str) -> timedelta:
    m = _DURATION.match(raw.strip())
    if not m:
        raise ValueError(f"bad duration {raw!r}; use forms like 30s, 5m, 3d")
    return timedelta(**{_UNITS[m.group(2)]: int(m.group(1))})


class Settings(BaseModel):
    temporal_address: str
    task_queue: str
    model: str
    fixture_mode: bool
    max_attempts: int
    max_iterations: int
    sla_remind: timedelta
    sla_escalate: timedelta
    client_id_sla: timedelta
    core_slow_ms: int
    demo_step_ms: int
    document_store: Path
    core_banking_url: str
    gateway_url: str
    outbox_dir: Path
    payload_codec: str


def settings() -> Settings:
    env = os.environ.get
    return Settings(
        temporal_address=env("TEMPORAL_ADDRESS", "localhost:7233"),
        task_queue=env("TASK_QUEUE", "customer-onboarding"),
        model=env("MODEL", "claude-sonnet-5"),
        fixture_mode=env("FIXTURE_MODE", "0") == "1",
        max_attempts=int(env("MAX_ATTEMPTS", "3")),
        max_iterations=int(env("MAX_ITERATIONS", "8")),
        sla_remind=_duration(env("SLA_REMIND", "3d")),
        sla_escalate=_duration(env("SLA_ESCALATE", "7d")),
        client_id_sla=_duration(env("CLIENT_ID_SLA", "1d")),
        core_slow_ms=int(env("CORE_SLOW_MS", "10000")),
        demo_step_ms=int(env("DEMO_STEP_MS", "0")),
        document_store=Path(env("DOCUMENT_STORE", "./.store")),
        core_banking_url=env("CORE_BANKING_URL", "http://localhost:8001"),
        gateway_url=env("GATEWAY_URL", "http://localhost:8000"),
        outbox_dir=Path(env("OUTBOX_DIR", "./outbox")),
        payload_codec=env("PAYLOAD_CODEC", "off"),
    )


async def demo_pause(multiplier: float = 1.0) -> None:
    """§17.1. Pad a stubbed stage so a live audience can watch it happen.

    `asyncio.sleep`, not `time.sleep`: the activities are `async def` sharing
    one event loop, so a blocking sleep would stall every other activity, the
    workflow tasks and the worker's pollers. And this belongs in an ACTIVITY,
    never in a workflow -- activity duration adds no history events, where a
    durable timer would rewrite all nine committed histories (§16.5).

    Default 0, so the suite pays nothing for it.
    """
    ms = settings().demo_step_ms
    if ms:
        await asyncio.sleep(ms * multiplier / 1000)


def build_data_converter() -> DataConverter:
    """Every process that talks to Temporal must use this. A mismatch produces
    deserialization errors that look like corruption rather than config."""
    from temporalio.contrib.pydantic import pydantic_data_converter

    if settings().payload_codec != "off":
        raise NotImplementedError(
            "PayloadCodec encryption is a stated scope cut (§18). Enabling it "
            "requires a codec server plus --codec-endpoint on the UI and CLI."
        )
    return pydantic_data_converter


# §5.1: declared in exactly one place, so the console, the gaps list, and the
# approve rule can never disagree.
REQUIRED_FIELD_PATHS: tuple[str, ...] = (
    "legal_name", "entity_type", "formation_date", "formation_state", "tax_id",
    "registered_address", "business_address", "industry_code",
    "beneficial_owners",
    "beneficial_owners[].full_name", "beneficial_owners[].dob",
    "beneficial_owners[].ownership_pct", "beneficial_owners[].residential_address",
    "beneficial_owners[].id_type", "beneficial_owners[].id_number",
    "control_person",
    "control_person.full_name", "control_person.title", "control_person.dob",
    "control_person.residential_address", "control_person.id_type",
    "control_person.id_number",
)

# §5.2 — which document each field lives in; used for FieldGap.documents_searched
FIELD_SOURCES: dict[str, tuple[str, ...]] = {
    "legal_name": ("articles_of_incorporation", "w9"),
    "entity_type": ("articles_of_incorporation",),
    "formation_date": ("articles_of_incorporation",),
    "formation_state": ("articles_of_incorporation",),
    "registered_address": ("articles_of_incorporation",),
    "tax_id": ("ein_letter", "w9"),
    "dba": ("business_license",),
    "business_address": ("business_license",),
    "industry_code": ("business_license",),
}
_OWNERSHIP_SOURCES = ("ownership_declaration",)
