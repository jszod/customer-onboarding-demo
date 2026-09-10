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
from temporalio.exceptions import (ActivityError, ApplicationError,
                                  ChildWorkflowError)

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
    from python.workflows import tracker

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
        self._core_duplicate = False
        self._core_preexisting = False
        self._last_error: str | None = None
        self._client_id_chase = 0

    def _track(self, req: ApplicationRequest, detail: str | None = None) -> None:
        """§12. One `stage` value, two surfaces: the console draws a stepper
        and the Temporal UI shows this. Pure string building, so it is safe
        from workflow code."""
        workflow.set_current_details(
            tracker.render(self._stage, self._attempt, req.legal_name,
                           self._gaps, detail))

    # ---------------------------------------------------------------- run

    @workflow.run
    async def run(self, req: ApplicationRequest) -> OnboardingResult:
        while self._attempt <= SETTINGS.max_attempts:
            self._stage = "ingesting"
            self._track(req)
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
            self._track(req)
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
                # A spent attempt, not a workflow failure (§10.3). Label it
                # with the attempt: this is the only record of why the attempt
                # went, and the exhausted-attempts path below reports it.
                self._last_error = (f"attempt {self._attempt} extraction "
                                    f"failed: {_failure_message(e)}")
                self._attempt += 1
                continue

            self._application = extraction.application
            self._gaps = extraction.gaps or gaps.compute_gaps(extraction.application)
            self._iterations = extraction.iterations

            self._stage = "awaiting_review"
            self._pending_since = workflow.now()
            self._review = None
            self._track(req)
            await self._await_review(req)
            review = self._review
            assert review is not None

            if review.decision == "approve":
                self._application = gaps.apply_edits(self._application,
                                                     review.field_edits)
                break
            # A rejection is a spent attempt too, and it is the analyst's note
            # that says why. Recording it here keeps `last_error` -- which §13
            # puts on the console -- true of the most recent attempt whichever
            # way it went, and gives the exhausted path below one thing to read.
            self._last_error = (f"attempt {self._attempt} rejected: "
                                f"{review.note or 'no note'}")
            self._attempt += 1
        else:
            # The loop ran out of attempts. `self._attempt` has been incremented
            # past the cap, so report the cap itself -- three attempts were made.
            self._attempt = SETTINGS.max_attempts
            # Do NOT assume the attempts were rejections: three
            # ChildWorkflowErrors exhaust the loop without a single human
            # decision, and reporting "rejected 3 times" there describes a
            # review that never happened while dropping the real cause.
            return await self._finish(
                req, "manual_intervention", None,
                f"{SETTINGS.max_attempts} attempts exhausted; "
                f"{self._last_error or 'no further detail recorded'}")

        return await self._open_and_finish(req)

    # ------------------------------------------------------- steps 4 to 7

    async def _open_and_finish(self, req: ApplicationRequest) -> OnboardingResult:
        """Filled in by Task 16. Kept as a separate method so Task 16 touches
        one place and Task 14's tests keep passing."""
        self._stage = "submitting_to_core"
        self._track(req)

        # A workflow-level retry loop, NOT the activity retry policy. §10.2's
        # table describes the policy shape -- initial 1s, backoff 2.0, max
        # interval 10s, unlimited attempts -- and this reproduces it exactly,
        # but as workflow-visible steps. Activity retries do not touch workflow
        # state, and §13 requires the console to show `core_attempt` and
        # `last_error` live while the retry is happening. See R-015.
        while True:
            self._core_attempt += 1
            try:
                ack: OpenAccountAck = await workflow.execute_activity(
                    "open_account",
                    OpenAccountRequest(
                        # Stable across every retry. NEVER a retry counter --
                        # that is the trap in §10.1 and it produces exactly the
                        # duplicate account this design prevents.
                        idempotency_key=workflow.info().workflow_id,
                        application=self._application),
                    result_type=OpenAccountAck,
                    start_to_close_timeout=timedelta(seconds=5),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    summary=f"Submit account request to core banking "
                            f"(attempt {self._core_attempt})")
                break
            except ActivityError as e:
                cause = e.cause
                if isinstance(cause, ApplicationError) and cause.non_retryable:
                    # A business rejection: complete, do not crash (§10.3).
                    self._last_error = _failure_message(e)
                    return await self._finish(req, "rejected_by_core", None,
                                              self._last_error)
                self._last_error = (f"attempt {self._core_attempt}: "
                                    f"{_failure_message(e)}")
                await workflow.sleep(
                    timedelta(seconds=min(10, 2 ** (self._core_attempt - 1))),
                    summary=f"Backoff before core banking attempt "
                            f"{self._core_attempt + 1}")

        self._core_request_id = ack.request_id
        if ack.status == "duplicate":
            self._core_duplicate = True
            if self._core_attempt == 1:
                # §10.1.1. A duplicate on the FIRST attempt means nothing in
                # this run created the account -- a previous onboarding for
                # this client did. Carrying on would send a welcome pack and
                # tell the client about an account they have held for months.
                # Terminal business status, never a failed workflow (§10.3);
                # `_finish` notifies the specialist and supervisor, and by
                # §5.5.1 the end client is not on that list.
                self._core_preexisting = True
                return await self._finish(
                    req, "already_onboarded", None,
                    f"account {ack.request_id} already exists for this client "
                    f"from an earlier onboarding; nothing was created and no "
                    f"documents were sent")
            # Attempt >= 2: our OWN first call created it and the answer was
            # lost. The proof the key worked, and the headline beat (§10.1).
            workflow.logger.info(
                "core banking returned duplicate for %s -- the idempotency key "
                "prevented a second account", ack.request_id)

        self._stage = "awaiting_client_id"
        self._pending_since = workflow.now()
        self._track(req)
        await self._await_client_id(req)
        assignment = self._client_id_assignment
        assert assignment is not None

        self._stage = "sending_documents"
        self._track(req)
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
        self._track(req, detail)
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
        self._track(req, client_id or detail)
        return OnboardingResult(status=status, client_id=client_id,
                                attempts=self._attempt, detail=detail)

    async def _await_review(self, req: ApplicationRequest) -> None:
        """§9.2. Tiered reminders, and the workflow NEVER auto-approves.

        A workflow that approved a KYC application because a timer fired would
        be a compliance incident. Only a human closes this gate; the timers
        only nag. T-TIME-02 pins this by advancing a year."""
        # Each tier is an offset from when the gate OPENED, not from when the
        # previous tier finished. Chaining the tiers (`sla_escalate -
        # sla_remind` started after the reminder's notify returns) pushes
        # escalation past SLA_ESCALATE by however long that activity took, and
        # goes negative outright when SLA_ESCALATE <= SLA_REMIND.
        opened_at = self._pending_since
        for deadline, tier, recipients in (
                (SETTINGS.sla_remind, "reminder",
                 ["onboarding_specialist"]),
                (SETTINGS.sla_escalate, "escalation",
                 ["onboarding_specialist", "supervisor"])):
            remaining = deadline - (workflow.now() - opened_at)
            if remaining > timedelta(0):
                try:
                    # §12 wants the durable timer labelled on the Timeline. The
                    # parameter is `timeout_summary`, not `summary`.
                    await workflow.wait_condition(
                        lambda: self._review is not None, timeout=remaining,
                        timeout_summary=f"KYC review SLA — {tier} at {deadline}")
                    return
                except TimeoutError:
                    pass
            elif self._review is not None:
                # The deadline was already behind us, so there was no timer to
                # wait on -- but a decision may have arrived meanwhile.
                return
            await workflow.execute_activity(
                "notify",
                NotifyRequest(
                    client_key=req.client_key, client_id=None,
                    outcome="manual_intervention", recipients=recipients,
                    detail=f"KYC review {tier}: attempt {self._attempt} has "
                           f"been awaiting review since {self._pending_since}"),
                result_type=NotifyResult,
                start_to_close_timeout=timedelta(seconds=30),
                summary=f"KYC review {tier}")
        # Both tiers have fired. Keep waiting -- indefinitely, by design.
        await workflow.wait_condition(lambda: self._review is not None)

    async def _await_client_id(self, req: ApplicationRequest) -> None:
        """§9.3. Same never-give-up basis: chase, never abandon -- and, like
        §9.2, remind first and then escalate."""
        while True:
            try:
                await workflow.wait_condition(
                    lambda: self._client_id_assignment is not None,
                    timeout=SETTINGS.client_id_sla,
                    timeout_summary=f"Client ID SLA — {SETTINGS.client_id_sla}")
                return
            except TimeoutError:
                self._client_id_chase += 1
                # `notify` keys its records on
                # (client_key, outcome, recipients, detail) -- R-005 chose that
                # key so a Temporal retry appends nothing. A chase whose detail
                # never varied would collide with the first one on every
                # iteration and be dropped, leaving one notification for an
                # unbounded wait. The chase count is what keeps them distinct.
                tier = "reminder" if self._client_id_chase == 1 else "escalation"
                recipients = (["onboarding_specialist"]
                              if self._client_id_chase == 1
                              else ["onboarding_specialist", "supervisor"])
                await workflow.execute_activity(
                    "notify",
                    NotifyRequest(
                        client_key=req.client_key, client_id=None,
                        outcome="manual_intervention",
                        recipients=recipients,
                        detail=f"client ID {tier} #{self._client_id_chase}: "
                               f"still awaiting the client ID from core banking "
                               f"(request {self._core_request_id}), pending "
                               f"since {self._pending_since}"),
                    result_type=NotifyResult,
                    start_to_close_timeout=timedelta(seconds=30),
                    summary=f"Chase the core banking client ID "
                            f"(#{self._client_id_chase})")

    # --------------------------------------------------------- wire surface

    @workflow.update
    async def submit_review(self, submission: ReviewSubmission) -> ReviewAck:
        # First decision wins. The validator below rejects a second one before
        # it ever reaches history, but two updates delivered in the SAME
        # activation are both validated before either handler runs, so the
        # validator alone cannot close this: without the guard here the second
        # write silently replaces an approval the workflow already
        # acknowledged. There is deliberately no `await` above it -- the check
        # and the assignment have to be one atomic step.
        if self._review is not None:
            raise ApplicationError(
                f"a {self._review.decision} decision has already been recorded "
                f"for attempt {self._attempt}",
                type="DuplicateReview", non_retryable=True)
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
        if self._review is not None:
            raise ValueError(f"a {self._review.decision} decision has already "
                             f"been recorded for attempt {self._attempt}")

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
            extraction_iterations=self._iterations,
            core_duplicate=self._core_duplicate,
            core_preexisting=self._core_preexisting)
