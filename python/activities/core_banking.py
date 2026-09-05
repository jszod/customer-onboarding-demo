"""The core banking call. §10.1.

The idempotency key arrives on the request and IS the parent workflow ID --
identical on every retry, because the workflow ID does not change when an
activity is retried. Never rebuild it here from anything the SDK varies per
retry (`activity.info()` exposes a retry counter, and reaching for it is the
trap §10.1 names); doing so produces exactly the duplicate account the design
exists to prevent. The word does not appear in this module on purpose, and
`tests/test_activity_core_banking.py` asserts that.

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

    ack = OpenAccountAck.model_validate(resp.json())
    activity.logger.info("open_account key=%s status=%s request_id=%s",
                         req.idempotency_key, ack.status, ack.request_id)
    return ack
