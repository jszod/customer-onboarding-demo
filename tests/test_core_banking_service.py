"""§11 — the fake core banking system.

The ledger is the thing the workflow cannot see: it is the proof surface for
"exactly one account" after an ambiguous timeout (§10.1).
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CORE_LEDGER_PATH", str(tmp_path / "ledger.db"))
    monkeypatch.setenv("CORE_SLOW_MS", "0")          # fast in tests
    from core_banking.app import build_app
    return TestClient(build_app())


def _req(key: str = "onboarding-acme-corp") -> dict:
    return {"idempotency_key": key,
            "application": {"legal_name": "Acme Holdings LLC", "tax_id": "88-1234567"}}


def test_first_call_accepts_and_creates_one_account(client):
    body = client.post("/accounts", json=_req()).json()
    assert body["status"] == "accepted"
    assert len(client.get("/ledger").json()["accounts"]) == 1


def test_same_key_returns_duplicate_with_the_original_request_id(client):
    first = client.post("/accounts", json=_req()).json()
    second = client.post("/accounts", json=_req()).json()
    assert second["status"] == "duplicate"
    assert second["request_id"] == first["request_id"]


def test_duplicate_does_not_create_a_second_account(client):
    """The proof surface for the headline (§10.1)."""
    for _ in range(5):
        client.post("/accounts", json=_req())
    assert len(client.get("/ledger").json()["accounts"]) == 1


def test_different_keys_create_different_accounts(client):
    client.post("/accounts", json=_req("onboarding-acme-corp"))
    client.post("/accounts", json=_req("onboarding-globex"))
    assert len(client.get("/ledger").json()["accounts"]) == 2


def test_slow_first_call_is_on_by_default(tmp_path, monkeypatch):
    """§10.1 — slow-first-call is the default so the beat happens every run."""
    monkeypatch.setenv("CORE_LEDGER_PATH", str(tmp_path / "l.db"))
    monkeypatch.delenv("CORE_SLOW_MS", raising=False)
    from core_banking.app import build_app
    app = build_app()
    assert app.state.slow_first_call is True
    assert app.state.slow_ms == 10000


def test_control_endpoint_can_disable_slow_first_call(client):
    client.post("/control", json={"slow_first_call": False})
    assert client.get("/ledger").json()["slow_first_call"] is False


def test_forced_rejection_returns_a_business_400(client):
    client.post("/control", json={"reject_next": True})
    resp = client.post("/accounts", json=_req())
    assert resp.status_code == 400
    assert "reject" in resp.json()["detail"].lower()


def test_assign_posts_the_client_id_to_the_gateway_callback(client, monkeypatch):
    sent = {}

    def fake_post(url, json, timeout):
        sent["url"], sent["json"] = url, json
        class R:
            status_code = 202
        return R()

    monkeypatch.setattr("core_banking.app.httpx.post", fake_post)
    request_id = client.post("/accounts", json=_req()).json()["request_id"]
    client.post(f"/accounts/{request_id}/assign")
    assert sent["url"].endswith("/callbacks/client-id")
    assert sent["json"]["client_key"] == "acme-corp"
    assert sent["json"]["client_id"].startswith("CL-")


def test_service_never_imports_temporalio():
    """§20.1 — this is the strongest independence case in the design."""
    import core_banking.app as mod
    source = (open(mod.__file__).read()
              + open(mod.__file__.replace("app.py", "ledger.py")).read())
    assert "temporalio" not in source


def test_no_module_in_the_package_imports_temporalio_or_the_worker():
    """The substring check above is only as good as the files it reads.

    This one parses every module in the package and looks at import statements
    specifically, so an indirect route in -- importing the worker's models, say
    -- is caught too. If this service could reach the SDK, the demo's claim
    that idempotency is enforced *outside* Temporal would be circular (§20.1).
    """
    import ast
    import pathlib

    import core_banking

    package_dir = pathlib.Path(core_banking.__file__).parent
    forbidden = ("temporalio", "python")
    offenders = []
    for path in sorted(package_dir.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name.split(".")[0] in forbidden:
                    offenders.append(f"{path.name}: {name}")
    assert offenders == []
