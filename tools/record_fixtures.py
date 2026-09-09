"""Records call_llm responses from a live run. §16.7 step 2.

Requires ANTHROPIC_API_KEY. Run deliberately -- a fixture that no longer
matches the current prompt is worse than no fixture, so the output is reviewed
in the diff.

Re-record when: the prompt changes, ApplicationFields changes, or the document
set changes.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Run from anywhere: `python tools/record_fixtures.py` puts `tools/` on the
# path, not the repo root, so the `python.*` imports below would fail. pytest
# gets this from pyproject's `pythonpath = ["."]`; a plain script does not.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from temporalio.testing import ActivityEnvironment

from python import config
from python.activities.ingest import ingest_documents
from python.activities.llm import live_call_llm
from python.models.documents import IngestRequest
from python.models.extraction import (AgentTurn, DocumentRequest, Escalation,
                                      ExtractionSubmission, LLMRequest)
# The loop below is a hand-rolled copy of ExtractionAgentWorkflow's -- §16.7
# records without a Temporal server -- so the one piece with a rule attached to
# it is imported rather than reimplemented. See its docstring.
from python.workflows.extraction import document_tool_turn

CLIENT_KEY = "acme-corp"
OUT = Path("fixtures")


async def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is required to record fixtures (§16.7)")

    s = config.settings()
    env = ActivityEnvironment()
    manifest = await env.run(ingest_documents,
                             IngestRequest(client_key=CLIENT_KEY, attempt=1))

    requested: list[str] = []
    turns: list[AgentTurn] = []
    recorded: list[dict] = []
    known = {r.doc_id for r in manifest.refs}
    terminal = None

    for iteration in range(1, s.max_iterations + 1):
        response = await env.run(live_call_llm, LLMRequest(
            model=s.model, manifest=manifest, requested_doc_ids=list(requested),
            turns=list(turns),
            required_field_paths=list(config.REQUIRED_FIELD_PATHS)))
        recorded.append(response.model_dump(mode="json"))
        turns.append(response.turn)
        action = response.action
        print(f"  iteration {iteration}: {action.kind}")

        if isinstance(action, DocumentRequest):
            for doc_id in action.doc_ids:
                if doc_id in known and doc_id not in requested:
                    requested.append(doc_id)
            turns.append(document_tool_turn(action.doc_ids, known))
            continue
        if isinstance(action, (ExtractionSubmission, Escalation)):
            terminal = action
            break

    OUT.mkdir(exist_ok=True)
    (OUT / f"{CLIENT_KEY}.json").write_text(json.dumps(recorded, indent=2))
    (OUT / "README.md").write_text(
        "# Recorded fixtures\n\n"
        "Recorded from a live run by `make fixtures` (§16.7). **Never edit by "
        "hand** — a hand-written fixture drifts from real model output and "
        "silently stops testing anything.\n\n"
        f"- Model: `{s.model}` (`MODEL` env)\n"
        f"- Document set: `documents/{CLIENT_KEY}/`\n"
        f"- Iterations recorded: {len(recorded)}\n\n"
        "Re-record when the prompt changes, `ApplicationFields` changes, or "
        "the document set changes. Review the diff.\n")
    print(f"wrote {len(recorded)} responses to {OUT / CLIENT_KEY}.json")

    # §8.4's deliberate gap is the demo's escalation beat. If this run did not
    # reach it, the recording is not usable -- say so here rather than letting
    # it be discovered by a failing test after the commit.
    paths = [g.field_path for g in getattr(terminal, "gaps", [])] if terminal else []
    if not any("dob" in p for p in paths):
        print(
            "\n  WARNING: this run did not escalate the missing date of birth.\n"
            "  Do NOT hand-edit the fixture -- that is the exact failure §16.7\n"
            "  exists to prevent. Make prompts.SYSTEM clearer about reporting\n"
            "  gaps rather than guessing, then re-record.")


if __name__ == "__main__":
    asyncio.run(main())
