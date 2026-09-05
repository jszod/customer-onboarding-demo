"""The onboarding business process. §7.

Steps 1-3 are a LOOP. ingest_documents re-runs per attempt, which is what lets
a rejected attempt pick up newly added documents without a signal-based intake
path (§7).

Every failure path ends in a business status. A failed workflow reads as a bug;
a completed workflow with a terminal status reads as a process (§10.3).
"""
from __future__ import annotations

import re
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ChildWorkflowError

with workflow.unsafe.imports_passed_through():
    from python import config, gaps
    from python.models.application import ApplicationFields
    from python.models.core_banking import (ClientIdAssignment, OpenAccountAck,
                                            OpenAccountRequest)
    from python.models.delivery import (NotifyRequest, NotifyResult,
                                        SendDocumentsRequest, SendDocumentsResult)
    from python.models.documents import DocumentManifest, IngestRequest
    from python.models.extraction import (ExtractionRequest, ExtractionResult,
                                          FieldGap)
    from python.models.onboarding import (ApplicationRequest, OnboardingResult,
                                          OnboardingStatus)
    from python.models.review import ReviewAck, ReviewSubmission

    # Read ONCE, here. `settings()` reads os.environ, which the sandbox forbids
    # during execution -- and a workflow that re-read its config mid-run would
    # replay differently after an env change. See .claude/rules/.
    SETTINGS = config.settings()


# §9.1 rule 4. Compiled at import rather than inside the validator, so the
# pattern is not rebuilt on every submission and nothing is imported mid-run.
_EIN = re.compile(r"^\d{2}-\d{7}$")


def _failure_message(e: ActivityError | ChildWorkflowError) -> str:
    cause = e.cause
    return str(cause) if cause else str(e)


