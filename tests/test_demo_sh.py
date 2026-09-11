"""§14.1 — the entry point that assumes nothing.

The live-stack cycle is a MANUAL step (Step 10), not a test here: it binds
7233, 8000 and 8001, which would collide with a dev stack and make `make
verify` depend on free ports. Same call as R-022's browser drive — the
structural gates are committed, the thing that needs real processes is run by
hand and reported.
"""
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "demo.sh"
VERBS = ("demo", "up", "down", "status", "logs", "reset", "restart-worker")


def run(*args, **kw):
    return subprocess.run(["bash", str(SCRIPT), *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=60, **kw)


def test_the_script_exists_and_is_bash():
    assert SCRIPT.is_file()
    assert SCRIPT.read_text().startswith("#!/usr/bin/env bash")


def test_every_verb_is_handled():
    out = run("no-such-verb")
    assert out.returncode != 0
    for verb in VERBS:
        assert verb in out.stdout + out.stderr, f"{verb} missing from usage"


def test_no_pgrep_or_pkill_anywhere():
    """§14.1. Git Bash ships rm, tail, grep, nohup, kill and mkdir — but not
    procps. `pgrep` is the one tool that would break the customer, and it is
    also what cost R-001 and R-025."""
    for f in (SCRIPT, ROOT / "make" / "common.mk"):
        body = f.read_text()
        assert "pgrep" not in body, f"{f.name} still uses pgrep"
        assert "pkill" not in body, f"{f.name} still uses pkill"


def test_the_long_running_processes_do_not_go_through_uv_run():
    """The measured trap: `uv run` forks a child python, the CHILD binds the
    port, so `$!` records uv and killing it orphans the listener. The venv
    interpreter is started directly so `$!` IS the port owner."""
    body = SCRIPT.read_text()
    assert ".venv/bin/python" in body
    assert ".venv/Scripts/python.exe" in body, "no Windows interpreter path"
    for line in body.splitlines():
        if "nohup" in line:
            assert "uv run" not in line, f"uv run in a spawn line: {line.strip()}"


def test_status_on_a_stopped_stack_says_so_and_exits_zero():
    out = run("status")
    assert out.returncode == 0, out.stderr
    for name in ("temporal", "core banking", "gateway", "worker"):
        assert name in out.stdout


def test_a_stale_pid_file_reads_as_stopped_and_does_not_block(tmp_path):
    """§14.1's stated new failure mode. A killed process leaves its file
    behind, so liveness must be checked rather than existence — and a stale
    file must not make `up` refuse to start."""
    run("down")
    runsdir = ROOT / ".run"
    runsdir.mkdir(exist_ok=True)
    stale = runsdir / "gateway.pid"
    stale.write_text("999999\n")          # a pid that cannot be alive
    try:
        out = run("status")
        assert out.returncode == 0, out.stderr
        assert re.search(r"gateway\s*:\s*stopped", out.stdout), out.stdout
    finally:
        stale.unlink(missing_ok=True)


def test_gitattributes_pins_shell_scripts_to_lf():
    """Git for Windows defaults to core.autocrlf=true. Without this the
    customer's FIRST command returns `/bin/bash^M: bad interpreter`, which
    looks like our defect."""
    ga = (ROOT / ".gitattributes").read_text()
    assert re.search(r"\*\.sh\s+text\s+eol=lf", ga), ga


def test_the_run_directory_is_gitignored():
    assert ".run/" in (ROOT / ".gitignore").read_text()


def test_make_delegates_rather_than_duplicating():
    """One implementation, two front doors (§14.1). A recipe that starts a
    process itself is a second definition, and this build has paid for that
    twice — R-035 and the demo-reset help entry.

    `make demo-reset` maps to the `reset` verb, not a `demo-reset` verb —
    demo.sh's VERBS tuple above has no such entry (R-038)."""
    mk = (ROOT / "make" / "common.mk").read_text()
    for target, verb in (("up", "up"), ("down", "down"), ("status", "status"),
                         ("demo-reset", "reset"), ("restart-worker", "restart-worker")):
        assert f"demo.sh {verb}" in mk, f"`make {target}` does not call demo.sh {verb}"
    assert not (ROOT / "make" / "start.sh").exists(), \
        "start.sh should have folded into demo.sh"
