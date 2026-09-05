"""The scenario manifest — §16.8 of the spec.

THE DEFINITION OF DONE: all 22 pass and none are skipped.

Each task below converts its own stubs into real failing tests, then makes
them pass. Do NOT delete a stub. Adding a scenario is allowed and must be
logged as a ruling (§19); silently dropping one is not.
"""
import pytest

SKIP = "not implemented — see the owning task in the plan"


# --- §16.1 activity unit tests (Tasks 9, 10, 11) ---

def test_T_ACT_01_ingest_copies_and_hashes_documents():
    """ingest_documents copies files and returns refs; missing file raises non-retryable."""
    from tests.test_activity_ingest import (assert_copies_and_hashes,
                                            assert_missing_file_is_non_retryable)
    assert_copies_and_hashes()
    assert_missing_file_is_non_retryable()


def test_T_ACT_02_call_llm_classifies_errors():
    """401 non-retryable, 429 sets next_retry_delay, 5xx retryable."""
    from tests.test_activity_llm import (assert_401_non_retryable,
                                         assert_429_sets_retry_delay,
                                         assert_5xx_retryable)
    assert_401_non_retryable()
    assert_429_sets_retry_delay()
    assert_5xx_retryable()


def test_T_ACT_03_open_account_is_idempotent():
    """Two calls with the same idempotency key: the second returns duplicate."""
    from tests.test_activity_core_banking import assert_second_call_is_duplicate
    assert_second_call_is_duplicate()


# --- §16.2 workflow tests (Tasks 14, 15, 16) ---

async def test_T_WF_01_happy_path_completes_with_client_id(env):
    """Happy path completes with status="completed" and a client ID.

    Delegates to tests/test_onboarding_workflow.py::test_T_WF_01_happy_path.
    """
    from tests.test_onboarding_workflow import test_T_WF_01_happy_path
    await test_T_WF_01_happy_path(env)


async def test_T_WF_02_reject_increments_attempt_and_reingests(env):
    """Reject increments attempt and re-runs ingest_documents.

    Delegates to tests/test_onboarding_workflow.py::test_T_WF_02_reject_increments_attempt_and_reingests.
    """
    from tests.test_onboarding_workflow import test_T_WF_02_reject_increments_attempt_and_reingests
    await test_T_WF_02_reject_increments_attempt_and_reingests(env)


async def test_T_WF_03_max_attempts_exhausted_is_manual_intervention(env):
    """MAX_ATTEMPTS exhausted -> manual_intervention, not a failed workflow.

    Delegates to tests/test_onboarding_workflow.py::test_T_WF_03_max_attempts_exhausted_is_manual_intervention.
    """
    from tests.test_onboarding_workflow import test_T_WF_03_max_attempts_exhausted_is_manual_intervention
    await test_T_WF_03_max_attempts_exhausted_is_manual_intervention(env)


async def test_T_WF_04_approve_with_empty_required_field_is_rejected(env):
    """The validator refuses an approve while a required field is empty.

    Delegates to tests/test_review_validator.py::test_T_WF_04_approve_with_empty_required_field_is_rejected.
    """
    from tests.test_review_validator import test_T_WF_04_approve_with_empty_required_field_is_rejected
    await test_T_WF_04_approve_with_empty_required_field_is_rejected(env)


async def test_T_WF_05_approve_without_attestation_is_rejected(env):
    """The validator refuses an approve without attested=True.

    Delegates to tests/test_review_validator.py::test_T_WF_05_approve_without_attestation_is_rejected.
    """
    from tests.test_review_validator import test_T_WF_05_approve_without_attestation_is_rejected
    await test_T_WF_05_approve_without_attestation_is_rejected(env)


async def test_T_WF_06_ownership_over_100_is_rejected(env):
    """sum(ownership_pct) > 100 -> validator rejects. Note <=, not ==.

    Delegates to tests/test_review_validator.py::test_T_WF_06_ownership_over_100_is_rejected.
    """
    from tests.test_review_validator import test_T_WF_06_ownership_over_100_is_rejected
    await test_T_WF_06_ownership_over_100_is_rejected(env)


