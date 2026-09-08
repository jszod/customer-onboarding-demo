"""The extraction agent child workflow. §8.1, T-CHILD-01/02/03.

The stubs here are hand-written, not recorded (§16.0): these tests pin the
loop's control flow, and a scripted sequence states the case under test in the
test itself. Fixtures are for `call_llm`'s own behaviour, not for this.
"""
import asyncio
import uuid

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from python import config
from python.models.application import ApplicationFields
from python.models.documents import DocumentManifest, DocumentRef
from python.models.extraction import (AgentTurn, DocumentRequest, Escalation,
                                      ExtractionRequest, ExtractionResult,
                                      ExtractionSubmission,
                                      FieldGap, LLMRequest, LLMResponse)
from python.workflows import extraction
from python.workflows.extraction import ExtractionAgentWorkflow


def _manifest() -> DocumentManifest:
    kinds = {"articles-of-incorporation": "articles_of_incorporation",
             "business-license": "business_license", "ein-letter": "ein_letter",
             "w9": "w9", "ownership-declaration": "ownership_declaration"}
    return DocumentManifest(refs=[
        DocumentRef(doc_id=d, kind=k, uri=f"acme-corp/1/{d}.pdf",
                    sha256="0" * 64, page_count=1) for d, k in kinds.items()])


def _request() -> ExtractionRequest:
    return ExtractionRequest(client_key="acme-corp", legal_name="Acme Holdings LLC",
                             manifest=_manifest(), attempt=1)


def _scripted(*responses: LLMResponse):
    """A stub, not a fixture (§16.0) — hand-written is correct here."""
    seen: list[LLMRequest] = []

    @activity.defn(name="call_llm")
    async def stub(req: LLMRequest) -> LLMResponse:
        seen.append(req)
        return responses[min(len(seen) - 1, len(responses) - 1)]

    return stub, seen


async def _run(stub, req: ExtractionRequest):
    queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_local(
            data_converter=config.build_data_converter()) as env:
        async with Worker(env.client, task_queue=queue,
                          workflows=[ExtractionAgentWorkflow], activities=[stub]):
            return await env.client.execute_workflow(
                "ExtractionAgentWorkflow", req, result_type=ExtractionResult,
                id=f"extract-{uuid.uuid4()}", task_queue=queue)


