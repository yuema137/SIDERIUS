"""OpenAI Responses background mode: admission, polling, cancellation and evidence.

Ownership split with ``LLMBridge``:

- Submission runs inside the bridge's ``_call_with_retry`` like any other
  request, so its transport retry policy (including unbounded 429) applies.
- Polling runs AFTER that retry owner has returned a ``BackgroundTicket``. The
  poll loop retries its own transient failures and never raises a transport
  error that could reach ``_call_with_retry``; an accepted request is therefore
  never resubmitted because a status poll failed.
- The bridge's call sites keep recording the final usage row; this module adds
  the submission ledger row and the background pricing evidence.

The wait limit is explicit: ``max_wait_seconds`` from provider acceptance,
clipped by any cooperative execution deadline visible to the bridge. A process
killed by SIGTERM/SIGKILL cannot run the cancel call; its accepted response
keeps running server-side and is billed. Its submission row is the evidence.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import httpx2

from agent.llm_transport.accounting import AccountingCapture
from agent.llm_transport.contracts import (
    COMPLETION_WINDOW_SECONDS,
    Completion,
    OpenAIBackgroundConfig,
)
from core.execution_deadline import ExecutionDeadlineExceeded, remaining_seconds

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelRequest, ModelResponse
    from pydantic_ai.models import Model, ModelRequestParameters
    from pydantic_ai.models.openai import OpenAIResponsesModelSettings

    from agent.llm_transport.client import PydanticClient

#: Discounted windows require Standard processing; ``auto`` qualifies only if
#: the provider happens to select Standard, so the request names it explicitly.
SERVICE_TIER = "default"
#: Poll cadence: doubles from 2 s to a 60 s cap (the bridge's retry backoff cap).
POLL_INITIAL_SECONDS = 2.0
POLL_MAX_SECONDS = 60.0
#: ``background_status`` value that makes the bridge raise ``BackgroundWaitExpired``.
WAIT_EXPIRED = "wait_expired"

WaitLimit = Literal["max_wait_seconds", "execution_deadline"]


def _now() -> float:
    """The poll loop's monotonic clock (one seam for deterministic tests)."""
    return time.monotonic()


class BackgroundWindowRefused(ExecutionDeadlineExceeded):
    """A visible deadline cannot fit the completion window; nothing was submitted."""


class BackgroundWaitExpired(TimeoutError):
    """An accepted background response did not finish within its wait limit.

    The response was cancelled (best effort) and its usage row recorded before
    this was raised. It is not a transport error, so it is never retried. When
    the route's own ``max_wait_seconds`` applied, this is not a deadline verdict;
    see ``BackgroundDeadlineExpired`` for the execution-deadline case.
    """

    def __init__(
        self,
        *,
        label: str,
        response_id: str,
        completion_window: str,
        waited_seconds: float,
        limit: WaitLimit,
    ) -> None:
        self.label = label
        self.response_id = response_id
        self.completion_window = completion_window
        self.waited_seconds = waited_seconds
        self.limit = limit
        super().__init__(
            f"Background response {response_id} for route {label!r} "
            f"(completion window {completion_window}) did not finish after "
            f"{waited_seconds:.1f}s; {limit} reached, response cancelled"
        )


class BackgroundDeadlineExpired(BackgroundWaitExpired, ExecutionDeadlineExceeded):
    """The wait ended because the visible execution deadline came first."""


def background_metadata(
    config: OpenAIBackgroundConfig,
    response_id: str | None,
    raw: dict[str, Any],
    *,
    status: str | None = None,
) -> dict[str, str | int | float | None]:
    """Pricing evidence for one background request, merged into its usage row.

    Cost consumers apply the window discount only when ``service_tier_served``
    is ``default`` and the model is eligible; the provider reports no price.
    """
    served = raw.get("service_tier")
    evidence: dict[str, str | int | float | None] = {
        "background_response_id": response_id,
        "completion_window": config.completion_window,
        "service_tier_requested": SERVICE_TIER,
        "service_tier_served": served if isinstance(served, str) else None,
    }
    if status is not None:
        evidence["background_status"] = status
    return evidence


