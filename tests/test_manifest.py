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


@pytest.mark.skip(reason=SKIP)
def test_T_ACT_02_call_llm_classifies_errors():
    """401 non-retryable, 429 sets next_retry_delay, 5xx retryable."""


@pytest.mark.skip(reason=SKIP)
def test_T_ACT_03_open_account_is_idempotent():
    """Two calls with the same idempotency key: the second returns duplicate."""


# --- §16.2 workflow tests (Tasks 14, 15, 16) ---

@pytest.mark.skip(reason=SKIP)
def test_T_WF_01_happy_path_completes_with_client_id():
    """Happy path completes with status="completed" and a client ID."""


@pytest.mark.skip(reason=SKIP)
def test_T_WF_02_reject_increments_attempt_and_reingests():
    """Reject increments attempt and re-runs ingest_documents."""


@pytest.mark.skip(reason=SKIP)
def test_T_WF_03_max_attempts_exhausted_is_manual_intervention():
    """MAX_ATTEMPTS exhausted -> manual_intervention, not a failed workflow."""


@pytest.mark.skip(reason=SKIP)
def test_T_WF_04_approve_with_empty_required_field_is_rejected():
    """The validator refuses an approve while a required field is empty."""


@pytest.mark.skip(reason=SKIP)
def test_T_WF_05_approve_without_attestation_is_rejected():
    """The validator refuses an approve without attested=True."""


@pytest.mark.skip(reason=SKIP)
def test_T_WF_06_ownership_over_100_is_rejected():
    """sum(ownership_pct) > 100 -> validator rejects. Note <=, not ==."""


@pytest.mark.skip(reason=SKIP)
def test_T_WF_07_timeout_then_duplicate_opens_exactly_one_account():
    """THE HEADLINE. Workflow proceeds and the ledger holds exactly one account."""


@pytest.mark.skip(reason=SKIP)
def test_T_WF_08_core_rejection_completes_as_rejected_by_core():
    """A non-retryable core rejection completes the workflow, not crashes it."""


@pytest.mark.skip(reason=SKIP)
def test_T_WF_09_child_workflow_error_counts_as_a_spent_attempt():
    """ChildWorkflowError is caught and counted, not propagated."""


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

@pytest.mark.skip(reason=SKIP)
def test_T_CHILD_01_illegible_ein_letter_falls_back_to_w9():
    """The cross-document behaviour. If this regresses, the demo's most
    interesting moment dies silently."""


@pytest.mark.skip(reason=SKIP)
def test_T_CHILD_02_missing_dob_escalates_with_documents_searched():
    """dob absent everywhere -> escalated=True, documents_searched populated."""


@pytest.mark.skip(reason=SKIP)
def test_T_CHILD_03_iteration_cap_escalates_without_raising():
    """MAX_ITERATIONS reached -> escalated=True, no exception."""


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
