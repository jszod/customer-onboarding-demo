"""The progress tracker. §12.

One `stage` value, two surfaces: the console draws a stepper, the Temporal UI
renders the same seven steps as Current Details.
"""
from python.models.extraction import FieldGap
from python.workflows import tracker

GAP = FieldGap(field_path="beneficial_owners[1].dob", reason="not stated",
               documents_searched=["ownership_declaration"])


def _markers(out: str) -> dict[str, str]:
    """Marker per step, matched by name rather than by splitting on the first
    space — the current step's line carries a trailing note."""
    found = {}
    for line in out.splitlines():
        if line[:1] in ("✓", "→", "○"):
            for step in tracker.STEPS:
                if line[2:].startswith(step):
                    found[step] = line[0]
    return found


def test_all_seven_steps_appear_in_every_render():
    out = tracker.render("awaiting_review", 1, "Acme Holdings LLC", [GAP], None)
    for step in ("Collect documents", "Extract", "KYC review", "Open account",
                 "Receive client ID", "Send documents", "Notify"):
        assert step in out


def test_current_step_is_marked_and_earlier_steps_are_done():
    out = tracker.render("awaiting_review", 1, "Acme Holdings LLC", [], None)
    marks = _markers(out)
    assert marks["Collect documents"] == "✓"
    assert marks["Extract & structure"] == "✓"
    assert marks["KYC review"] == "→"
    assert marks["Open account"] == "○"


def test_the_gap_is_named_so_the_ui_says_what_is_blocking():
    out = tracker.render("awaiting_review", 1, "Acme Holdings LLC", [GAP], None)
    assert "beneficial_owners[1].dob" in out


def test_attempt_is_shown_only_when_greater_than_one():
    assert "attempt 1" not in tracker.render("extracting", 1, "Acme", [], None)
    assert "attempt 2" in tracker.render("extracting", 2, "Acme", [], None)


def test_terminal_stages_render_without_a_current_marker():
    out = tracker.render("complete", 1, "Acme Holdings LLC", [], "CL-ABC12345")
    assert "→" not in out
    assert out.count("✓") == 7
    assert "CL-ABC12345" in out


def test_a_failed_terminal_stage_says_so_rather_than_showing_seven_ticks():
    """§10.3 — manual_intervention is a finished process with a bad outcome,
    not a completed one. R-011 drew the same distinction in the console."""
    out = tracker.render("manual_intervention", 3, "Acme Holdings LLC", [],
                         "rejected 3 times")
    assert "→" not in out
    assert "rejected 3 times" in out
    assert out.count("✓") < 7, "a failed run must not read as seven done steps"


def test_render_is_pure_and_deterministic():
    a = tracker.render("extracting", 1, "Acme", [GAP], None)
    b = tracker.render("extracting", 1, "Acme", [GAP], None)
    assert a == b


def test_output_fits_the_20kb_details_limit():
    """§12 — static_details allows 20KB; current details should stay small."""
    out = tracker.render("awaiting_review", 3, "Acme Holdings LLC", [GAP] * 20, None)
    assert len(out.encode()) < 20_000
