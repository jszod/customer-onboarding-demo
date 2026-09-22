"""The README is the customer's first contact with this repo. §14.1, §2.

These are not style checks. Each one pins a claim that, if wrong, fails on the
Windows customer's machine before anything works — and he has nobody to ask.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()
DEMO_SH = (ROOT / "demo.sh").read_text()

# Verified against the vendors' own install docs, 2026-09-22:
#   https://docs.temporal.io/cli/setup-cli          — no package manager, manual only
#   https://docs.astral.sh/uv/getting-started/installation/ — winget id astral-sh.uv
INVENTED_WINGET_IDS = ("Temporal.Temporal", "temporal.temporal")


def test_no_winget_package_is_claimed_for_the_temporal_cli():
    """R-039. The Temporal CLI has NO winget/Chocolatey/Scoop package —
    docs.temporal.io/cli/setup-cli documents the manual download as the only
    Windows route. An earlier draft invented `winget install Temporal.Temporal`
    in both the README and demo.sh's error message. That is the customer's
    very first command, and it would have failed with a package-not-found
    error that looks like his mistake rather than ours.

    `uv` is the opposite case and stays: `astral-sh.uv` is a documented id.
    """
    for name, body in (("README.md", README), ("demo.sh", DEMO_SH)):
        for bad in INVENTED_WINGET_IDS:
            assert bad not in body, (
                f"{name} claims a winget package for the Temporal CLI "
                f"({bad!r}); there isn't one — link the temporal.download "
                f"archive and the PATH step instead")


def test_the_windows_path_points_at_the_real_download():
    """Having removed the wrong command, the right one has to be present —
    otherwise the fix above is satisfied by saying nothing at all."""
    assert "temporal.download/cli/archive/latest?platform=windows" in README
    assert re.search(r"temporal\.exe", README), "no PATH instruction for the binary"


def test_demo_sh_tells_a_windows_user_where_to_get_the_cli():
    """demo.sh fails early and loudly when the CLI is missing; that message is
    the one place a customer who skipped the README will look."""
    i = DEMO_SH.find("Temporal CLI is not on PATH")
    assert i != -1, "demo.sh no longer checks for the Temporal CLI"
    nearby = DEMO_SH[i:i + 600]
    assert "temporal.download" in nearby, \
        "the CLI-missing message does not say where to get it"


def test_uv_keeps_its_documented_winget_id():
    """The distinction is the point: uv HAS a winget package, the CLI does
    not. A blanket ban on the word would lose a correct instruction."""
    assert "astral-sh.uv" in README


def test_both_platforms_have_a_setup_section_and_the_nav_links_resolve():
    """§2's fourth audience runs this repo. A Windows reader who lands in a
    macOS-shaped Setup section types `brew install` and stops."""
    headings = re.findall(r"^#{2,3} (.+)$", README, re.M)
    slugs = {re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", h.lower())) for h in headings}
    for anchor in set(re.findall(r"\]\(#([^)]+)\)", README)):
        assert anchor in slugs, f"README links to #{anchor}, which is not a heading"
    assert any("macos" in s for s in slugs), "no macOS setup section"
    assert any("windows" in s for s in slugs), "no Windows setup section"


def test_every_demo_sh_verb_named_in_the_readme_exists():
    """The customer copies these verbatim."""
    named = set(re.findall(r"demo\.sh ([a-z-]+)", README))
    real = set(re.findall(r"^\s{2}([a-z-]+)\)\s", DEMO_SH, re.M))
    assert named <= real, f"README names verbs demo.sh does not have: {named - real}"
