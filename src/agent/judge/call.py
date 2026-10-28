"""The single effectful judge call: render, bridge call, validate, publish once."""

from __future__ import annotations

import json
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


class JudgeRunContext(JudgeModel):
    """Usage-accounting binding; deliberately outside every hashed request."""

    workspace: Path
    iteration: int = Field(ge=0)
    run_name: str = Field(min_length=1)
    run_id: str = Field(min_length=1)


class JudgeCallRefused(RuntimeError):
    """The call was refused before any provider contact; nothing was written."""


def bridge_for_route(route: JudgeRoute) -> JudgeBridge:
    from agent.llm_bridge import LLMBridge

    return LLMBridge(
        provider=route.provider,
        model_id=route.model_id,
        max_retries=route.max_retries,
        reasoning_effort=route.reasoning_effort,
        max_output_tokens=route.max_output_tokens,
    )


def _admit(request: CallRequest, max_calls: int, evidence_path: Path) -> None:
    if max_calls <= 0:
        raise JudgeCallRefused("a judge call requires a positive max_calls cap")
    if request.call_index >= max_calls:
        raise JudgeCallRefused(
            f"judge call {request.call_index} exceeds the declared cap of {max_calls} calls"
        )
    if evidence_path.exists():
        raise JudgeCallRefused(f"judge evidence already exists; never reused: {evidence_path}")


def _failure(code: str, exc: BaseException) -> dict[str, Any]:
    status = "timed_out" if code == "deadline" else "failed"
    message = f"{type(exc).__name__}: {exc}"[:2000]
    return {"status": status, "payload": None, "failure_code": code, "failure_message": message}


def _call(template: JudgeTemplate, bridge: JudgeBridge, system: str, user: str) -> dict[str, Any]:
    try:
        raw = bridge.generate(system, user, label=template.usage_label)
        remaining_seconds("judge.response")
    except TimeoutError as exc:
        return _failure("deadline", exc)
    except Exception as exc:  # provider failure after the route's finite retries
        return _failure("provider_error", exc)
    try:
        payload = template.response_model.model_validate_json(json.dumps(raw))
    except ValidationError as exc:
        return _failure("invalid_payload", exc)
    return {"status": "decided", "payload": payload, "failure_code": None, "failure_message": None}


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

    Provider, deadline and payload failures are recorded as evidence with a
    ``failure_code``; the consumer's declared ``on_failure`` decides what a
    failed call means. Refusals (cap, existing evidence) raise before any call.
    """
    _admit(request, max_calls, evidence_path)
    system, user = template.render(request)
    prompt = template.identity(request)
    remaining_seconds("judge.before_request")
    bridge = bridge_factory(route)
    bridge.set_run_context(
        workspace=context.workspace,
        iter=context.iteration,
        run_name=context.run_name,
        run_id=context.run_id,
    )
    outcome = _call(template, bridge, system, user)
    evidence = JudgeCallEvidence(
        request=request,
        request_sha256=canonical_sha256(request),
        prompt=prompt,
        route=route,
        usage_label=template.usage_label,
        **outcome,
    )
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    publish_bytes_write_once(str(evidence_path), canonical_json_bytes(evidence))
    return evidence
