"""The recorded fixtures. §16.7.

Recorded from a live run, never hand-written. These tests are skipped until
`make fixtures` has been run once with `ANTHROPIC_API_KEY` set — that is the
one human prerequisite in the build, and the skip is the remaining work, not a
tolerated gap. `make verify` stays red while it stands.
"""
import json
from pathlib import Path

import pytest

from python.models.extraction import (DocumentRequest, Escalation,
                                      ExtractionSubmission, LLMResponse)

FIXTURES = Path("fixtures/acme-corp.json")

pytestmark = pytest.mark.skipif(
    not FIXTURES.exists(),
    reason="fixtures not recorded yet — run `make fixtures` with "
           "ANTHROPIC_API_KEY set (§16.7 step 2)")


def _sequence() -> list[LLMResponse]:
    return [LLMResponse.model_validate(r)
            for r in json.loads(FIXTURES.read_text())]


def test_fixtures_exist_and_parse_as_llm_responses():
    """§16.7 — recorded from a real run, never hand-written."""
    assert len(_sequence()) >= 2


def test_the_sequence_reaches_a_terminal_action():
    assert isinstance(_sequence()[-1].action, (ExtractionSubmission, Escalation))


def test_the_sequence_requests_documents_before_deciding():
    """The loop must have genuinely iterated, or the fixture proves nothing."""
    assert isinstance(_sequence()[0].action, DocumentRequest)


def test_the_recorded_run_escalates_the_deliberate_gap():
    """§8.4 — the recording must reproduce the demo's escalation beat."""
    terminal = _sequence()[-1].action
    paths = [g.field_path for g in terminal.gaps]
    assert any("dob" in p for p in paths), \
        "the recorded run should have escalated the missing date of birth"


def test_fixtures_carry_a_provenance_header():
    """A fixture with no provenance cannot be judged stale."""
    meta = Path("fixtures/README.md").read_text()
    assert "make fixtures" in meta
    assert "claude-sonnet-5" in meta or "MODEL" in meta
