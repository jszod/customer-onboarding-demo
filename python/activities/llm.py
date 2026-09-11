"""The model call. §8.3.

The ONLY thing in the extraction child that performs I/O. It resolves
requested_doc_ids to document text itself, so document content never enters
workflow history (§8.1, §8.2). It returns VALIDATED models, so the workflow
never parses raw model output (§8.3).

Error classification lives here rather than in `non_retryable_error_types` at
the call site (§10.2): 401 and other 4xx are non-retryable, 429 carries the
`retry-after` header through as `next_retry_delay`, 5xx and connection errors
retry. One source of truth, and correct retry behaviour then falls out of
merely calling the activity.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

import anthropic
from pydantic import ValidationError
from pypdf import PdfReader
from temporalio import activity
from temporalio.exceptions import ApplicationError

from python import config, prompts
from python.models.extraction import (AgentTurn, DocumentRequest, Escalation,
                                      ExtractionSubmission, LLMRequest,
                                      LLMResponse)

_ACTION_BY_TOOL = {"request_documents": DocumentRequest,
                   "submit_extraction": ExtractionSubmission,
                   "escalate": Escalation}

# §10.2 gives call_llm a 120s start_to_close. The client gives up first so a
# hung socket surfaces as a classified activity failure rather than a Temporal
# timeout with nothing to say about it.
_CLIENT_TIMEOUT_SECONDS = 110.0
_DEFAULT_RETRY_AFTER_SECONDS = 30.0
_MAX_TOKENS = 4096


@lru_cache(maxsize=1)
def _client() -> anthropic.Anthropic:
    # max_retries=0: Temporal owns retry (§8.3). A client that retried
    # internally would hide attempts from the history and from the console.
    return anthropic.Anthropic(max_retries=0, timeout=_CLIENT_TIMEOUT_SECONDS)


def _create_message(**kwargs):
    """Seam so tests can inject failures without touching the network."""
    return _client().messages.create(**kwargs)


def _llm_down_flag() -> Path:
    """§10.4. The console's LLM-outage toggle reaches the worker as a flag
    file, because the worker is a different process from the gateway and could
    never see its memory. `web/gateway.py:_llm_down_flag` writes exactly this
    path; if the two halves disagree the demo beat silently does nothing.
    """
    return config.settings().document_store.parent / ".llm_down"


def _document_text(req: LLMRequest) -> str:
    """Resolve refs to text HERE, inside the activity."""
    store = config.settings().document_store
    by_id = {r.doc_id: r for r in req.manifest.refs}
    chunks = []
    for doc_id in req.requested_doc_ids:
        ref = by_id.get(doc_id)
        if ref is None:
            # §8.1: an unknown id is reported back to the model as content, not
            # raised. The manifest check itself is the workflow's pure job.
            chunks.append(f"### {doc_id}\n(unknown document id)")
            continue
        path = store / ref.uri
        text = "\n".join(p.extract_text() or "" for p in PdfReader(path).pages)
        chunks.append(f"### {doc_id} ({ref.kind})\n{text}")
    return "\n\n".join(chunks)


def _user_content(req: LLMRequest) -> str:
    manifest = "\n".join(f"- {r.doc_id} ({r.kind}, {r.page_count}p)"
                         for r in req.manifest.refs)
    parts = [f"Available documents:\n{manifest}",
             "Required field paths:\n" + "\n".join(req.required_field_paths)]
    if req.requested_doc_ids:
        parts.append("Document contents you asked for:\n" + _document_text(req))
    if req.prior_gaps:
        parts.append("Gaps from the previous attempt:\n" + "\n".join(
            f"- {g.field_path}: {g.reason}" for g in req.prior_gaps))
    if req.analyst_note:
        parts.append(f"Note from the KYC analyst:\n{req.analyst_note}")
    return "\n\n".join(parts)


def _retry_after_seconds(exc: anthropic.RateLimitError) -> float:
    """§10.2 — 429 sets next_retry_delay from the header. A header we cannot
    read as seconds falls back rather than failing the classification."""
    raw = None
    response = getattr(exc, "response", None)
    if response is not None:
        raw = response.headers.get("retry-after")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return _DEFAULT_RETRY_AFTER_SECONDS


@activity.defn(name="call_llm")
async def live_call_llm(req: LLMRequest) -> LLMResponse:
    if _llm_down_flag().exists():
        # §10.4. Retryable on purpose: the beat is the agent loop visibly
        # retrying and then resuming once the toggle is cleared. A
        # non-retryable failure would end the demo instead of staging it.
        raise ApplicationError(
            "LLM outage toggled from the console (§10.4)", type="LLMOutage")

    # Both legs are blocking: `_user_content` opens and parses PDFs, and the
    # Anthropic client is the SYNCHRONOUS one, which can sit on a socket for
    # `_CLIENT_TIMEOUT_SECONDS`. Run on the event loop they stall every other
    # activity this worker is running, its workflow tasks, and its heartbeats
    # -- the same defect R-009 fixed in `open_account`.
    messages = [{"role": "user", "content": await asyncio.to_thread(_user_content, req)}]
    for turn in req.turns:
        messages.append({"role": "assistant" if turn.role == "assistant" else "user",
                         "content": turn.content})
    try:
        message = await asyncio.to_thread(
            _create_message,
            model=req.model, max_tokens=_MAX_TOKENS, system=prompts.SYSTEM,
            tools=prompts.TOOLS, tool_choice={"type": "any"}, messages=messages)
    except anthropic.AuthenticationError as e:
        raise ApplicationError(f"invalid API key: {e}", type="AuthenticationError",
                               non_retryable=True) from e
    except anthropic.RateLimitError as e:
        raise ApplicationError(
            f"rate limited: {e}", type="RateLimitError",
            next_retry_delay=timedelta(seconds=_retry_after_seconds(e))) from e
    except anthropic.APIStatusError as e:
        if e.status_code and e.status_code < 500:
            raise ApplicationError(f"client error {e.status_code}: {e}",
                                   type="ClientError", non_retryable=True) from e
        raise ApplicationError(f"server error {e.status_code}: {e}",
                               type="ServerError") from e
    except anthropic.APIConnectionError as e:
        raise ApplicationError(f"connection error: {e}",
                               type="ConnectionError") from e
    except TypeError as e:
        # No credentials resolve at all: the SDK constructs happily with
        # `api_key=None` and raises a BARE TypeError from `messages.create`.
        # It is not an `anthropic` error, so it misses every clause above,
        # escapes the classification chain, and retries on the default
        # unlimited policy -- a missing environment variable presenting as a
        # workflow that hangs. It is a configuration fault: never retryable.
        if "authentication" not in str(e).lower():
            raise
        raise ApplicationError(
            f"no API credentials: {e}. Set ANTHROPIC_API_KEY, or run with "
            f"FIXTURE_MODE=1 (§16.7).",
            type="AuthenticationError", non_retryable=True) from e

    block = next((b for b in message.content if b.type == "tool_use"), None)
    if block is None:
        raise ApplicationError("model returned no tool call",
                               type="MalformedResponse")
    model_cls = _ACTION_BY_TOOL.get(block.name)
    if model_cls is None:
        raise ApplicationError(f"unknown tool {block.name!r}",
                               type="MalformedResponse")

    # Coercion happens HERE: malformed output is a retryable activity failure,
    # and the workflow only ever stores known-good structures (§8.3).
    try:
        action = model_cls.model_validate({**block.input, "kind": block.name})
    except ValidationError as e:
        raise ApplicationError(f"{block.name} did not validate: {e}",
                               type="MalformedResponse") from e

    usage = {"input_tokens": message.usage.input_tokens,
             "output_tokens": message.usage.output_tokens}
    activity.logger.info("call_llm action=%s usage=%s", block.name, usage)
    return LLMResponse(
        action=action,
        turn=AgentTurn(role="assistant", content=json.dumps(block.input)[:2000]),
        usage=usage)


@activity.defn(name="call_llm")
async def fixture_call_llm(req: LLMRequest) -> LLMResponse:
    """Recorded responses (§16.0, §16.7). Selected by FIXTURE_MODE at worker
    startup -- never by an `if` inside the workflow, which would make the two
    modes non-replay-compatible."""
    # §17.1. Fixtures return instantly, so step 2 would otherwise be invisible.
    # `live_call_llm` gets nothing: a real call already takes real seconds.
    await config.demo_pause(1)
    fixture_dir = Path(os.environ.get("FIXTURE_DIR", "fixtures"))
    client_key = (req.manifest.refs[0].uri.split("/")[0]
                  if req.manifest.refs else "acme-corp")
    path = fixture_dir / f"{client_key}.json"
    if not path.exists():
        raise ApplicationError(
            f"no fixtures at {path}; run `make fixtures` with an API key (§16.7)",
            type="FixturesMissing", non_retryable=True)
    sequence = json.loads(path.read_text())
    if not sequence:
        # `min(len(turns), -1)` is -1, which indexes the empty list and raises
        # IndexError -- unclassified, so it retries forever.
        raise ApplicationError(
            f"{path} records no responses; re-run `make fixtures` (§16.7)",
            type="FixturesMissing", non_retryable=True)
    # ONE recorded response per model CALL, and each call contributes exactly
    # one assistant turn to the transcript. Counting the whole transcript
    # instead skips a response for every tool result: `request_documents`
    # appends the assistant turn AND its tool turn, so the second call would
    # ask for sequence[2] of a two-response recording and die as exhausted.
    # Invisible to every fixture unit test, which hand-build transcripts that
    # happen to hold assistant turns only -- and to the recorder, which never
    # reads its own output. R-026, and the same family as R-024.
    call = sum(1 for turn in req.turns if turn.role == "assistant")
    if call >= len(sequence):
        # Past the end of the recording. Repeating the last turn forever is
        # how a fixture set that is one response short presents as the agent
        # looping to its iteration cap for no visible reason.
        raise ApplicationError(
            f"{path} records {len(sequence)} responses but the agent is on "
            f"call {call + 1}; re-record it (§16.7)",
            type="FixturesExhausted", non_retryable=True)
    return LLMResponse.model_validate(sequence[call])
