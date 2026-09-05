"""`call_llm` — T-ACT-02. Spec §8.1, §8.2, §8.3, §10.2, §10.4.

Every test here runs against a stubbed client or a fixture file: nothing in
this module makes a real API call, and no API key is required.

The three `assert_*` helpers are module-level and take no arguments on
purpose — `tests/test_manifest.py`'s `T-ACT-02` scenario delegates into them,
so the manifest scenario and the unit tests assert the same thing rather than
drifting apart.
"""
from __future__ import annotations

import asyncio
import json
import unittest.mock as m
from pathlib import Path

import anthropic

# The anthropic SDK is 1.x, which is built on httpx2 rather than httpx: its
# error classes are typed `response: httpx2.Response`. Constructing the
# fixtures from the `httpx` package would be a different type than the SDK
# hands the activity in production.
import httpx2
import pytest
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from python.activities import llm
from python.models.documents import DocumentManifest, DocumentRef
from python.models.extraction import (AgentTurn, DocumentRequest, Escalation,
                                      ExtractionSubmission, LLMRequest)


def _request(**overrides) -> LLMRequest:
    base = dict(model="claude-sonnet-5",
                manifest=DocumentManifest(refs=[]),
                requested_doc_ids=[], turns=[],
                required_field_paths=["tax_id"])
    base.update(overrides)
    return LLMRequest(**base)


def _raise(exc):
    def _boom(*_a, **_k):
        raise exc
    return _boom


def _run(coro_fn, req):
    return asyncio.run(ActivityEnvironment().run(coro_fn, req))


def _run_expecting(exc) -> ApplicationError:
    # The outage flag is ambient demo state (§10.4). Pin it off so the three
    # helpers below classify the injected API error and nothing else — they are
    # called from the manifest, where no fixture has cleaned the repo root.
    with m.patch.object(llm, "_llm_down_flag",
                        lambda: Path("/nonexistent/.llm_down")):
        with m.patch.object(llm, "_create_message", _raise(exc)):
            with pytest.raises(ApplicationError) as ei:
                _run(llm.live_call_llm, _request())
    return ei.value


def _resp(status: int) -> httpx2.Response:
    return httpx2.Response(status, request=httpx2.Request("POST", "http://x"))


# --------------------------------------------------------------------------
# §10.2 error classification — the three assertions T-ACT-02 delegates into.
# Classification lives INSIDE the activity, never in `non_retryable_error_types`
# at the call site.
# --------------------------------------------------------------------------

def assert_401_non_retryable() -> None:
    err = _run_expecting(anthropic.AuthenticationError(
        message="bad key", response=_resp(401), body=None))
    assert err.non_retryable is True, "401 must not be retried"
    assert err.type == "AuthenticationError"


def assert_429_sets_retry_delay() -> None:
    resp = _resp(429)
    resp.headers["retry-after"] = "42"
    err = _run_expecting(anthropic.RateLimitError(
        message="slow down", response=resp, body=None))
    assert err.non_retryable is False, "429 is retryable"
    assert err.type == "RateLimitError"
    assert err.next_retry_delay is not None, "429 must set next_retry_delay"
    assert err.next_retry_delay.total_seconds() == 42


def assert_5xx_retryable() -> None:
    err = _run_expecting(anthropic.InternalServerError(
        message="upstream", response=_resp(503), body=None))
    assert err.non_retryable is False, "5xx is retryable"
    assert err.type == "ServerError"


def test_401_is_non_retryable():
    assert_401_non_retryable()


def test_429_sets_next_retry_delay_from_the_header():
    assert_429_sets_retry_delay()


def test_5xx_is_retryable():
    assert_5xx_retryable()


def test_429_without_a_header_still_sets_a_delay():
    err = _run_expecting(anthropic.RateLimitError(
        message="slow down", response=_resp(429), body=None))
    assert err.non_retryable is False
    assert err.next_retry_delay is not None


def test_400_is_non_retryable():
    """§10.2 — invalid input is a client error; retrying cannot help."""
    err = _run_expecting(anthropic.BadRequestError(
        message="invalid input", response=_resp(400), body=None))
    assert err.non_retryable is True
    assert err.type == "ClientError"


