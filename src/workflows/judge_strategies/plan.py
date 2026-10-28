"""The call chain shared by run and replay: planned calls, their requests, the decision.

Run and replay derive every request from the same pure planner and decide the
outcome with the same pure function, so a replay that re-derives a different
request, chain or outcome refuses instead of diverging.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.judge.evidence import chain_prior_turns
from agent.judge.template import JudgeTemplate
from agent.schemas.judge import (
    CallContent,
    CallRequest,
    CallRole,
    JudgeCallEvidence,
    JudgeRoute,
    JudgeRoutes,
)
from workflows.definition.llm_strategies import LLMStrategy

from .models import (
    CALLS_DIR,
    ItemRanking,
    StrategyError,
    StrategyInvocation,
    StrategyOutcome,
)


@dataclass(frozen=True)
class PlannedCall:
    role: CallRole
    template: JudgeTemplate
    content: CallContent


@dataclass(frozen=True)
class StrategyKind:
    """An implemented LLM kind: its static call bound, call planner and pure fold."""

    call_bound: Callable[[Any, int], int]
    plan_call: Callable[[StrategyInvocation, int], PlannedCall | None]
    fold: Callable[[StrategyInvocation, tuple[Any, ...]], ItemRanking]


def strategy_route(strategy: LLMStrategy, routes: JudgeRoutes) -> JudgeRoute:
    """The locked route of the strategy's declared slot; an unconfigured slot refuses."""
    route = routes.aggregate if strategy.route_slot == "aggregate" else routes.debate
    if route is None:
        raise StrategyError(
            f"{strategy.kind} requires a WorkflowLLMConfig.judge.{strategy.route_slot} route"
        )
    return route


def call_request(
    invocation_digest: str, planned: PlannedCall, earlier: tuple[JudgeCallEvidence, ...]
) -> CallRequest:
    """The hashed request of the call after ``earlier``; it covers every earlier call."""
    return CallRequest(
        invocation_sha256=invocation_digest,
        call_role=planned.role,
        call_index=len(earlier),
        prior_turns=chain_prior_turns(earlier),
        content=planned.content,
    )


def call_path(evidence_dir: Path, index: int, role: CallRole) -> Path:
    return evidence_dir / CALLS_DIR / f"{index:03d}_{role}.json"


def decide(
    kind: StrategyKind, invocation: StrategyInvocation, calls: tuple[JudgeCallEvidence, ...]
) -> StrategyOutcome:
    """Outcome of a finished chain: the first failed call ends it under ``on_failure``."""
    failed = next((call for call in calls if call.status != "decided"), None)
    if failed is None:
        payloads = tuple(call.payload for call in calls)
        return StrategyOutcome(
            status="decided",
            ranking=kind.fold(invocation, payloads),
            failure_code=None,
            fallback_combine=None,
        )
    if failed is not calls[-1]:
        raise StrategyError("a strategy call chain continued after a failed call")
    on_failure = invocation.strategy.on_failure
    fallback = None if on_failure == "fail" else on_failure.combine.kind
    return StrategyOutcome(
        status="failed" if fallback is None else "fallback",
        ranking=None,
        failure_code=failed.failure_code,
        fallback_combine=fallback,
    )