async def test_T_WF_07_timeout_then_duplicate_opens_exactly_one_account(env):
    """THE HEADLINE. Workflow proceeds and the ledger holds exactly one account.

    Delegates to tests/test_core_submission.py::test_T_WF_07_timeout_then_duplicate_opens_exactly_one_account.
    """
    from tests.test_core_submission import test_T_WF_07_timeout_then_duplicate_opens_exactly_one_account
    await test_T_WF_07_timeout_then_duplicate_opens_exactly_one_account(env)


async def test_T_WF_08_core_rejection_completes_as_rejected_by_core(env):
    """A non-retryable core rejection completes the workflow, not crashes it.

    Delegates to tests/test_core_submission.py::test_T_WF_08_core_rejection_completes_as_rejected_by_core.
    """
    from tests.test_core_submission import test_T_WF_08_core_rejection_completes_as_rejected_by_core
    await test_T_WF_08_core_rejection_completes_as_rejected_by_core(env)


async def test_T_WF_09_child_workflow_error_counts_as_a_spent_attempt(env):
    """ChildWorkflowError is caught and counted, not propagated.

    Delegates to tests/test_onboarding_workflow.py::test_T_WF_09_child_workflow_error_counts_as_a_spent_attempt.
    """
    from tests.test_onboarding_workflow import test_T_WF_09_child_workflow_error_counts_as_a_spent_attempt
    await test_T_WF_09_child_workflow_error_counts_as_a_spent_attempt(env)


# --- §16.3 time-skipping tests (Task 17) ---

@pytest.mark.skip(reason=SKIP)
def test_T_TIME_01_remind_then_escalate_fire_in_order():
    """Remind at SLA_REMIND, escalate at SLA_ESCALATE, still waiting after both."""


@pytest.mark.skip(reason=SKIP)
def test_T_TIME_02_never_auto_approves():
    """Far past both SLAs, stage is still awaiting_review. §9.2's rule is
    worthless without this test."""


@pytest.mark.skip(reason=SKIP)
def test_T_TIME_03_client_id_sla_does_not_abandon_the_workflow():
    """CLIENT_ID_SLA fires, reminds, and keeps waiting."""


# --- §16.4 child workflow tests (Task 13) ---

def test_T_CHILD_01_illegible_ein_letter_falls_back_to_w9():
    """The cross-document behaviour. If this regresses, the demo's most
    interesting moment dies silently."""
    from tests.test_extraction_workflow import assert_falls_back_to_w9
    assert_falls_back_to_w9()


def test_T_CHILD_02_missing_dob_escalates_with_documents_searched():
    """dob absent everywhere -> escalated=True, documents_searched populated."""
    from tests.test_extraction_workflow import assert_escalates_with_provenance
    assert_escalates_with_provenance()


def test_T_CHILD_03_iteration_cap_escalates_without_raising():
    """MAX_ITERATIONS reached -> escalated=True, no exception."""
    from tests.test_extraction_workflow import assert_cap_escalates
    assert_cap_escalates()


# --- §16.5 replay tests (Task 20) ---

@pytest.mark.skip(reason=SKIP)
def test_T_REPLAY_01_happy_path_history_replays():
    """histories/happy-path.json replays against current workflow code."""


@pytest.mark.skip(reason=SKIP)
def test_T_REPLAY_02_reject_loop_history_replays():
    """histories/reject-loop.json replays."""


@pytest.mark.skip(reason=SKIP)
def test_T_REPLAY_03_timeout_retry_history_replays():
    """histories/timeout-retry.json replays."""


@pytest.mark.skip(reason=SKIP)
def test_T_REPLAY_04_escalation_history_replays():
    """histories/escalation.json replays."""
