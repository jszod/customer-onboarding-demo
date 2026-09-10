"""Progress-tracker rendering. §12.

Pure and deterministic: string building only, so it is safe to call from
workflow code. Uses ✓ / → / ○ rather than markdown task lists, because
task-list rendering is not guaranteed in the Temporal UI.
"""
from __future__ import annotations

STEPS = ("Collect documents", "Extract & structure", "KYC review",
         "Open account", "Receive client ID", "Send documents", "Notify")

STAGE_INDEX = {"ingesting": 0, "extracting": 1, "awaiting_review": 2,
               "submitting_to_core": 3, "awaiting_client_id": 4,
               "sending_documents": 5, "notifying": 6}

# A finished process with a bad outcome is not a finished process with a good
# one. R-011 drew this distinction in the console; the Temporal UI gets the
# same treatment, and the index is the step the run stopped at.
FAILED_AT = {"manual_intervention": 2, "rejected_by_core": 3,
             # §10.1.1. It stopped AT the account step, and nothing failed --
             # the account was already there. Marked at index 3 so the first
             # three steps still read as done and the last three as never run,
             # which is what happened. Without an entry here `.get()` returns
             # None and all seven steps render as open, claiming the run never
             # started.
             "already_onboarded": 3}

STAGE_NOTE = {
    "ingesting": "reading the client's document set",
    "extracting": "the agent is filling the application",
    "awaiting_review": "awaiting the KYC analyst",
    "submitting_to_core": "submitting to core banking",
    "awaiting_client_id": "awaiting the client ID from core banking",
    "sending_documents": "preparing the welcome pack",
    "notifying": "notifying the specialist and the client",
}


def render(stage: str, attempt: int, legal_name: str, gaps, detail=None) -> str:
    current = STAGE_INDEX.get(stage)
    failed_at = FAILED_AT.get(stage)
    lines = [f"**Onboarding — {legal_name}**", ""]

    for i, step in enumerate(STEPS):
        if failed_at is not None:
            if i < failed_at:
                lines.append(f"✓ {step}")
            elif i == failed_at:
                lines.append(f"✗ {step} — {stage.replace('_', ' ')}")
            else:
                lines.append(f"○ {step}")
        elif stage == "complete" or (current is not None and i < current):
            lines.append(f"✓ {step}")
        elif i == current:
            suffix = f" — {STAGE_NOTE.get(stage, '')}"
            if attempt > 1:
                suffix += f" (attempt {attempt})"
            lines.append(f"→ {step}{suffix}")
        else:
            lines.append(f"○ {step}")

    if gaps:
        lines.append("")
        shown = list(gaps)[:5]
        lines.append(f"Gaps ({len(gaps)}):")
        lines.extend(f"- `{g.field_path}` — {g.reason}" for g in shown)
        if len(gaps) > len(shown):
            lines.append(f"- …and {len(gaps) - len(shown)} more")

    if detail:
        lines += ["", str(detail)]

    return "\n".join(lines)
