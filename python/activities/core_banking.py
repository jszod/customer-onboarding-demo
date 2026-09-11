"""The core banking call. §10.1.

The idempotency key arrives on the request and IS the parent workflow ID --
identical on every retry, because the workflow ID does not change when an
activity is retried. It is forwarded to core banking exactly as it arrived;
never rebuilt here from anything the SDK varies per retry. Doing so would
produce exactly the duplicate account the design exists to prevent.

§10.1.1 gives this module one legitimate reason to read its own retry
counter below: to stamp which try got the answer, on the ack this activity
returns -- never to build the key from it. `tests/test_activity_core_banking.py`
asserts the real property behaviourally (drive the activity across several
attempt numbers and the key on the wire stays byte-identical) rather than by
grepping this file for the counter's name, which stopped working the moment
that legitimate read was added; R-037 has the history.

The HTTP client's timeout is deliberately far longer than the activity's 5s
`start_to_close_timeout`. The activity timing out while the request is still in
flight is the whole point: a `start_to_close_timeout` firing does not cancel
the server's work, so the account gets opened and the answer is lost. The retry
then carries the same key, and core banking answers `duplicate` with the
original `request_id` -- the proof the key worked, and a value to return, never
an error to raise.
"""
from __future__ import annotations

import httpx
from temporalio import activity
from temporalio.exceptions import ApplicationError

from python import config
from python.models.core_banking import OpenAccountAck, OpenAccountRequest


def _detail(resp: httpx.Response) -> str:
    """Core banking's own words, when it gave any."""
    try:
        body = resp.json()
    except ValueError:
        return resp.text.strip()[:200]
    return str(body.get("detail", body)) if isinstance(body, dict) else str(body)


@activity.defn(name="open_account")
async def open_account(req: OpenAccountRequest) -> OpenAccountAck:
    s = config.settings()
    try:
        async with httpx.AsyncClient(base_url=s.core_banking_url,
                                     timeout=110.0) as client:
            resp = await client.post("/accounts", json={
                "idempotency_key": req.idempotency_key,
                "application": req.application.model_dump(mode="json")})
    except httpx.HTTPError as e:
        # Unreachable or timed out at the socket: transient, Temporal's to retry.
        raise ApplicationError(f"core banking unreachable: {e}",
                               type="ConnectionError") from e

    if resp.status_code in (408, 429):
        # Busy, not a verdict on the application.
        raise ApplicationError(f"core banking busy ({resp.status_code})",
                               type="Transient")
    if 400 <= resp.status_code < 500:
        # §10.2: a business rejection is the bank's answer, not a glitch.
        # Retrying it forever would hide a decision behind a spinner, so the
        # classification lives here rather than in a call-site retry policy.
        raise ApplicationError(
            f"core banking rejected the application: {_detail(resp)}",
            type="CoreRejection", non_retryable=True)
    if resp.status_code >= 500:
        raise ApplicationError(f"core banking error {resp.status_code}",
                               type="ServerError")
    resp.raise_for_status()

    # §10.1.1. The service does not know how many times we have asked, so the
    # count is stamped here. The workflow cannot count for itself: §10.2's
    # policy owns the retry, so it sees one call and one result -- and it needs
    # this to tell a duplicate caused by our own lost reply from a duplicate
    # caused by an onboarding that ran months ago.
    ack = OpenAccountAck.model_validate(
        resp.json() | {"attempt": activity.info().attempt})
    activity.logger.info("open_account key=%s status=%s request_id=%s try=%d",
                         req.idempotency_key, ack.status, ack.request_id,
                         ack.attempt)
    return ack