def test_connection_errors_are_retryable():
    err = _run_expecting(anthropic.APIConnectionError(
        request=httpx2.Request("POST", "http://x")))
    assert err.non_retryable is False
    assert err.type == "ConnectionError"


# --------------------------------------------------------------------------
# §8.3 client configuration
# --------------------------------------------------------------------------

def test_client_retries_are_disabled():
    """§8.3 — Temporal owns all retry behaviour."""
    assert llm._client().max_retries == 0


# --------------------------------------------------------------------------
# §8.3 coercion — the activity returns VALIDATED models
# --------------------------------------------------------------------------

class _Block:
    type = "tool_use"

    def __init__(self, name, payload):
        self.name = name
        self.input = payload


class _Usage:
    input_tokens = 11
    output_tokens = 7


class _Message:
    def __init__(self, blocks):
        self.content = blocks
        self.usage = _Usage()


def _reply(name, payload):
    return lambda *_a, **_k: _Message([_Block(name, payload)])


def _address(line1: str) -> dict:
    return {"line1": line1, "city": "Dover", "state": "DE",
            "postal_code": "19901", "country": "US"}


def _application() -> dict:
    return {
        "legal_name": "Acme Corp", "entity_type": "LLC",
        "formation_date": "2019-04-01", "formation_state": "DE",
        "tax_id": "12-3456789",
        "registered_address": _address("1 Main St"),
        "business_address": _address("1 Main St"),
        "industry_code": "5411",
        "beneficial_owners": [{
            "full_name": "Dana Reyes", "dob": "1980-02-03",
            "ownership_pct": "51.0",
            "residential_address": _address("2 Oak Ave"),
            "id_type": "passport", "id_number": "X1234567"}],
        "control_person": {
            "full_name": "Dana Reyes", "title": "CEO", "dob": "1980-02-03",
            "residential_address": _address("2 Oak Ave"),
            "id_type": "passport", "id_number": "X1234567"},
    }


def test_request_documents_is_returned_as_a_validated_model():
    with m.patch.object(llm, "_create_message", _reply(
            "request_documents",
            {"doc_ids": ["ein-letter"], "rationale": "tax_id lives there"})):
        out = _run(llm.live_call_llm, _request())
    assert isinstance(out.action, DocumentRequest)
    assert out.action.kind == "request_documents"
    assert out.action.doc_ids == ["ein-letter"]
    assert out.turn.role == "assistant"
    assert out.usage == {"input_tokens": 11, "output_tokens": 7}


def test_submit_extraction_is_coerced_into_application_fields():
    """§8.3 — dates and decimals are coerced HERE, not in the workflow."""
    from datetime import date
    from decimal import Decimal

    with m.patch.object(llm, "_create_message", _reply(
            "submit_extraction",
            {"application": _application(), "gaps": []})):
        out = _run(llm.live_call_llm, _request())
    assert isinstance(out.action, ExtractionSubmission)
    assert out.action.application.formation_date == date(2019, 4, 1)
    assert out.action.application.beneficial_owners[0].dob == date(1980, 2, 3)
    assert out.action.application.beneficial_owners[0].ownership_pct == Decimal("51.0")


def test_escalate_is_returned_as_a_validated_model():
    with m.patch.object(llm, "_create_message", _reply(
            "escalate",
            {"gaps": [{"field_path": "beneficial_owners[0].dob",
                       "reason": "absent from every document",
                       "documents_searched": ["ownership-declaration"]}]})):
        out = _run(llm.live_call_llm, _request())
    assert isinstance(out.action, Escalation)
    assert out.action.gaps[0].field_path == "beneficial_owners[0].dob"


def test_malformed_tool_input_is_a_retryable_failure():
    """§8.3 — malformed model output is a retryable ACTIVITY failure, never an
    exception raised in workflow code."""
    with m.patch.object(llm, "_create_message", _reply(
            "request_documents", {"rationale": "no doc_ids at all"})):
        with pytest.raises(ApplicationError) as ei:
            _run(llm.live_call_llm, _request())
    assert ei.value.non_retryable is False
    assert ei.value.type == "MalformedResponse"


