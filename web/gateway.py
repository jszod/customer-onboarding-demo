"""The gateway. §6.1.

Imports ZERO worker code -- every workflow interaction is by string name, which
is what makes CONTRACT.md real rather than aspirational (§15, §20.1).
"""
from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from temporalio.client import Client, WorkflowUpdateFailedError
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from python import config

STATIC = Path(__file__).parent / "static"

CLIENTS = {"acme-corp": "Acme Holdings LLC"}


class SubmitBody(BaseModel):
    client_key: str


class ControlBody(BaseModel):
    slow_first_call: bool | None = None
    reject_next: bool | None = None
    llm_down: bool | None = None


async def temporal_client() -> Client:
    s = config.settings()
    return await Client.connect(s.temporal_address,
                                data_converter=config.build_data_converter())


def _handle(client: Client, client_key: str):
    return client.get_workflow_handle(f"onboarding-{client_key}")


def _llm_down_flag() -> Path:
    """§10.4. The toggle must reach the worker, which is a different process,
    so it is a flag file rather than gateway memory. `live_call_llm` reads it."""
    return config.settings().document_store.parent / ".llm_down"


def build_app() -> FastAPI:
    app = FastAPI(title="Customer Onboarding Gateway")
    s = config.settings()

    @app.post("/applications")
    async def submit(body: SubmitBody):
        legal_name = CLIENTS.get(body.client_key, body.client_key)
        client = await temporal_client()
        try:
            await client.start_workflow(
                "OnboardingWorkflow",
                {"client_key": body.client_key, "legal_name": legal_name},
                id=f"onboarding-{body.client_key}",
                task_queue=s.task_queue,
                static_summary=f"Onboard {legal_name} — business account",
                static_details=(
                    f"Client key: `{body.client_key}`\n\n"
                    f"Documents: 5 (articles of incorporation, business licence, "
                    f"EIN letter, W-9, ownership declaration)\n\n"
                    f"Required fields: {len(config.REQUIRED_FIELD_PATHS)}\n\n"
                    f"KYC SLA: remind {s.sla_remind}, escalate {s.sla_escalate}"),
            )
        except WorkflowAlreadyStartedError:
            # The typed form, raised when the ALREADY_EXISTS details unpack.
            return _already_in_progress(body.client_key)
        except RPCError as e:
            if e.status == RPCStatusCode.ALREADY_EXISTS:
                # §6.1: not an error to hide -- this IS the workflow-ID demo.
                return _already_in_progress(body.client_key)
            raise
        return JSONResponse(status_code=202, content={"client_key": body.client_key})

    @app.get("/api/status/{client_key}")
    async def status(client_key: str):
        client = await temporal_client()
        try:
            return await _handle(client, client_key).query("status")
        except RPCError as e:
            if e.status == RPCStatusCode.NOT_FOUND:
                # The console polls from page load, before anything is running.
                return JSONResponse(
                    status_code=404,
                    content={"error": f"no onboarding running for {client_key}"})
            raise

    @app.post("/api/review/{client_key}")
    async def review(client_key: str, request: Request):
        client = await temporal_client()
        try:
            return await _handle(client, client_key).execute_update(
                "submit_review", await request.json())
        except WorkflowUpdateFailedError as e:
            # The update validator rejected it before it entered history (§9.1).
            # The wrapper's own message is "Workflow update failed"; §6.1 wants
            # the validator's reason, which is the cause.
            return JSONResponse(status_code=422, content={"error": str(e.cause)})
        except ApplicationError as e:
            return JSONResponse(status_code=422, content={"error": str(e)})

    @app.post("/callbacks/client-id")
    async def client_id_callback(request: Request):
        body = await request.json()
        client_key = body.pop("client_key")
        client = await temporal_client()
        await _handle(client, client_key).signal("client_id_received", body)
        return JSONResponse(status_code=202, content={"signalled": client_key})

    @app.post("/api/control")
    async def control(body: ControlBody):
        if body.llm_down is not None:
            flag = _llm_down_flag()
            if body.llm_down:
                flag.parent.mkdir(parents=True, exist_ok=True)
                flag.write_text("llm outage toggled from the console (§10.4)\n")
            else:
                flag.unlink(missing_ok=True)
        core = {k: v for k, v in
                {"slow_first_call": body.slow_first_call,
                 "reject_next": body.reject_next}.items() if v is not None}
        if core:
            async with httpx.AsyncClient(timeout=10.0) as hc:
                await hc.post(f"{s.core_banking_url}/control", json=core)
        return {"llm_down": _llm_down_flag().exists(), **core}

    @app.post("/api/assign/{client_key}")
    async def assign(client_key: str):
        """Console's 'Return client ID' button -> core banking's assign."""
        client = await temporal_client()
        st = await _handle(client, client_key).query("status")
        request_id = st["core_request_id"]
        async with httpx.AsyncClient(timeout=30.0) as hc:
            r = await hc.post(f"{s.core_banking_url}/accounts/{request_id}/assign")
        return r.json()

    @app.get("/")
    def console():
        return FileResponse(STATIC / "index.html")

    return app


def _already_in_progress(client_key: str) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"error": f"onboarding already in progress for {client_key}"})


app = build_app()
