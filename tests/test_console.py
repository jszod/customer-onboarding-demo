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


def test_field_edits_carry_corrections_to_already_extracted_fields():
    """R-014 — `field_edits` is not scoped to gaps. §9.1 chose an update over a
    signal because the analyst edits field values, and correcting one the model
    read wrongly is the ordinary case in KYC review."""
    b = body()
    assert "corrections" in b, "no store for edits to non-gap fields"
    # The dotted paths the validator's apply_edits walks.
    assert "beneficial_owners[" in b
    assert "control_person." in b
    # Corrections must reach the same field_edits array the gaps build.
    assert "field_edits.push" in b


def test_a_corrected_field_is_not_sent_twice():
    """A gap the analyst also edits in the table must produce one entry."""
    b = body()
    assert "field_edits.some" in b


def test_the_extracted_fields_table_is_editable():
    """The other half of R-014: the table renders as editable cells, not text."""
    b = body()
    assert "cell-edit" in b
    assert "data-path=" in b or 'data-path="' in b
    assert "is-edited" in b


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
                  "manual_intervention", "rejected_by_core",
                  "already_onboarded"):
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


# --- Task 22: the visual system, §13.1 --------------------------------------
#
# Ten structural gates over the inline <style> block. They are greps, and greps
# cannot see a visual regression -- Step 14's browser drive is the other half.

TYPE_SCALE = {"11px", "13px", "14px", "15px", "17px", "21px"}
WEIGHTS = {"500", "600", "700"}

# §13.1.1, name -> the value it must hold. Checking presence alone lets the
# scale be redefined to anything while the suite stays green.
TOKEN_VALUES = {
    "--fs-eyebrow": "11px", "--fs-meta": "13px", "--fs-ui": "14px",
    "--fs-body": "15px", "--fs-title": "17px", "--fs-display": "21px",
    "--sp-1": "4px", "--sp-2": "8px", "--sp-3": "12px", "--sp-4": "16px",
    "--sp-5": "20px", "--sp-6": "24px", "--sp-7": "28px", "--sp-8": "32px",
    "--radius": "10px", "--radius-sm": "8px",
}

TOKENS_REQUIRED = tuple(f"{n}:" for n in TOKEN_VALUES) + (
    "--surface-0:", "--surface-1:", "--surface-2:",
    "--text-1:", "--text-2:",
    "--border:", "--border-strong:",
    "--accent:", "--accent-ink:", "--accent-wash:",
    "--done:", "--done-ink:", "--done-wash:",
    "--wait:", "--wait-wash:",
    "--alert:", "--alert-ink:", "--alert-wash:",
    "--control-bg:", "--control-hover:", "--focus-ring:",
)

# Bare names, no colon: a leftover *reference* is the failure mode that
# matters. `var(--muted)` against a token nothing declares resolves to
# nothing, and the page renders with that property simply absent -- which a
# declaration-only check ("--muted:") cannot see. The negative lookahead stops
# a retired name matching its own replacement: --surface must not hit
# --surface-0, and --line must not hit --line-2.
TOKENS_RETIRED = (
    "--bg", "--surface", "--ink", "--muted", "--line", "--line-2",
    "--accent-in", "--accent-bg",
    "--done-bg", "--wait-bg", "--alert-bg",
)

FOCUSABLE = (
    ".btn", ".tui-link", ".gap input",
    "input.cell-edit", ".attest input", ".toggle input", "td.val",
)


def css() -> str:
    """The inline <style> block. §13 forbids external stylesheets, so this is
    the whole visual system."""
    m = re.search(r"<style>(.*?)</style>", PAGE.read_text(), re.S)
    assert m, "the page must carry exactly one inline <style> block"
    return m.group(1)