def test_no_tool_call_is_a_retryable_failure():
    with m.patch.object(llm, "_create_message", lambda *_a, **_k: _Message([])):
        with pytest.raises(ApplicationError) as ei:
            _run(llm.live_call_llm, _request())
    assert ei.value.non_retryable is False
    assert ei.value.type == "MalformedResponse"


def test_an_unknown_tool_name_is_a_retryable_failure():
    with m.patch.object(llm, "_create_message", _reply("delete_everything", {})):
        with pytest.raises(ApplicationError) as ei:
            _run(llm.live_call_llm, _request())
    assert ei.value.type == "MalformedResponse"


# --------------------------------------------------------------------------
# §8.1 / §8.2 — documents are resolved INSIDE the activity
# --------------------------------------------------------------------------

def _write_pdf(path: Path) -> None:
    """A real, readable single-page PDF. The text layer is irrelevant here —
    what matters is that the activity opens the file itself."""
    from pypdf import PdfWriter
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with path.open("wb") as fh:
        writer.write(fh)


def test_the_activity_resolves_requested_docs_from_the_store(tmp_path, monkeypatch):
    """§8.1, §8.2 — LLMRequest carries ids; the activity reads the bytes."""
    store = tmp_path / "store"
    monkeypatch.setenv("DOCUMENT_STORE", str(store))
    pdf = store / "acme-corp/1/ein-letter.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    _write_pdf(pdf)

    seen = {}

    def _capture(**kwargs):
        seen.update(kwargs)
        return _Message([_Block("escalate", {"gaps": []})])

    req = _request(
        manifest=DocumentManifest(refs=[DocumentRef(
            doc_id="ein-letter", kind="ein_letter",
            uri="acme-corp/1/ein-letter.pdf", sha256="0" * 64, page_count=1)]),
        requested_doc_ids=["ein-letter"])

    with m.patch.object(llm, "_create_message", _capture):
        _run(llm.live_call_llm, req)

    prompt = seen["messages"][0]["content"]
    assert "ein-letter" in prompt
    assert "ein_letter" in prompt


def test_an_unknown_doc_id_does_not_raise(tmp_path, monkeypatch):
    """§19.2 in spirit — an id outside the manifest is reported to the model,
    not raised. The manifest check is the workflow's job (§8.1)."""
    monkeypatch.setenv("DOCUMENT_STORE", str(tmp_path / "store"))
    with m.patch.object(llm, "_create_message",
                        _reply("escalate", {"gaps": []})):
        out = _run(llm.live_call_llm,
                   _request(requested_doc_ids=["not-in-the-manifest"]))
    assert isinstance(out.action, Escalation)


def test_activity_reads_documents_itself():
    """§8.1 — document text is resolved INSIDE the activity, never passed in."""
    source = Path(llm.__file__).read_text()
    assert "PdfReader" in source or "extract_text" in source
    assert "requested_doc_ids" in source


def test_prior_gaps_and_the_analyst_note_reach_the_prompt():
    from python.models.extraction import FieldGap
    seen = {}

    def _capture(**kwargs):
        seen.update(kwargs)
        return _Message([_Block("escalate", {"gaps": []})])

    req = _request(
        prior_gaps=[FieldGap(field_path="beneficial_owners[0].dob",
                             reason="not in any document")],
        analyst_note="the DOB is on the passport scan",
        turns=[AgentTurn(role="assistant", content="I looked at the W-9")])
    with m.patch.object(llm, "_create_message", _capture):
        _run(llm.live_call_llm, req)

    prompt = seen["messages"][0]["content"]
    assert "beneficial_owners[0].dob" in prompt
    assert "the DOB is on the passport scan" in prompt
    assert seen["messages"][1]["role"] == "assistant"
    assert seen["max_tokens"] == 4096
    assert seen["model"] == "claude-sonnet-5"


# --------------------------------------------------------------------------
# §10.4 — the LLM-outage toggle. The gateway writes the flag; this is the
# reader half. The two halves must name the SAME path.
# --------------------------------------------------------------------------

