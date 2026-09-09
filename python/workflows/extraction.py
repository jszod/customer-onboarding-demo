"""The extraction agent. §8.1.

Exactly ONE activity: call_llm. All three tools are inline workflow tools
because each mutates only agent state, which ai-patterns Pattern 3 places in
workflow code. Nothing here reads the disk -- the file system is touched only
by call_llm (Pattern 2).

Workflow state holds document IDS, never document text, so document content
never enters history (§8.2).
"""
from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from python import config
    from python.models.application import ApplicationFields
    from python.models.extraction import (AgentTurn, DocumentRequest, Escalation,
                                          ExtractionRequest, ExtractionResult,
                                          ExtractionSubmission, FieldGap,
                                          LLMRequest, LLMResponse)

    # Read ONCE, here, not inside run(). `settings()` reads os.environ, which
    # the workflow sandbox forbids at execution time -- and rightly so: a
    # workflow that re-read its config mid-run would replay differently after
    # an env change. Inside this context the read is an ordinary import-time
    # one, and the value is then frozen for the life of the worker.
    SETTINGS = config.settings()


def document_tool_turn(doc_ids: list[str], known_ids: set[str]) -> AgentTurn:
    """The result of one `request_documents` call, as a tool turn.

    Recorded on EVERY path, not only the error one. `call_llm` renders an
    assistant turn as an assistant message, so a transcript ending on one is an
    assistant prefill -- which Sonnet 5 and every 4.6+ model reject with a 400
    (`This model does not support assistant message prefill`). Recording the
    tool's result is both the correct tool-loop shape and what keeps the next
    request valid.

    Ids only. §8.2 keeps document text out of history, and `call_llm`
    re-renders the granted documents into the user message from
    `requested_doc_ids` regardless.

    Pure and deterministic -- sorted, never set-ordered -- so it is safe in
    workflow code, and `tools/record_fixtures.py` calls it too: that script
    hand-rolls this loop to record fixtures without a Temporal server, and a
    second copy of this rule is a second thing to forget.
    """
    granted = [d for d in doc_ids if d in known_ids]
    unknown = [d for d in doc_ids if d not in known_ids]
    parts = []
    if granted:
        parts.append(f"now readable: {', '.join(granted)}")
    if unknown:
        parts.append(f"unknown document ids: {', '.join(unknown)}. "
                     f"Available: {', '.join(sorted(known_ids))}")
    # An empty `doc_ids` would otherwise produce an empty content block, which
    # the API also rejects.
    return AgentTurn(role="tool",
                     content="; ".join(parts) or "no document ids were requested")


@workflow.defn(name="ExtractionAgentWorkflow")
class ExtractionAgentWorkflow:
    @workflow.run
    async def run(self, req: ExtractionRequest) -> ExtractionResult:
        s = SETTINGS
        requested: list[str] = []          # doc IDS -- a few bytes
        turns: list[AgentTurn] = []
        known_ids = {r.doc_id for r in req.manifest.refs}

        for iteration in range(1, s.max_iterations + 1):
            workflow.set_current_details(
                f"Extraction attempt {req.attempt}, iteration {iteration} — "
                f"read: {', '.join(requested) or 'nothing yet'}")

            response: LLMResponse = await workflow.execute_activity(
                "call_llm",
                LLMRequest(model=s.model, manifest=req.manifest,
                           requested_doc_ids=list(requested), turns=list(turns),
                           required_field_paths=list(config.REQUIRED_FIELD_PATHS),
                           prior_gaps=req.prior_gaps,
                           analyst_note=req.analyst_note),
                # Required: a string-named activity has no signature to infer
                # from, so without this the converter returns a bare dict.
                result_type=LLMResponse,
                start_to_close_timeout=timedelta(seconds=120),
                # maximum_attempts=0 means UNLIMITED, not "no retries" -- this is
                # §10.2's "default" policy for call_llm, and the classification
                # in the activity is what makes 401 and content-policy stop.
                retry_policy=RetryPolicy(maximum_attempts=0),
                summary=f"Extract — iteration {iteration}"
                        f"{', requesting ' + ','.join(requested[-1:]) if requested else ''}",
            )
            turns.append(response.turn)
            action = response.action

            # --- inline tool: request_documents (no I/O, pure state mutation)
            if isinstance(action, DocumentRequest):
                for doc_id in action.doc_ids:
                    if doc_id in known_ids and doc_id not in requested:
                        requested.append(doc_id)
                turns.append(document_tool_turn(action.doc_ids, known_ids))
                continue

            # --- inline tool: submit_extraction (terminal)
            if isinstance(action, ExtractionSubmission):
                return ExtractionResult(application=action.application,
                                        gaps=action.gaps, iterations=iteration,
                                        escalated=bool(action.gaps))

            # --- inline tool: escalate (terminal)
            if isinstance(action, Escalation):
                # Carry the partial application through. Escalation is the
                # demo's headline beat and it lands on the review console:
                # returning an empty ApplicationFields here would hand the
                # analyst a blank form and drop every field the agent read,
                # including the list members their gap edits address (§9.1).
                return ExtractionResult(
                    application=action.application or ApplicationFields(),
                    gaps=action.gaps, iterations=iteration, escalated=True)

        # Cap reached without a terminal tool. Escalate; never raise (§8.1).
        # Nothing was ever submitted, so there is no application to carry --
        # but the review console drives off `gaps`, so say why it is empty
        # rather than presenting a blank form with nothing flagged.
        return ExtractionResult(
            application=ApplicationFields(),
            gaps=req.prior_gaps or [FieldGap(
                field_path="",
                reason=f"the extraction agent reached its {s.max_iterations}"
                       f"-iteration cap without submitting an application",
                documents_searched=list(requested))],
            iterations=s.max_iterations, escalated=True)