def test_the_type_scale_is_six_sizes():
    """§13.1.2 — thirteen sizes collapse to six. The half-pixel steps were
    never distinguishable at projector distance. `code` keeps a relative
    `em` size and is deliberately not on the px scale.

    Both the `font-size:` longhand AND the `font:` shorthand are audited: the
    16px document base hid in `font: 16px/1.5 ...` for three tasks precisely
    because a longhand-only census cannot see it."""
    c = css()
    used = set(re.findall(r"font-size:\s*([\d.]+px)", c))
    used |= set(re.findall(r"\bfont:\s*[^;}]*?([\d.]+px)", c))
    assert used <= TYPE_SCALE, f"off-scale sizes: {sorted(used - TYPE_SCALE)}"


def test_the_scale_tokens_hold_the_values_the_spec_gives_them():
    """§13.1.1/13.1.2/13.1.3. Without this, every font-size and every gap
    becomes `var(--fs-ui)` / `var(--sp-4)`, the two audits above match nothing,
    and `set() <= TYPE_SCALE` passes against any scale at all."""
    c = css()
    wrong = [
        f"{name}: expected {want}"
        for name, want in TOKEN_VALUES.items()
        if not re.search(rf"{re.escape(name)}:\s*{re.escape(want)}\s*;", c)
    ]
    assert not wrong, wrong


def test_there_are_three_font_weights():
    """§13.1.2 — eight collapse to three. `ui-sans-serif` resolves to a
    non-variable system face on most machines, so 520 and 560 rendered
    identically to 500; five of the eight existed only in the stylesheet."""
    used = set(re.findall(r"font-weight:\s*(\d+)", css()))
    assert used <= WEIGHTS, f"off-scale weights: {sorted(used - WEIGHTS)}"


def test_the_inert_font_feature_settings_is_gone():
    """§13.1.2 — copied from canonical-ai-demo, whose stack leads with Inter
    where cv05/ss01 exist. Ours leads with ui-sans-serif, so it never did
    anything."""
    assert "font-feature-settings" not in css()


def test_spacing_is_a_four_pixel_grid():
    """§13.1.3. Scoped to padding/margin/gap: component dimensions like the
    34px brand mark and the 17px checkbox are sizes, not spacing."""
    off = []
    pattern = (
        r"\b(padding|margin|gap|row-gap|column-gap)"
        r"(?:-(?:top|right|bottom|left))?:\s*([^;}\n]+)"
    )
    for prop, value in re.findall(pattern, css()):
        for px in re.findall(r"([\d.]+)px", value):
            if float(px) % 4:
                off.append(f"{prop}: {px}px")
    assert not off, f"off-grid spacing: {sorted(set(off))}"


def test_there_is_exactly_one_breakpoint():
    """§13.1.4 — the 900px/860px disagreement had no reason behind it."""
    widths = set(re.findall(r"@media[^{]*max-width:\s*(\d+px)", css()))
    assert widths == {"900px"}, f"breakpoints: {sorted(widths)}"


def test_the_stepper_scrolls_rather_than_wrapping():
    """§13.1.4 — collapsing seven columns to four leaves an orphan row of
    three and destroys the one thing the stepper shows: position within a
    seven-step whole (§12)."""
    c = css().replace(" ", "")
    assert "repeat(4," not in c, "the 7->4 collapse is back"
    assert "minmax(96px" in c
    assert "overflow-x:auto" in c


def test_focus_visible_on_every_interactive_element():
    """§13.1.5 — only .gap input had a focus ring, which made the review gate
    unusable by keyboard. Grouped selectors satisfy this: each substring is
    present either way."""
    c = css()
    missing = [s for s in FOCUSABLE if f"{s}:focus-visible" not in c]
    assert not missing, f"no focus ring: {missing}"


def test_tokens_follow_the_sibling_convention():
    """§13.1.1 — names from temporal-agent-harness, values ours. Every old
    name must be gone from declarations AND from var() references: Step 5
    renames by regex across a 948-line file, and a missed `var(--muted)`
    resolves to nothing at all rather than to the old colour."""
    c = css()
    assert [t for t in TOKENS_REQUIRED if t not in c] == []
    stale = [t for t in TOKENS_RETIRED if re.search(rf"{re.escape(t)}(?![\w-])", c)]
    assert stale == [], f"retired token names still referenced: {stale}"


