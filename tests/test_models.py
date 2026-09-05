from python.models.extraction import (DocumentRequest, Escalation, ExtractionSubmission,
                                      LLMResponse, AgentTurn)
from python.models.onboarding import OnboardingStatus


def test_llm_response_action_discriminates_on_kind():
    """§5.3.1 — the workflow dispatches on action.kind and never parses."""
    raw = {"action": {"kind": "request_documents", "doc_ids": ["w9"],
                      "rationale": "tax_id not in ein_letter"},
           "turn": {"role": "assistant", "content": "checking the W-9"},
           "usage": {"input_tokens": 10, "output_tokens": 5}}
    parsed = LLMResponse.model_validate(raw)
    assert isinstance(parsed.action, DocumentRequest)
    assert parsed.action.doc_ids == ["w9"]


def test_escalation_and_submission_also_discriminate():
    esc = LLMResponse.model_validate(
        {"action": {"kind": "escalate", "gaps": []},
         "turn": {"role": "assistant", "content": "cannot find it"}, "usage": {}})
    assert isinstance(esc.action, Escalation)


def test_status_stage_is_constrained_to_the_spec_list():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        OnboardingStatus(stage="inventing_a_stage", attempt=1, application=None,
                         gaps=[], pending_since=None, core_attempt=0,
                         last_error=None, core_request_id=None, client_id=None,
                         extraction_iterations=0)