@workflow.defn(name="OnboardingWorkflow")
class OnboardingWorkflow:
    def __init__(self) -> None:
        self._stage = "ingesting"
        self._attempt = 1
        self._application: ApplicationFields | None = None
        self._gaps: list[FieldGap] = []
        self._iterations = 0
        self._pending_since = None
        self._review: ReviewSubmission | None = None
        self._client_id_assignment: ClientIdAssignment | None = None
        self._core_attempt = 0
        self._core_request_id: str | None = None
        self._last_error: str | None = None

    # ---------------------------------------------------------------- run

    @workflow.run
    async def run(self, req: ApplicationRequest) -> OnboardingResult:
        while self._attempt <= SETTINGS.max_attempts:
            self._stage = "ingesting"
            try:
                manifest = await workflow.execute_activity(
                    "ingest_documents",
                    IngestRequest(client_key=req.client_key, attempt=self._attempt),
                    result_type=DocumentManifest,
                    start_to_close_timeout=timedelta(seconds=30),
                    summary=f"Collect documents for {req.legal_name}")
            except ActivityError as e:
                return await self._finish(req, "manual_intervention", None,
                                          f"document ingestion failed: "
                                          f"{_failure_message(e)}")

            self._stage = "extracting"
            try:
                extraction: ExtractionResult = await workflow.execute_child_workflow(
                    "ExtractionAgentWorkflow",
                    ExtractionRequest(
                        client_key=req.client_key, legal_name=req.legal_name,
                        manifest=manifest, attempt=self._attempt,
                        prior_gaps=self._gaps,
                        analyst_note=self._review.note if self._review else None),
                    result_type=ExtractionResult,
                    id=f"{workflow.info().workflow_id}-extract-{self._attempt}")
            except ChildWorkflowError as e:
                # A spent attempt, not a workflow failure (§10.3).
                self._last_error = _failure_message(e)
                self._attempt += 1
                continue

            self._application = extraction.application
            self._gaps = extraction.gaps or gaps.compute_gaps(extraction.application)
            self._iterations = extraction.iterations

            self._stage = "awaiting_review"
            self._pending_since = workflow.now()
            self._review = None
            await self._await_review()
            review = self._review
            assert review is not None

            if review.decision == "approve":
                self._application = gaps.apply_edits(self._application,
                                                     review.field_edits)
                break
            self._attempt += 1
        else:
            # The loop ran out of attempts. `self._attempt` has been incremented
            # past the cap, so report the cap itself -- three attempts were made.
            self._attempt = SETTINGS.max_attempts
            return await self._finish(
                req, "manual_intervention", None,
                f"rejected {SETTINGS.max_attempts} times; "
                f"last note: {self._review.note if self._review else 'n/a'}")

        return await self._open_and_finish(req)

    # ------------------------------------------------------- steps 4 to 7

    async def _open_and_finish(self, req: ApplicationRequest) -> OnboardingResult:
        """Filled in by Task 16. Kept as a separate method so Task 16 touches
        one place and Task 14's tests keep passing."""
        self._stage = "submitting_to_core"
        ack: OpenAccountAck = await workflow.execute_activity(
            "open_account",
            OpenAccountRequest(idempotency_key=workflow.info().workflow_id,
                               application=self._application),
            result_type=OpenAccountAck,
            start_to_close_timeout=timedelta(seconds=5),
            retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1),
                                     backoff_coefficient=2.0,
                                     maximum_interval=timedelta(seconds=10)),
            summary="Submit account request to core banking")
        self._core_request_id = ack.request_id

        self._stage = "awaiting_client_id"
        self._pending_since = workflow.now()
        await workflow.wait_condition(lambda: self._client_id_assignment is not None)
        assignment = self._client_id_assignment
        assert assignment is not None

        self._stage = "sending_documents"
        packet: SendDocumentsResult = await workflow.execute_activity(
            "send_documents",
            SendDocumentsRequest(client_key=req.client_key,
                                 client_id=assignment.client_id,
                                 legal_name=req.legal_name,
                                 application=self._application),
            result_type=SendDocumentsResult,
            start_to_close_timeout=timedelta(seconds=60),
            summary="Send the welcome pack")

        return await self._finish(req, "completed", assignment.client_id,
                                  "onboarding complete", packet.packet_uri)

    async def _finish(self, req: ApplicationRequest, status: str,
                      client_id: str | None, detail: str,
                      packet_uri: str | None = None) -> OnboardingResult:
        self._stage = "notifying"
        recipients = (["onboarding_specialist", "end_client"]
                      if status == "completed"
                      else ["onboarding_specialist", "supervisor"])
        await workflow.execute_activity(
            "notify",
            NotifyRequest(client_key=req.client_key, client_id=client_id,
                          outcome=status, recipients=recipients,
                          packet_uri=packet_uri, detail=detail),
            result_type=NotifyResult,
            start_to_close_timeout=timedelta(seconds=30),
            summary=f"Notify {', '.join(recipients)}")
        self._stage = "complete" if status == "completed" else status
        return OnboardingResult(status=status, client_id=client_id,
                                attempts=self._attempt, detail=detail)

    async def _await_review(self) -> None:
        """Replaced by Task 17 with the tiered SLA. Never auto-approves."""
        await workflow.wait_condition(lambda: self._review is not None)

    # --------------------------------------------------------- wire surface

    @workflow.update
    async def submit_review(self, submission: ReviewSubmission) -> ReviewAck:
        self._review = submission
        return ReviewAck(accepted=True, stage=self._stage)

    @submit_review.validator
    def validate_review(self, submission: ReviewSubmission) -> None:
        """§9.1. Format and internal consistency ONLY — validators must not
        block or mutate, so no activities and no I/O. Anything needing I/O
        ("does this EIN exist?") is an activity after acceptance.

        Raising here rejects the update BEFORE it enters history.

        `field_edits` may target any path, not only the escalated gaps: §9.1
        picks an update over a signal precisely because the analyst edits field
        values, and §19.3 requires accepting an edit to an optional field.
        """
        if self._stage != "awaiting_review":
            raise ValueError(f"not awaiting review (stage: {self._stage})")
        if self._application is None:
            raise ValueError("no extracted application to review")

        if submission.decision == "reject":
            if not (submission.note or "").strip():
                raise ValueError("a rejection must carry a note the "
                                 "onboarding specialist can act on")
            return

        # --- approve path
        if not submission.attested:
            raise ValueError("you must attest that you have reviewed the "
                             "extracted data before approving")

        merged = gaps.apply_edits(self._application, submission.field_edits)

        missing = gaps.missing_required(merged)
        if missing:
            raise ValueError("cannot approve while required fields are empty: "
                             + ", ".join(missing))

        if merged.tax_id and not _EIN.match(merged.tax_id):
            raise ValueError(f"tax_id {merged.tax_id!r} is not a valid EIN "
                             f"(expected NN-NNNNNNN)")

        total = sum((o.ownership_pct or 0) for o in merged.beneficial_owners)
        if total > 100:
            raise ValueError(f"beneficial ownership totals {total}%, which "
                             f"exceeds 100%")

    @workflow.signal
    def client_id_received(self, assignment: ClientIdAssignment) -> None:
        # First assignment wins; a duplicate is ignored and logged (§19.5).
        if self._client_id_assignment is None:
            self._client_id_assignment = assignment
        else:
            workflow.logger.info("ignoring duplicate client id %s",
                                 assignment.client_id)

    @workflow.query
    def status(self) -> OnboardingStatus:
        return OnboardingStatus(
            stage=self._stage, attempt=self._attempt,
            application=self._application, gaps=self._gaps,
            pending_since=self._pending_since, core_attempt=self._core_attempt,
            last_error=self._last_error, core_request_id=self._core_request_id,
            client_id=(self._client_id_assignment.client_id
                       if self._client_id_assignment else None),
            extraction_iterations=self._iterations)
