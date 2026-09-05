import re
from pathlib import Path

DIAGRAMS = Path("docs/DESIGN-DIAGRAMS.md")
TALK = Path("TALK_TRACK.md")


def test_three_mermaid_diagrams_exist():
    """§21.2 — topology, the ambiguous-timeout sequence, the agent loop."""
    body = DIAGRAMS.read_text()
    assert body.count("```mermaid") == 3, "expected exactly three diagrams"


def test_each_diagram_has_numbered_callouts():
    """§21.3 — a diagram that only works with the author in the room fails."""
    sections = DIAGRAMS.read_text().split("## ")[1:]
    for section in sections:
        if "```mermaid" not in section:
            continue
        assert re.search(r"^\s*\d+\.\s", section, re.M), \
            f"diagram section lacks numbered callouts: {section[:60]!r}"


def test_artifact_does_not_leak_spec_mechanics():
    """§21.4 — not the spec. No retry tables, no env vars, no repo layout."""
    body = DIAGRAMS.read_text() + TALK.read_text()
    for banned in ("start_to_close_timeout", "ANTHROPIC_API_KEY", "pyproject",
                   "MAX_ITERATIONS", "uv run", "make up"):
        assert banned not in body, f"{banned} belongs in the spec, not the artifact"


def test_no_dependency_on_the_demo_running():
    """§21.4 — no console or Temporal UI screenshots; in the fallback
    scenario neither exists."""
    body = DIAGRAMS.read_text() + TALK.read_text()
    assert not re.search(r"!\[.*\]\(.*\.(png|jpg|jpeg|gif)\)", body)


def test_talk_track_covers_the_headline_and_the_escalation():
    body = TALK.read_text().lower()
    assert "idempot" in body
    assert "escalat" in body
