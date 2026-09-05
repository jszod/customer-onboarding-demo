"""§10.1 — the ambiguous timeout, and the key that resolves it.

The whole demo rests on one property: the idempotency key handed to core
banking is the PARENT WORKFLOW ID, arriving on the request and identical on
every retry. If it varied per retry the second call would open a second
account and the headline claim would be false, so this module asserts the
property three ways — behaviourally (a repeat call comes back `duplicate`
carrying the ORIGINAL request id), structurally (the ledger holds exactly one
row), and by reading the activity's own source for the trap §10.1 names.

The service runs in-process over an ASGI transport, against a ledger in a
tmp_path — never the repo's `core_banking/ledger.db`.
"""
from __future__ import annotations

import asyncio
import os
import re
import tempfile
import unittest.mock as mock
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from python.activities.core_banking import open_account
from python.models.application import ApplicationFields
from python.models.core_banking import OpenAccountAck, OpenAccountRequest

KEY = "onboarding-acme-corp"
ACTIVITY_SOURCE = Path(__file__).resolve().parents[1] / "python" / "activities" / "core_banking.py"


@contextmanager
def _ledger_env(directory: Path):
    """Point the ledger at a throwaway file; answer instantly.

    `core_banking.ledger` reads CORE_LEDGER_PATH on every call, so this has to
    stay in force for the duration of the calls, not just the build.
    """
    saved = {k: os.environ.get(k) for k in ("CORE_LEDGER_PATH", "CORE_SLOW_MS")}
    os.environ["CORE_LEDGER_PATH"] = str(Path(directory) / "ledger.db")
    os.environ["CORE_SLOW_MS"] = "0"
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _serve():
    """The real service, in-process. Call inside `_ledger_env`."""
    from core_banking.app import build_app

    return build_app()


def _request(key: str = KEY) -> OpenAccountRequest:
    return OpenAccountRequest(
        idempotency_key=key,
        application=ApplicationFields(legal_name="Acme Holdings LLC",
                                      tax_id="88-1234567"))


def _run(transport: httpx.BaseTransport, req: OpenAccountRequest) -> OpenAccountAck:
    """Run the activity with its HTTP client bound to `transport`.

    `python.activities.core_banking.httpx` IS the httpx module, so the patch
    below replaces `httpx.AsyncClient` globally for its duration — the real
    class has to be captured first or the factory calls itself.
    """
    real_client = httpx.AsyncClient

    def client_factory(*_a, **_k):
        return real_client(transport=transport, base_url="http://core")

    with mock.patch("python.activities.core_banking.httpx.AsyncClient",
                    client_factory):
        return asyncio.run(ActivityEnvironment().run(open_account, req))


def _call(app, key: str = KEY) -> OpenAccountAck:
    return _run(httpx.ASGITransport(app=app), _request(key))


def assert_second_call_is_duplicate() -> None:
    """T-ACT-03. Two calls, one key: the second is `duplicate`, same request id.

    Deliberately callable with no arguments so `tests/test_manifest.py` can
    delegate the scenario here.
    """
    with tempfile.TemporaryDirectory() as directory:
        with _ledger_env(Path(directory)):
            from core_banking import ledger

            app = _serve()
            first = _call(app)
            second = _call(app)

            assert first.status == "accepted", first
            assert second.status == "duplicate", second
            assert second.request_id == first.request_id, (first, second)
            accounts = ledger.all_accounts()
            assert len(accounts) == 1, accounts


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("CORE_LEDGER_PATH", str(tmp_path / "ledger.db"))
    monkeypatch.setenv("CORE_SLOW_MS", "0")
    from core_banking.app import build_app

    return build_app()


def test_second_call_with_the_same_key_is_a_duplicate():
    """The scenario the manifest delegates here, run under pytest too."""
    assert_second_call_is_duplicate()


def test_the_duplicate_ack_is_returned_not_raised(app):
    """`duplicate` is the proof the key worked, not an error to retry past."""
    _call(app)
    second = _call(app)
    assert isinstance(second, OpenAccountAck)
    assert second.status == "duplicate"


def test_repeated_retries_still_open_exactly_one_account(app):
    """The proof surface for §10.1: five retries, one account."""
    from core_banking import ledger

    request_ids = {_call(app).request_id for _ in range(5)}
    assert len(request_ids) == 1
    assert len(ledger.all_accounts()) == 1


def test_different_clients_get_different_accounts(app):
    from core_banking import ledger

    _call(app, "onboarding-acme-corp")
    _call(app, "onboarding-globex")
    assert len(ledger.all_accounts()) == 2


def test_business_rejection_is_non_retryable(app):
    """§10.2 — a core rejection must not be retried forever."""
    TestClient(app).post("/control", json={"reject_next": True})
    with pytest.raises(ApplicationError) as ei:
        _call(app)
    assert ei.value.non_retryable is True
    assert ei.value.type == "CoreRejection"


def test_a_rejection_opens_no_account(app):
    """§10.3 — the rejection ends the process, it does not half-open an account."""
    from core_banking import ledger

    TestClient(app).post("/control", json={"reject_next": True})
    with pytest.raises(ApplicationError):
        _call(app)
    assert ledger.all_accounts() == []


def test_server_error_stays_retryable():
    """§10.2 — 5xx is Temporal's to retry."""
    transport = httpx.MockTransport(lambda _r: httpx.Response(503, text="down"))
    with pytest.raises(ApplicationError) as ei:
        _run(transport, _request())
    assert ei.value.type == "ServerError"
    assert ei.value.non_retryable is False


def test_connection_failure_stays_retryable():
    """An unreachable core is transient; the activity must not give up on it."""

    def unreachable(_request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(ApplicationError) as ei:
        _run(httpx.MockTransport(unreachable), _request())
    assert ei.value.type == "ConnectionError"
    assert ei.value.non_retryable is False


def test_the_key_travels_on_the_wire_exactly_as_it_arrived():
    """The activity must forward the caller's key verbatim — no decoration."""
    seen: list[dict] = []

    def record(request: httpx.Request) -> httpx.Response:
        import json

        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"request_id": "REQ-1", "status": "accepted"})

    _run(httpx.MockTransport(record), _request("onboarding-acme-corp"))
    assert seen[0]["idempotency_key"] == "onboarding-acme-corp"
    assert seen[0]["application"]["legal_name"] == "Acme Holdings LLC"


def test_the_http_client_outlives_the_activity_timeout():
    """§10.1 — the activity's 5s start_to_close firing does NOT stop the call.

    A client timeout at or under 5s would cancel the HTTP request and destroy
    the ambiguity the demo exists to teach.
    """
    source = ACTIVITY_SOURCE.read_text()
    timeouts = [float(t) for t in re.findall(r"timeout=([0-9.]+)", source)]
    assert timeouts, "the HTTP client must set an explicit timeout"
    assert all(t > 5.0 for t in timeouts), timeouts


def test_key_is_never_derived_from_the_attempt_number():
    """§10.1's stated trap. Deriving from the SDK's per-retry counter defeats
    the whole mechanism, so the word does not appear in the module at all."""
    source = ACTIVITY_SOURCE.read_text()
    assert "info().attempt" not in source
    assert "attempt" not in source.lower()
    assert "attempt" not in source.split("idempotency_key")[1][:200]
