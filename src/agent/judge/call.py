"""The single effectful judge call: render, bridge call, validate, publish once."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from pydantic import Field, ValidationError

from agent.judge.template import JudgeTemplate
from agent.schemas.data_analysis.common import canonical_json_bytes, canonical_sha256
from agent.schemas.judge import CallRequest, JudgeCallEvidence, JudgeModel, JudgeRoute
from core.durable_io import publish_bytes_write_once
from core.execution_deadline import remaining_seconds


class JudgeBridge(Protocol):
    def set_run_context(
        self, *, workspace: Path, iter: int, run_name: str, run_id: str
    ) -> None: ...

    def generate(self, system_prompt: str, user_prompt: str, *, label: str) -> Any: ...

    def emit_marker(self, *, label: str, extra: dict[str, Any] | None = None) -> None: ...


class JudgeRunContext(JudgeModel):
    """Usage-accounting binding; deliberately outside every hashed request."""

    workspace: Path
    iteration: int = Field(ge=0)
    run_name: str = Field(min_length=1)
    run_id: str = Field(min_length=1)


class JudgeCallRefused(RuntimeError):
    """The call was refused before any provider contact; nothing was written."""


class JudgeEvidenceConflict(RuntimeError):
    """Another writer published evidence at this path after admission.

    The provider call has already happened and its usage rows are recorded;
    the record built by this call was not published.
    """


def bridge_for_route(route: JudgeRoute) -> JudgeBridge:
    from agent.llm_bridge import LLMBridge

    return LLMBridge(
        provider=route.provider,
        model_id=route.model_id,
        max_retries=route.max_retries,
        reasoning_effort=route.reasoning_effort,
        max_output_tokens=route.max_output_tokens,
    )


def _admit(
    request: CallRequest, context: JudgeRunContext, max_calls: int, evidence_path: Path
) -> None:
    if request.content.kind == "stop" and context.iteration != request.content.iteration:
        raise JudgeCallRefused("usage context iteration differs from the judged iteration")
    if max_calls <= 0:
        raise JudgeCallRefused("a judge call requires a positive max_calls cap")
    if request.call_index >= max_calls:
        raise JudgeCallRefused(
            f"judge call {request.call_index} exceeds the declared cap of {max_calls} calls"
        )
    if evidence_path.exists():
        raise JudgeCallRefused(f"judge evidence already exists; never reused: {evidence_path}")


def _failure(code: str, message: str) -> dict[str, Any]:
    status = "timed_out" if code == "deadline" else "failed"
    return {
        "status": status,
        "payload": None,
        "failure_code": code,
        "failure_message": message[:2000],
    }


def _described(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _bound_bridge(
    route: JudgeRoute,
    context: JudgeRunContext,
    bridge_factory: Callable[[JudgeRoute], JudgeBridge],
) -> JudgeBridge:
    remaining_seconds("judge.before_request")  # ExecutionDeadlineExceeded propagates
    try:
        bridge = bridge_factory(route)
        bridge.set_run_context(
            workspace=context.workspace,
            iter=context.iteration,
            run_name=context.run_name,
            run_id=context.run_id,
        )
    except Exception as exc:
        raise JudgeCallRefused(f"judge bridge unavailable: {_described(exc)}") from exc
    return bridge


def _call(
    template: JudgeTemplate,
    request: CallRequest,
    bridge: JudgeBridge,
    prompt: tuple[str, str],
) -> dict[str, Any]:
    try:
        raw = bridge.generate(*prompt, label=template.usage_label)
        remaining_seconds("judge.response")
    except TimeoutError as exc:
        return _failure("deadline", _described(exc))
    except Exception as exc:  # provider failure after the route's finite retries
        return _failure("provider_error", _described(exc))
    try:
        payload = template.response_model.model_validate_json(json.dumps(raw))
    except ValidationError as exc:
        return _failure("invalid_payload", _described(exc))
    try:
        refusal = template.check_payload(request, payload) if template.check_payload else None
    except Exception as exc:
        return _failure("inadmissible_choice", _described(exc))
    if refusal is not None:
        return _failure("inadmissible_choice", refusal)
    return {"status": "decided", "payload": payload, "failure_code": None, "failure_message": None}


def emit_judge_marker(
    route: JudgeRoute,
    context: JudgeRunContext,
    *,
    label: str,
    extra: dict[str, Any],
    bridge_factory: Callable[[JudgeRoute], JudgeBridge] = bridge_for_route,
) -> bool:
    """Best-effort usage marker row for a skipped judge call (no provider call, no evidence).

    The marker owner is ``LLMBridge.emit_marker``, which only exists on a bridge bound
    to the run's usage context, and building a provider bridge can fail (for example a
    missing credential). A marker is telemetry, so this never checks the execution
    deadline and never raises an ``Exception``: a failure is reported on stderr and
    ``False`` is returned, leaving the caller's run outcome unchanged.
    """
    try:
        bridge = bridge_factory(route)
        bridge.set_run_context(
            workspace=context.workspace,
            iter=context.iteration,
            run_name=context.run_name,
            run_id=context.run_id,
        )
        bridge.emit_marker(label=label, extra=extra)
    except Exception as exc:
        print(f"[judge] marker {label!r} not recorded: {_described(exc)}", file=sys.stderr)
        return False
    return True


def run_judge_call(
    request: CallRequest,
    *,
    template: JudgeTemplate,
    route: JudgeRoute,
    context: JudgeRunContext,
    evidence_path: Path,
    max_calls: int,
    bridge_factory: Callable[[JudgeRoute], JudgeBridge] = bridge_for_route,
) -> JudgeCallEvidence:
    """Make one bounded call and publish its write-once evidence.

    Provider, deadline, payload and admissibility failures are recorded as
    evidence with a ``failure_code``; the consumer's declared ``on_failure``
    decides what a failed call means. ``JudgeCallRefused`` is raised before
    any provider contact and without writing. One writer per evidence path is
    assumed; a concurrent publish raises ``JudgeEvidenceConflict``.
    """
    _admit(request, context, max_calls, evidence_path)
    rendered = template.render(request)
    identity = template.identity(request)
    bridge = _bound_bridge(route, context, bridge_factory)
    outcome = _call(template, request, bridge, rendered)
    evidence = JudgeCallEvidence(
        request=request,
        request_sha256=canonical_sha256(request),
        prompt=identity,
        route=route,
        usage_label=template.usage_label,
        **outcome,
    )
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        publish_bytes_write_once(str(evidence_path), canonical_json_bytes(evidence))
    except FileExistsError as exc:
        raise JudgeEvidenceConflict(
            f"judge evidence published concurrently: {evidence_path}"
        ) from exc
    return evidence
