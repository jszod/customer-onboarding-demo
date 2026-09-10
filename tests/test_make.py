"""`make help` is generated, so it can only stay honest if every target is
annotated. §14.

This exists because the command list previously lived in three places — the
spec's §14 table, `CLAUDE.md`'s Commands section, and nothing at all in the
Makefile — and the only complete one was written for agents rather than for a
person at a prompt. Generating the list from the targets removes one copy;
this test removes the way the generated one goes quietly incomplete.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MK = ROOT / "make" / "common.mk"

# Started by `up`, never typed directly. `kill-worker` is reachable but is
# `restart-worker`'s first half, and naming it in help invites a bare `kill`
# mid-demo, which §14 explicitly does not want.
INTERNAL = {"temporal", "core-banking", "gateway", "worker", "kill-worker", "help"}

GROUPS = ("setup", "demo", "verify", "build")


def targets() -> dict[str, str | None]:
    """Every target in the file, mapped to its `## N group|description`."""
    found = {}
    for line in MK.read_text().splitlines():
        m = re.match(r"^([a-z][a-z-]*):(?!=)([^#]*)(?:##\s*(.*))?$", line)
        if m:
            found[m.group(1)] = m.group(3)
    return found


def test_every_public_target_is_annotated():
    """An unannotated target is invisible in `make help`, which is worse than
    no help at all — the list looks complete."""
    missing = [t for t, ann in targets().items()
               if ann is None and t not in INTERNAL]
    assert not missing, f"no `## group|description` on: {sorted(missing)}"


def test_annotations_use_a_known_group_and_sort_index():
    bad = []
    for t, ann in targets().items():
        if ann is None:
            continue
        m = re.match(r"^(\d) ([a-z]+)\|(.+)$", ann)
        if not m or m.group(2) not in GROUPS:
            bad.append(f"{t}: {ann!r}")
        elif int(m.group(1)) != GROUPS.index(m.group(2)) + 1:
            bad.append(f"{t}: group {m.group(2)!r} wants index "
                       f"{GROUPS.index(m.group(2)) + 1}, got {m.group(1)}")
    assert not bad, bad


def test_help_lists_every_annotated_target():
    """The generator is a grep/sed/awk pipeline, so it is worth running rather
    than reading. It also catches the trap that broke it once: `$(lastword
    $(MAKEFILE_LIST))` inside a recipe expands to `.env`, because
    `-include $(ROOT)/.env` appends to MAKEFILE_LIST after the top of the
    file — so help greps an empty file and prints a heading with no rows."""
    out = subprocess.run(["make", "help"], cwd=ROOT, capture_output=True,
                         text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    for target, ann in targets().items():
        if ann is not None:
            assert re.search(rf"^\s+make {re.escape(target)}\s", out.stdout, re.M), \
                f"`make help` never lists {target!r}"
    for group in GROUPS:
        assert group.upper() in out.stdout, f"group {group!r} missing from help"


def test_help_works_from_the_second_entry_point():
    """§15 — `python/Makefile` is the same include one directory down, and
    `THIS_MK` has to resolve from there too."""
    out = subprocess.run(["make", "-C", "python", "help"], cwd=ROOT,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert "make verify" in out.stdout