@dataclass
class BackgroundTicket:
    """An accepted, still pending background response and its continuation state."""

    client: PydanticClient
    config: OpenAIBackgroundConfig
    model_id: str
    messages: list[ModelRequest]
    suspended: ModelResponse
    settings: OpenAIResponsesModelSettings
    parameters: ModelRequestParameters
    json_mode: str | None
    tool_names: set[str]
    raw: dict[str, Any]
    metadata: dict[str, str | int | float | None]
    accepted_at: float = field(default_factory=lambda: _now())
    # A ticket carries no completion: usage and served model stay unknown.
    usage: None = None
    model: None = None

    @property
    def response_id(self) -> str:
        return self.suspended.provider_response_id or ""

    @property
    def transport_metadata(self) -> dict[str, str | int | float | None]:
        return {
            **self.metadata,
            **background_metadata(self.config, self.response_id, self.raw, status="submitted"),
        }

    def cancel_quietly(self) -> str:
        """Best-effort cancel for in-process failures; never masks the original error."""
        try:
            return self.client.cancel_background(self)
        except Exception:  # Best effort: the caller is already propagating a failure.
            return "cancel_failed"


def admit_window(config: OpenAIBackgroundConfig, *, model_id: str) -> None:
    """Refuse before submission when a visible deadline is shorter than the window."""
    remaining = remaining_seconds("llm.background.admission")
    window = COMPLETION_WINDOW_SECONDS[config.completion_window]
    if remaining is not None and remaining < window:
        raise BackgroundWindowRefused(
            f"Background completion window {config.completion_window} ({window:g}s) for "
            f"model {model_id!r} exceeds the {remaining:.0f}s left on the execution deadline; "
            "refused before submission (nothing was billed)"
        )


def _expiry(ticket: BackgroundTicket) -> tuple[float, WaitLimit]:
    """Absolute monotonic expiry: max_wait from acceptance, clipped by a visible deadline."""
    expires_at = ticket.accepted_at + ticket.config.max_wait_seconds
    limit: WaitLimit = "max_wait_seconds"
    remaining = remaining_seconds("llm.background.wait")
    if remaining is not None and _now() + remaining < expires_at:
        expires_at = _now() + remaining
        limit = "execution_deadline"
    return expires_at, limit


def finish_background(
    response: Any,
    *,
    label: str,
    attempt: int,
    model_name: str,
    provider: str,
    record_usage: Callable[..., None],
    emit_marker: Callable[..., None],
) -> Any:
    """Wait for a submitted background response; pass every other response through.

    Writes the submission ledger row first, so a request orphaned by a process
    kill remains discoverable by its response id. On wait expiry the response is
    cancelled, its usage row recorded, and ``BackgroundWaitExpired`` raised.
    """
    if not isinstance(response, BackgroundTicket):
        return response
    try:
        emit_marker(
            label=f"{label}.background_submitted",
            extra={
                "attempt": attempt,
                "status": "background_submitted",
                "model": model_name,
                "provider": provider,
                **background_metadata(response.config, response.response_id, response.raw),
            },
        )
        expires_at, limit = _expiry(response)
        # Terminal poll outcomes (completion, refusal, wait expiry) cancel or
        # finish the job themselves and return normally.
        completion = response.client.await_background(response, expires_at)
    except BaseException:
        # Any in-process failure from the marker through polling (ledger error,
        # deadline, KeyboardInterrupt, cancellation, a bug) stops the accepted
        # server-side work rather than leave it billing.
        response.cancel_quietly()
        raise
    if completion.transport_metadata.get("background_status") == WAIT_EXPIRED:
        waited = _now() - response.accepted_at
        completion.transport_metadata["background_waited_seconds"] = round(waited, 3)
        record_usage(response=completion, extra={"attempt": attempt, "status": WAIT_EXPIRED})
        expired = (
            BackgroundDeadlineExpired if limit == "execution_deadline" else BackgroundWaitExpired
        )
        raise expired(
            label=label,
            response_id=response.response_id,
            completion_window=response.config.completion_window,
            waited_seconds=waited,
            limit=limit,
        )
    return completion


# --------------------------------------------------------------------------
# Asynchronous poll loop (runs on the PydanticClient's request-local loop)
# --------------------------------------------------------------------------


