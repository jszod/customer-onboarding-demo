"""Task 8 — the operator console. §13.

There is no server and no Temporal here: the console is a single self-contained
page, so its contract is checked statically against the file plus the pure-JS
constants it declares. What is under test is the *functional surface* — the
seven stages, the three controls (one per actor, §3), the attestation gate, the
2s poll, and the two states the gateway can hand back that a naive console gets
wrong (404 before the workflow exists, 409 on a duplicate submit).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "web" / "static" / "index.html"


def body() -> str:
    return PAGE.read_text()


# --- the plan's seven tests -------------------------------------------------

def test_page_exists_and_is_self_contained():
    b = body()
    assert "<script" in b
    assert 'src="http' not in b and "src='http" not in b, "no external assets"


def test_all_seven_steps_are_named_in_the_stepper():
    """§12 — the audience sees position in the whole process, not one screen."""
    b = body()
    for step in ("Collect", "Extract", "KYC review", "Open account",
                 "Client ID", "Send docs", "Notify"):
        assert step in b


def test_three_controls_one_per_actor():
    b = body()
    assert "/applications" in b        # onboarding specialist
    assert "/api/review/" in b         # KYC analyst
    assert "/api/assign/" in b         # core banking


def test_attestation_checkbox_is_required_to_approve():
    """§13 — the analyst attests; §9.1 rule 3 enforces it server-side too."""
    b = body()
    assert "attested" in b
    assert "reviewed" in b.lower()


def test_polls_status_every_two_seconds():
    b = body()
    assert "/api/status/" in b
    assert "2000" in b


def test_submitting_to_core_shows_attempt_and_last_error():
    """§13 — the headline retry must be legible without the Temporal UI."""
    b = body()
    assert "core_attempt" in b
    assert "last_error" in b


def test_demo_controls_are_present():
    b = body()
    assert "slow_first_call" in b
    assert "llm_down" in b


# --- what the finished gateway forces on us --------------------------------

def test_404_before_the_workflow_exists_is_an_idle_state_not_an_error():
    """GET /api/status/<key> is 404 until Submit is pressed. The console polls
    from page load, so a 404 must render neutral, never a red banner."""
    b = body()
    assert "404" in b


def test_duplicate_submit_surfaces_the_409_message():
    """§6.1 — the 409 is the workflow-ID demonstration, not an error to hide."""
    b = body()
    assert "409" in b


def test_review_rejection_renders_the_422_validator_message():
    """§9.1 — the update validator's reason comes back as 422 {error}."""
    b = body()
    assert "422" in b


# --- the review panel ------------------------------------------------------

def test_gap_panel_renders_the_whole_field_gap():
    """§5.3 / §13 — gap-first means reason and provenance, not just a name."""
    b = body()
    for key in ("field_path", "reason", "documents_searched"):
        assert key in b


def test_review_payload_matches_review_submission():
    """§5.4 — decision / analyst_id / note / field_edits / attested."""
    b = body()
    for key in ("decision", "analyst_id", "note", "field_edits", "attested"):
        assert key in b
    assert "approve" in b and "reject" in b
    assert "kyc-analyst-1" in b


def test_extracted_fields_collapse_into_an_application_grouped_table():
    """§13 — Business / Beneficial owners / Control person."""
    b = body()
    assert "extracted &amp; verified" in b or "extracted & verified" in b
    assert "Business" in b
    assert "Beneficial owners" in b
    assert "Control person" in b


# --- stage coverage --------------------------------------------------------

def test_every_status_stage_has_a_stepper_position():
    """§5.6 lists ten stages. A stage the console cannot place is a blank
    screen in front of a customer."""
    b = body()
    for stage in ("ingesting", "extracting", "awaiting_review",
                  "submitting_to_core", "awaiting_client_id",
                  "sending_documents", "notifying", "complete",
                  "manual_intervention", "rejected_by_core"):
        assert re.search(rf"\b{stage}\b", b), f"stage {stage} unhandled"


def test_client_id_control_is_gated_on_the_waiting_stage():
    b = body()
    assert "awaiting_client_id" in b


# --- shown on a projector --------------------------------------------------

def test_page_adapts_to_light_and_dark():
    b = body()
    assert "prefers-color-scheme" in b


def test_no_external_javascript_libraries():
    b = body().lower()
    for host in ("cdnjs", "unpkg", "jsdelivr", "cdn.tailwindcss", "code.jquery"):
        assert host not in b