def test_every_strong_fill_carries_its_ink_token():
    """§13.1.1/13.1.5 — `.btn.go` and the failed step numeral both set
    `color: #fff` literally. That is 5.64:1 and 7.10:1 in light and 2.11:1 and
    2.52:1 in dark, because --done and --alert invert between themes and a
    literal cannot follow them. Foreground colour comes from a token; only a
    token *declaration* may hold a literal."""
    literals = re.findall(r"(?<!-)\bcolor:\s*(#[0-9a-fA-F]{3,8})", css())
    assert literals == [], f"hardcoded foreground colours: {literals}"


def test_the_responsive_block_comes_after_the_rules_it_overrides():
    """§13.1.4 — `@media` contributes nothing to specificity, so a 900px block
    written above the unconditional `.cols` rule loses the cascade to it and
    the columns never collapse. Every other test in this file still reports
    green when that happens: the breakpoint is present, the declaration is
    present, only the order is wrong. Source order is the whole mechanism, so
    source order is what this pins."""
    c = css()
    media = c.index("@media (max-width: 900px)")
    late = [s for s in (".cols {", ".stepper {") if c.index(s) > media]
    assert not late, f"declared after the 900px block, so it overrides it: {late}"


def test_typed_gaps_get_a_typed_input():
    """Four of the 22 required paths are not strings: `formation_date`,
    `beneficial_owners[].dob` and `control_person.dob` are dates, and
    `ownership_pct` is a Decimal (§5.1). Asked for through a bare text box that
    states no format, a date of birth invites `04/15/1962` -- which `apply_edits`
    refuses, correctly: guessing MM/DD against DD/MM on a DOB is worse than
    refusing. `type=date` renders in the analyst's own locale and always hands
    back ISO, so the ambiguity never arises."""
    b = body()
    for leaf, kind in (("dob", "date"), ("formation_date", "date"),
                       ("ownership_pct", "number")):
        assert re.search(rf'{leaf}:\s*"{kind}"', b), f"{leaf} has no typed input"
    assert 'input type="text" data-gap=' not in b, \
        "the gap input is still hardcoded to text"
    assert 'input type="text" class="cell-edit"' not in b, \
        "the inline table editor is still hardcoded to text — correcting an " \
        "already-extracted dob there hits the same refusal as an unfilled gap"


def test_the_gap_input_is_styled_by_type_agnostic_selectors():
    """The moment a gap renders as type=date, `.gap input[type=text]` stops
    matching it and the control silently loses its border, padding and focus
    ring. Same class of failure as R-033: the rule is present, correct, and
    simply does not apply."""
    c = css()
    assert "input[type=text]" not in c, \
        "a type-scoped gap-input selector cannot style a date or number gap"


def test_the_slow_core_checkbox_matches_the_core_banking_default():
    """§10.1. `core_banking/app.py`'s `/ledger` GET already reports
    `slow_first_call`, but the console does not read it back on load -- so the
    checkbox is a hardcoded guess at a value another process owns. While they
    disagreed, a fresh `make demo` showed the box unchecked over an armed
    flag, and the control read as inverted: only a `change` event posts, so
    turning the beat OFF meant checking the box and unchecking it again.

    Wiring the console to read `/ledger` on load is deferred work, not this
    pass -- this test only pins the two hardcoded defaults against each other.

    Pinned here because nothing else connects the two files, and the runbook
    (Task 21 Step 2) walks the analyst straight into the timeout."""
    core = (ROOT / "core_banking" / "app.py").read_text()
    m = re.search(r"app\.state\.slow_first_call\s*=\s*(True|False)", core)
    assert m, "core banking no longer sets slow_first_call at startup"
    server_default = m.group(1) == "True"

    box = re.search(r'<input[^>]*id="slow-first-call"[^>]*>', body())
    assert box, "the slow-first-call checkbox is gone"
    console_default = " checked" in box.group(0)

    assert console_default == server_default, (
        f"core banking starts slow_first_call={server_default} but the "
        f"checkbox renders {'checked' if console_default else 'unchecked'}")