def test_the_outage_flag_path_matches_the_one_the_gateway_writes(tmp_path,
                                                                 monkeypatch):
    from web import gateway
    monkeypatch.setenv("DOCUMENT_STORE", str(tmp_path / "store"))
    assert llm._llm_down_flag() == gateway._llm_down_flag()


def test_the_outage_toggle_makes_call_llm_fail_retryably(tmp_path, monkeypatch):
    """§10.4 — the agent loop visibly retries and resumes, so the failure must
    be RETRYABLE. A non-retryable one would end the demo beat, not stage it."""
    monkeypatch.setenv("DOCUMENT_STORE", str(tmp_path / "store"))
    (tmp_path / ".llm_down").write_text("toggled from the console\n")

    def _must_not_be_called(*_a, **_k):  # pragma: no cover
        raise AssertionError("the outage check must short-circuit the API call")

    with m.patch.object(llm, "_create_message", _must_not_be_called):
        with pytest.raises(ApplicationError) as ei:
            _run(llm.live_call_llm, _request())
    assert ei.value.non_retryable is False
    assert ei.value.type == "LLMOutage"


def test_clearing_the_flag_restores_the_activity(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCUMENT_STORE", str(tmp_path / "store"))
    flag = tmp_path / ".llm_down"
    flag.write_text("down\n")
    flag.unlink()
    with m.patch.object(llm, "_create_message",
                        _reply("escalate", {"gaps": []})):
        out = _run(llm.live_call_llm, _request())
    assert isinstance(out.action, Escalation)


# --------------------------------------------------------------------------
# §16.0, §16.7 — fixture mode
# --------------------------------------------------------------------------

def test_fixture_mode_returns_the_recorded_sequence(tmp_path, monkeypatch):
    monkeypatch.setenv("FIXTURE_DIR", str(tmp_path))
    (tmp_path / "acme-corp.json").write_text(json.dumps([
        {"action": {"kind": "request_documents", "doc_ids": ["ein-letter"],
                    "rationale": "tax_id lives in the EIN letter"},
         "turn": {"role": "assistant", "content": "reading the EIN letter"},
         "usage": {}}]))
    req = _request(manifest=DocumentManifest(refs=[DocumentRef(
        doc_id="ein-letter", kind="ein_letter",
        uri="acme-corp/1/ein-letter.pdf", sha256="0" * 64, page_count=1)]))
    out = _run(llm.fixture_call_llm, req)
    assert isinstance(out.action, DocumentRequest)
    assert out.action.doc_ids == ["ein-letter"]


def test_fixture_mode_advances_with_the_turn_count(tmp_path, monkeypatch):
    monkeypatch.setenv("FIXTURE_DIR", str(tmp_path))
    (tmp_path / "acme-corp.json").write_text(json.dumps([
        {"action": {"kind": "request_documents", "doc_ids": ["ein-letter"],
                    "rationale": "first"},
         "turn": {"role": "assistant", "content": "first"}, "usage": {}},
        {"action": {"kind": "escalate", "gaps": []},
         "turn": {"role": "assistant", "content": "second"}, "usage": {}}]))
    req = _request(turns=[AgentTurn(role="assistant", content="first")])
    out = _run(llm.fixture_call_llm, req)
    assert isinstance(out.action, Escalation)


def test_fixture_mode_makes_no_api_call(tmp_path, monkeypatch):
    monkeypatch.setenv("FIXTURE_DIR", str(tmp_path))
    (tmp_path / "acme-corp.json").write_text(json.dumps([
        {"action": {"kind": "escalate", "gaps": []},
         "turn": {"role": "assistant", "content": "x"}, "usage": {}}]))

    def _must_not_be_called(*_a, **_k):  # pragma: no cover
        raise AssertionError("fixture mode must never touch the network")

    with m.patch.object(llm, "_create_message", _must_not_be_called):
        _run(llm.fixture_call_llm, _request())


def test_missing_fixtures_is_non_retryable(tmp_path, monkeypatch):
    """Retrying cannot conjure a fixture file; §10.2 says say so."""
    monkeypatch.setenv("FIXTURE_DIR", str(tmp_path / "nope"))
    with pytest.raises(ApplicationError) as ei:
        _run(llm.fixture_call_llm, _request())
    assert ei.value.non_retryable is True
    assert ei.value.type == "FixturesMissing"


def test_both_implementations_register_under_one_activity_name():
    """§8.3 — the worker picks one at startup; the workflow never branches."""
    from temporalio import activity
    for fn in (llm.live_call_llm, llm.fixture_call_llm):
        assert activity._Definition.must_from_callable(fn).name == "call_llm"


# --------------------------------------------------------------------------
# Defects found reviewing the activities — see docs/RULINGS.md R-018
# --------------------------------------------------------------------------

def test_absent_credentials_are_classified_not_retried():
    """With no key resolvable the SDK constructs fine and then raises a BARE
    TypeError from `messages.create` — not an `anthropic` error, so it misses
    every clause in the classification chain, escapes, and retries forever on
    the default policy. A missing env var must not present as a hung workflow."""
    boom = TypeError(
        "Could not resolve authentication method. Expected one of api_key, "
        "auth_token, or credentials to be set.")
    err = _run_expecting(boom)
    assert err.non_retryable is True, "no retry can conjure a credential"
    assert err.type == "AuthenticationError"
    assert "FIXTURE_MODE" in str(err), "say how to run without a key (§16.7)"


def test_an_unrelated_type_error_is_not_swallowed():
    """The clause is narrow on purpose: a genuine bug in the call must still
    surface as itself rather than being relabelled a credentials problem."""
    with m.patch.object(llm, "_llm_down_flag",
                        lambda: Path("/nonexistent/.llm_down")):
        with m.patch.object(llm, "_create_message",
                            _raise(TypeError("unexpected keyword 'modle'"))):
            with pytest.raises(TypeError):
                _run(llm.live_call_llm, _request())


def test_the_model_call_does_not_run_on_the_event_loop():
    """The Anthropic client is synchronous and can hold a socket for
    `_CLIENT_TIMEOUT_SECONDS`. On the event loop it stalls every other
    activity on the worker, its workflow tasks, and its heartbeats (R-009)."""
    import threading
    ran_on = {}

    def _record(**_k):
        ran_on["thread"] = threading.current_thread()
        raise anthropic.APIConnectionError(request=httpx2.Request("POST", "http://x"))

    with m.patch.object(llm, "_llm_down_flag",
                        lambda: Path("/nonexistent/.llm_down")):
        with m.patch.object(llm, "_create_message", _record):
            with pytest.raises(ApplicationError):
                _run(llm.live_call_llm, _request())

    assert ran_on["thread"] is not threading.main_thread(), \
        "the blocking client must be handed to a worker thread"


def test_an_empty_fixture_file_is_non_retryable(tmp_path, monkeypatch):
    """`min(len(turns), len(sequence) - 1)` is -1 on an empty file, which
    indexes the empty list and raises IndexError — unclassified, so it retries
    forever rather than saying what is wrong."""
    monkeypatch.setenv("FIXTURE_DIR", str(tmp_path))
    (tmp_path / "acme-corp.json").write_text("[]")
    with pytest.raises(ApplicationError) as ei:
        _run(llm.fixture_call_llm, _request())
    assert ei.value.non_retryable is True
    assert ei.value.type == "FixturesMissing"


def test_running_past_the_recording_says_so(tmp_path, monkeypatch):
    """Clamping to the last entry replays one response forever, which presents
    as the agent looping to its iteration cap for no visible reason."""
    monkeypatch.setenv("FIXTURE_DIR", str(tmp_path))
    (tmp_path / "acme-corp.json").write_text(json.dumps([
        {"action": {"kind": "request_documents", "doc_ids": ["ein-letter"],
                    "rationale": "first"},
         "turn": {"role": "assistant", "content": "first"}, "usage": {}}]))
    req = _request(turns=[AgentTurn(role="assistant", content="first"),
                          AgentTurn(role="assistant", content="second")])
    with pytest.raises(ApplicationError) as ei:
        _run(llm.fixture_call_llm, req)
    assert ei.value.non_retryable is True
    assert ei.value.type == "FixturesExhausted"
