"""Task 7 — the gateway. §6.1.

The gateway is the only thing that talks to Temporal, and it does so by the
literal string names in CONTRACT.md. No live server is needed: a hand-written
FakeClient/FakeHandle records what the gateway asked for, which is exactly the
property under test — *which strings*, *which workflow ID*, *which primitive*.
"""
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


class FakeHandle:
    def __init__(self, recorder):
        self._rec = recorder

    async def query(self, name, *args):
        self._rec.append(("query", name))
        return {"stage": "awaiting_review", "attempt": 1, "application": None,
                "gaps": [], "pending_since": None, "core_attempt": 0,
                "last_error": None, "core_request_id": None, "client_id": None,
                "extraction_iterations": 0}

    async def execute_update(self, name, arg):
        self._rec.append(("update", name, arg))
        return {"accepted": True, "stage": "submitting_to_core"}

    async def signal(self, name, arg):
        self._rec.append(("signal", name, arg))


class FakeClient:
    def __init__(self):
        self.calls = []
        self.started = []

    async def start_workflow(self, workflow, arg, *, id, task_queue, **kwargs):
        if any(s["id"] == id for s in self.started):
            from temporalio.service import RPCError, RPCStatusCode
            raise RPCError("already started", RPCStatusCode.ALREADY_EXISTS, b"")
        self.started.append({"id": id, "workflow": workflow, "arg": arg,
                             "task_queue": task_queue, "kwargs": kwargs})
        return FakeHandle(self.calls)

    def get_workflow_handle(self, workflow_id):
        return FakeHandle(self.calls)


def _client_for(fake, monkeypatch):
    from web import gateway

    async def fake_connect():
        return fake

    monkeypatch.setattr(gateway, "temporal_client", fake_connect)
    tc = TestClient(gateway.build_app())
    tc.fake = fake
    return tc


@pytest.fixture
def client(monkeypatch):
    return _client_for(FakeClient(), monkeypatch)


def test_submit_starts_the_workflow_with_the_derived_id(client):
    resp = client.post("/applications", json={"client_key": "acme-corp"})
    assert resp.status_code == 202
    started = client.fake.started[0]
    assert started["id"] == "onboarding-acme-corp"
    assert started["workflow"] == "OnboardingWorkflow"
    assert started["task_queue"] == "customer-onboarding"


def test_submit_sets_static_summary_and_details(client):
    """§12 — the workflow is labelled at start."""
    client.post("/applications", json={"client_key": "acme-corp"})
    kwargs = client.fake.started[0]["kwargs"]
    assert "Acme" in kwargs["static_summary"]
    assert kwargs["static_details"]


def test_duplicate_submit_returns_409_not_500(client):
    """§6.1 — this is the demonstration of the workflow-ID property, not an
    error path to hide."""
    client.post("/applications", json={"client_key": "acme-corp"})
    resp = client.post("/applications", json={"client_key": "acme-corp"})
    assert resp.status_code == 409
    assert "already in progress" in resp.json()["error"]


def test_duplicate_submit_409_for_the_typed_already_started_error(monkeypatch):
    """A real server raises WorkflowAlreadyStartedError, not a raw RPCError,
    whenever the ALREADY_EXISTS details unpack (temporalio client/_impl.py).
    The 409 must not depend on which of the two arrives."""
    from temporalio.exceptions import WorkflowAlreadyStartedError

    class Typed(FakeClient):
        async def start_workflow(self, workflow, arg, *, id, task_queue, **kw):
            raise WorkflowAlreadyStartedError(id, workflow, run_id="r1")

    tc = _client_for(Typed(), monkeypatch)
    resp = tc.post("/applications", json={"client_key": "acme-corp"})
    assert resp.status_code == 409
    assert "already in progress" in resp.json()["error"]


def test_status_proxies_the_query_by_string_name(client):
    resp = client.get("/api/status/acme-corp")
    assert resp.status_code == 200
    assert resp.json()["stage"] == "awaiting_review"
    assert ("query", "status") in client.fake.calls