def _execute(stub, req: ExtractionRequest):
    """Sync entry point. The manifest wrappers (§16.8) are plain functions, so
    the loop is owned here and closed rather than leaked."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run(stub, req))
    finally:
        loop.close()


def _turn(text: str = "ok") -> AgentTurn:
    return AgentTurn(role="assistant", content=text)


def assert_falls_back_to_w9():
    """T-CHILD-01. The model asks for the EIN letter, cannot read tax_id, then
    asks for the W-9 and succeeds. The workflow must carry BOTH doc ids
    forward on the second call."""
    stub, seen = _scripted(
        LLMResponse(action=DocumentRequest(doc_ids=["ein-letter"],
                                           rationale="tax_id lives here"),
                    turn=_turn()),
        LLMResponse(action=DocumentRequest(doc_ids=["w9"],
                                           rationale="EIN letter illegible"),
                    turn=_turn()),
        LLMResponse(action=ExtractionSubmission(
            application=ApplicationFields(legal_name="Acme Holdings LLC",
                                          tax_id="88-1234567"), gaps=[]),
            turn=_turn()),
    )
    result = _execute(stub, _request())
    assert result.escalated is False
    assert result.application.tax_id == "88-1234567"
    assert result.iterations == 3
    assert seen[0].requested_doc_ids == []
    assert seen[1].requested_doc_ids == ["ein-letter"]
    assert seen[2].requested_doc_ids == ["ein-letter", "w9"], \
        "requested docs must accumulate, not be replaced"


def assert_escalates_with_provenance():
    """T-CHILD-02. Escalation is a RETURN VALUE, not an exception (§8.2)."""
    gap = FieldGap(field_path="beneficial_owners[1].dob",
                   reason="not stated in any document",
                   documents_searched=["ownership_declaration", "w9"])
    stub, _ = _scripted(LLMResponse(action=Escalation(gaps=[gap]), turn=_turn()))
    result = _execute(stub, _request())
    assert result.escalated is True
    assert result.gaps[0].field_path == "beneficial_owners[1].dob"
    assert "ownership_declaration" in result.gaps[0].documents_searched


def assert_cap_escalates():
    """T-CHILD-03. Hitting MAX_ITERATIONS escalates; it does not raise."""
    stub, seen = _scripted(LLMResponse(
        action=DocumentRequest(doc_ids=["w9"], rationale="again"), turn=_turn()))
    result = _execute(stub, _request())
    assert result.escalated is True
    assert result.iterations == config.settings().max_iterations
    assert len(seen) == config.settings().max_iterations


def test_escalation_carries_the_partial_application_through():
    """§8.4's beat lands on the review console, so the analyst has to see what
    the agent DID read. Returning an empty application here would blank every
    extracted field and leave nothing for their gap edits to address --
    `beneficial_owners[1].dob` needs owner 1 to exist."""
    from datetime import date

    from python.models.application import BeneficialOwner

    partial = ApplicationFields(
        legal_name="Acme Holdings LLC", tax_id="88-1234567",
        beneficial_owners=[BeneficialOwner(full_name="Dana Reyes",
                                           dob=date(1979, 3, 2)),
                           BeneficialOwner(full_name="Sam Okafor")])
    gap = FieldGap(field_path="beneficial_owners[1].dob",
                   reason="not stated in any document",
                   documents_searched=["ownership_declaration"])
    stub, _ = _scripted(LLMResponse(
        action=Escalation(application=partial, gaps=[gap]), turn=_turn()))
    result = _execute(stub, _request())

    assert result.escalated is True
    assert result.application.legal_name == "Acme Holdings LLC"
    assert result.application.tax_id == "88-1234567"
    assert len(result.application.beneficial_owners) == 2, \
        "the gap names owner 1 -- an empty application makes that edit impossible"
    assert result.application.beneficial_owners[1].full_name == "Sam Okafor"


def test_escalation_without_an_application_is_still_a_clean_result():
    """The field is optional, so a response that omits it must not crash."""
    stub, _ = _scripted(LLMResponse(action=Escalation(gaps=[]), turn=_turn()))
    result = _execute(stub, _request())
    assert result.escalated is True
    assert result.application == ApplicationFields()


def test_the_iteration_cap_says_why_it_escalated():
    """The console drives off `gaps`. Escalating with an empty list presents a
    blank form with nothing flagged and no explanation."""
    stub, _ = _scripted(LLMResponse(
        action=DocumentRequest(doc_ids=["w9"], rationale="again"), turn=_turn()))
    result = _execute(stub, _request())
    assert result.escalated is True
    assert result.gaps, "the cap must explain itself"
    assert "cap" in result.gaps[0].reason


def test_unknown_doc_id_is_a_tool_error_not_an_exception():
    """§8.1 — validation against the in-state manifest is a pure check; an
    unknown id returns an error to the model."""
    stub, seen = _scripted(
        LLMResponse(action=DocumentRequest(doc_ids=["not-a-document"],
                                           rationale="guessing"), turn=_turn()),
        LLMResponse(action=Escalation(gaps=[]), turn=_turn()))
    result = _execute(stub, _request())
    assert result.escalated is True
    assert any("unknown" in t.content.lower() for t in seen[1].turns)


def test_a_successful_document_request_is_recorded_as_a_tool_turn():
    """The transcript must never end on an assistant turn. `call_llm` maps an
    assistant turn to an assistant message, and an assistant message in last
    position is an assistant PREFILL -- removed on Sonnet 5 and every 4.6+
    model, which reject it with a 400 (`This model does not support assistant
    message prefill`). Every non-terminal tool therefore records its result,
    and the ONLY reason the unknown-id path above did so was that it had an
    error to report.

    Ids only, never text: §8.2 keeps document content out of history, and the
    activity re-renders the requested documents into the user message anyway.
    """
    stub, seen = _scripted(
        LLMResponse(action=DocumentRequest(doc_ids=["ein-letter"],
                                           rationale="tax id"), turn=_turn()),
        LLMResponse(action=Escalation(gaps=[]), turn=_turn()))
    _execute(stub, _request())
    assert seen[1].turns[-1].role == "tool"
    assert "ein-letter" in seen[1].turns[-1].content


def test_the_tool_turn_reports_granted_and_unknown_ids_together():
    """One request can be partly valid. Both halves are reported, so the model
    learns which ids it may not ask for again."""
    turn = extraction.document_tool_turn(["ein-letter", "nope"],
                                         {"ein-letter", "w9"})
    assert turn.role == "tool"
    assert "now readable: ein-letter" in turn.content
    assert "unknown document ids: nope" in turn.content
    assert "w9" in turn.content              # what IS available


def test_the_tool_turn_is_never_empty():
    """An empty `doc_ids` would render an empty content block, which the API
    rejects for the same reason it rejects the prefill -- a different 400 on
    the same call."""
    assert extraction.document_tool_turn([], {"w9"}).content.strip()


def test_child_has_exactly_one_activity():
    """§8.1 — every tool is inline; only call_llm is an activity."""
    source = open("python/workflows/extraction.py").read()
    assert source.count("execute_activity") == 1