def _refused(
    ticket: BackgroundTicket,
    raw: dict[str, Any],
    message: str,
    status: str,
    *,
    cancel: str | None = None,
) -> Completion:
    from agent.llm_transport.runtime import refused_completion

    completion = refused_completion(raw, message)
    completion.transport_metadata = {
        **ticket.metadata,
        **background_metadata(ticket.config, ticket.response_id, raw, status=status),
    }
    if cancel is not None:
        completion.transport_metadata["background_cancel"] = cancel
    return completion


async def _cancel(model: Model, ticket: BackgroundTicket) -> str:
    try:
        await model.cancel_suspended_response(ticket.suspended)
    except Exception:  # Best effort: the caller already has a terminal outcome to report.
        return "cancel_failed"
    return "cancelled"


async def cancel(ticket: BackgroundTicket) -> str:
    """Cancel one pending background response on a request-local client."""
    from agent.llm_transport.providers import build_model

    async with httpx2.AsyncClient(timeout=ticket.client.timeout) as http:
        return await _cancel(build_model(ticket.client, ticket.model_id, http), ticket)


def _is_transient(exc: BaseException) -> bool:
    from pydantic_ai.exceptions import ModelConnectionError, ModelHTTPError

    if isinstance(exc, ModelHTTPError):
        return exc.status_code == 429 or exc.status_code >= 500
    return isinstance(exc, (ModelConnectionError, httpx2.TimeoutException, httpx2.RequestError))


async def await_completion(ticket: BackgroundTicket, expires_at: float) -> Completion:
    """Poll until a terminal state or ``expires_at``; never resubmit the request."""
    from agent.llm_transport.providers import build_model

    capture = AccountingCapture()
    capture.raw.update(ticket.raw)
    async with httpx2.AsyncClient(
        timeout=ticket.client.timeout, event_hooks={"response": [capture]}
    ) as http:
        model = build_model(ticket.client, ticket.model_id, http)
        # In-process failures propagate to finish_background, which cancels once.
        return await _poll(model, ticket, capture.raw, expires_at)


async def _poll(
    model: Model, ticket: BackgroundTicket, raw: dict[str, Any], expires_at: float
) -> Completion:
    from pydantic_ai.exceptions import (
        ModelAPIError,
        SuspendedResponseExpired,
        UnexpectedModelBehavior,
    )

    from agent.llm_transport.responses import normalize
    from agent.llm_transport.runtime import continue_background

    interval = POLL_INITIAL_SECONDS
    while True:
        remaining = expires_at - _now()
        if remaining <= 0:
            outcome = await _cancel(model, ticket)
            return _refused(
                ticket,
                raw,
                f"Background response {ticket.response_id} exceeded its wait limit ({outcome})",
                WAIT_EXPIRED,
                cancel=outcome,
            )
        await asyncio.sleep(min(interval, remaining))
        interval = min(interval * 2, POLL_MAX_SECONDS)
        remaining = expires_at - _now()
        if remaining <= 0:
            continue
        try:
            response = await continue_background(
                model, ticket, min(ticket.client.timeout, remaining)
            )
        except SuspendedResponseExpired:
            # The provider no longer has the job (404): nothing left to cancel.
            return _refused(
                ticket, raw, "Background response is no longer retrievable", "not_retrievable"
            )
        except UnexpectedModelBehavior:
            # Cancel before refusing: the caller may resubmit, and an accepted
            # job left running would bill twice. Cancel is idempotent.
            outcome = await _cancel(model, ticket)
            return _refused(
                ticket,
                raw,
                "Background response could not be decoded",
                "undecodable",
                cancel=outcome,
            )
        except Exception as exc:
            if _is_transient(exc):
                continue
            if isinstance(exc, ModelAPIError):
                outcome = await _cancel(model, ticket)
                return _refused(
                    ticket, raw, f"Background response failed: {exc}", "failed", cancel=outcome
                )
            raise
        if response.state == "suspended":
            ticket.suspended = response
            continue
        status = (response.provider_details or {}).get("finish_reason")
        metadata = {
            **ticket.metadata,
            **background_metadata(
                ticket.config,
                ticket.response_id,
                raw,
                status=status if isinstance(status, str) else "completed",
            ),
        }
        return normalize(
            response,
            raw,
            json_mode=ticket.json_mode,
            tool_names=ticket.tool_names,
            metadata=metadata,
        )