def test_status_for_an_unstarted_workflow_is_404(client, monkeypatch):
    """The console polls every 2s from page load, before any application has
    been submitted (§13 step 7). Not-found is a state, not a server error."""
    from temporalio.service import RPCError, RPCStatusCode
    from web import gateway

    class Missing(FakeHandle):
        async def query(self, name, *args):
            raise RPCError("workflow not found", RPCStatusCode.NOT_FOUND, b"")

    monkeypatch.setattr(gateway, "_handle", lambda c, k: Missing([]))
    resp = client.get("/api/status/acme-corp")
    assert resp.status_code == 404
    assert "acme-corp" in resp.json()["error"]


def test_review_sends_the_update_by_string_name(client):
    body = {"decision": "approve", "analyst_id": "kyc-7", "note": None,
            "field_edits": [], "attested": True}
    resp = client.post("/api/review/acme-corp", json=body)
    assert resp.status_code == 200
    assert resp.json()["accepted"] is True
    assert client.fake.calls[-1][0] == "update"
    assert client.fake.calls[-1][1] == "submit_review"


def test_review_validator_rejection_becomes_422(client, monkeypatch):
    from web import gateway

    class Failing(FakeHandle):
        async def execute_update(self, name, arg):
            from temporalio.exceptions import ApplicationError
            raise ApplicationError("required field empty: beneficial_owners[1].dob")

    monkeypatch.setattr(gateway, "_handle", lambda c, k: Failing([]))
    resp = client.post("/api/review/acme-corp",
                       json={"decision": "approve", "analyst_id": "kyc-7",
                             "note": None, "field_edits": [], "attested": True})
    assert resp.status_code == 422
    assert "beneficial_owners[1].dob" in resp.json()["error"]


def test_review_422_carries_the_validator_message_not_the_wrapper(client,
                                                                 monkeypatch):
    """execute_update wraps the validator's ApplicationError in a
    WorkflowUpdateFailedError whose own str() is the useless 'Workflow update
    failed'. §6.1 requires the *validator's* rejection message."""
    from temporalio.client import WorkflowUpdateFailedError
    from web import gateway

    class Failing(FakeHandle):
        async def execute_update(self, name, arg):
            from temporalio.exceptions import ApplicationError
            raise WorkflowUpdateFailedError(
                ApplicationError("required field empty: beneficial_owners[1].dob"))

    monkeypatch.setattr(gateway, "_handle", lambda c, k: Failing([]))
    resp = client.post("/api/review/acme-corp",
                       json={"decision": "approve", "analyst_id": "kyc-7",
                             "note": None, "field_edits": [], "attested": True})
    assert resp.status_code == 422
    assert "beneficial_owners[1].dob" in resp.json()["error"]
    assert "Workflow update failed" != resp.json()["error"]


def test_client_id_callback_signals_the_workflow(client):
    body = {"client_key": "acme-corp", "client_id": "CL-ABC12345",
            "core_ref": "REQ-1", "assigned_at": "2026-09-04T10:00:00Z"}
    resp = client.post("/callbacks/client-id", json=body)
    assert resp.status_code == 202
    kind, name, arg = client.fake.calls[-1]
    assert (kind, name) == ("signal", "client_id_received")
    assert arg["client_id"] == "CL-ABC12345"


def test_control_writes_and_removes_the_llm_outage_flag(monkeypatch, tmp_path):
    """§10.4 — the toggle has to reach the *worker*, which is a different
    process, so it is a flag file rather than gateway memory."""
    monkeypatch.setenv("DOCUMENT_STORE", str(tmp_path / "store"))
    tc = _client_for(FakeClient(), monkeypatch)
    flag = tmp_path / ".llm_down"

    assert tc.post("/api/control", json={"llm_down": True}).json()["llm_down"] is True
    assert flag.exists()
    assert tc.post("/api/control", json={"llm_down": False}).json()["llm_down"] is False
    assert not flag.exists()


def test_gateway_imports_no_worker_code():
    """§20.1 — the gateway drives workflows by string name only."""
    source = (ROOT / "web" / "gateway.py").read_text()
    for banned in ("from python.workflows", "from python.activities",
                   "import python.workflows", "OnboardingWorkflow.run"):
        assert banned not in source
    # And prove it at runtime, not just by grep: importing the gateway must not
    # drag worker modules in transitively.
    probe = ("import sys, web.gateway; "
             "bad = [m for m in sys.modules "
             "if m.startswith(('python.workflows', 'python.activities'))]; "
             "assert not bad, bad")
    r = subprocess.run([sys.executable, "-c", probe], cwd=ROOT,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
