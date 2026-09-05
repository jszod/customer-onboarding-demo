"""The fake core banking system. §11.

Deliberately slow on the FIRST call for any idempotency key -- it creates the
account and then fails to answer in time, which is the ambiguity the whole
design exists to handle (§10.1). It NEVER imports the Temporal SDK: it only
speaks HTTP, which is what makes it independently buildable (§20.1).
"""
from __future__ import annotations

import os
import time

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from core_banking import ledger


class ControlRequest(BaseModel):
    slow_first_call: bool | None = None
    reject_next: bool | None = None


class OpenAccountBody(BaseModel):
    """The wire shape of `OpenAccountRequest` (§5.5).

    `application` stays an untyped dict on purpose: a system the bank bought in
    1998 does not import the onboarding platform's Pydantic models. Coupling
    them would undo the independence this service exists to demonstrate.
    """

    idempotency_key: str
    application: dict


def _iso(sqlite_timestamp: str | None) -> str | None:
    """SQLite's `datetime('now')` is UTC, formatted 'YYYY-MM-DD HH:MM:SS'.
    `ClientIdAssignment.assigned_at` is a datetime, so hand it ISO-8601."""
    if not sqlite_timestamp:
        return None
    return sqlite_timestamp.replace(" ", "T") + "Z"


def build_app() -> FastAPI:
    app = FastAPI(title="Fake Core Banking")
    app.state.slow_first_call = True
    app.state.slow_ms = int(os.environ.get("CORE_SLOW_MS", "10000"))
    app.state.reject_next = False
    app.state.gateway_url = os.environ.get("GATEWAY_URL", "http://localhost:8000")

    @app.post("/accounts")
    def open_account(body: OpenAccountBody):
        if app.state.reject_next:
            app.state.reject_next = False
            raise HTTPException(
                status_code=400,
                detail="Application rejected: entity not found in state registry")

        row, created = ledger.create_or_get(
            body.idempotency_key, body.application.get("legal_name"))
        if not created:
            # The retry path. This is the response that proves the key worked.
            return {"request_id": row["request_id"], "status": "duplicate"}

        if app.state.slow_first_call and app.state.slow_ms:
            # The account is ALREADY created. We simply fail to answer in time.
            time.sleep(app.state.slow_ms / 1000)
        return {"request_id": row["request_id"], "status": "accepted"}

    @app.post("/accounts/{request_id}/assign")
    def assign(request_id: str):
        row = ledger.assign_client_id(request_id)
        if not row:
            raise HTTPException(status_code=404, detail="unknown request_id")
        client_key = row["idempotency_key"].removeprefix("onboarding-")
        payload = {"client_key": client_key, "client_id": row["client_id"],
                   "core_ref": row["request_id"],
                   "assigned_at": _iso(row["assigned_at"])}
        httpx.post(f"{app.state.gateway_url}/callbacks/client-id",
                   json=payload, timeout=10.0)
        return payload

    @app.get("/ledger")
    def get_ledger():
        return {"accounts": ledger.all_accounts(),
                "slow_first_call": app.state.slow_first_call}

    @app.post("/control")
    def control(body: ControlRequest):
        if body.slow_first_call is not None:
            app.state.slow_first_call = body.slow_first_call
        if body.reject_next is not None:
            app.state.reject_next = body.reject_next
        return {"slow_first_call": app.state.slow_first_call,
                "reject_next": app.state.reject_next}

    return app


app = build_app()
