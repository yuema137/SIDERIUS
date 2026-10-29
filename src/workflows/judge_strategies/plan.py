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
    MAX_JUDGE_PROMPT_CHARS,
    MAX_SCORED_ITEMS_PER_CALL,
    CallContent,
    CallRequest,
    CallRole,
    FailureCode,
    JudgeCallEvidence,
    JudgedItem,
    JudgeRoute,
    JudgeRoutes,
)
from workflows.definition.llm_strategies import LLMStrategy
from workflows.definition.models import InputPort

from .models import (
    CALLS_DIR,
    CombinedItems,
    ItemRanking,
    PromptBudgetExceeded,
    StrategyError,
    StrategyFailureCode,
    StrategyInvocation,
    StrategyOutcome,
    StrategyRefusal,
    invocation_sha256,
    lists_every_item,
)


@dataclass(frozen=True)
class PlannedCall:
    role: CallRole
    template: JudgeTemplate
    content: CallContent


class StrategyFoldFailure(Exception):
    """A complete, decided chain the pure fold cannot turn into a valid result."""

    def __init__(self, code: StrategyFailureCode, message: str) -> None:
        super().__init__(message)
        self.code: StrategyFailureCode = code


@dataclass(frozen=True)
class StrategyKind:
    """An implemented LLM kind: its static call bound, call planner and pure fold.

    A kind without ``output_count`` folds to an ``ItemRanking`` of every item (SELECT
    bounds it); a kind with one folds to ``output_count(strategy)`` new values
    (``CombinedItems``, ``select=all/v1``). ``min_items`` is the fewest admissible
    items the kind can run on; with fewer, no call is made and the outcome is
    ``insufficient_items``. ``precheck`` names any other strategy failure known
    before the first call (e.g. a declared primary that is not admissible).
    ``plan_call`` receives the payloads of the earlier, decided calls, so a later
    call can carry what earlier calls said.
    """

    call_bound: Callable[[Any, int], int]
    min_items: Callable[[Any], int]
    plan_call: Callable[[StrategyInvocation, tuple[Any, ...]], PlannedCall | None]
    fold: Callable[[StrategyInvocation, tuple[Any, ...]], ItemRanking | CombinedItems]
    output_count: Callable[[Any], int] | None = None  # combined kinds only
    precheck: Callable[[StrategyInvocation], StrategyFailureCode | None] | None = None
    # Kind-specific static refusals over the adaptor's declared input ports.
    admit_parameters: Callable[[Any, tuple[InputPort, ...]], tuple[StrategyRefusal, ...]] | None = (
        None
    )


def precall_failure(
    kind: StrategyKind, invocation: StrategyInvocation
) -> StrategyFailureCode | None:
    """The strategy failure that forbids every call of this invocation, or ``None``."""
    if len(invocation.items) < kind.min_items(invocation.strategy):
        return "insufficient_items"
    return None if kind.precheck is None else kind.precheck(invocation)


def next_call(
    kind: StrategyKind, invocation: StrategyInvocation, calls: tuple[JudgeCallEvidence, ...]
) -> PlannedCall | None:
    """The call after the decided ``calls``, or ``None``; never a call after a pre-call failure."""
    if precall_failure(kind, invocation) is not None:
        return None
    return kind.plan_call(invocation, tuple(call.payload for call in calls))


def require_call_capacity(invocation: StrategyInvocation) -> None:
    """Refuse (``StrategyError``) more items than one call may list, before any call."""
    strategy = invocation.strategy
    if lists_every_item(strategy) and len(invocation.items) > MAX_SCORED_ITEMS_PER_CALL:
        raise StrategyError(
            f"{strategy.kind} lists every item in one call; {len(invocation.items)} items "
            f"exceed {MAX_SCORED_ITEMS_PER_CALL} items per call"
        )


def prompt_chars(planned: PlannedCall, request: CallRequest) -> int:
    """Rendered size (system + user characters) of one planned call."""
    system, user = planned.template.render(request)
    return len(system) + len(user)


def budget_refusal(invocation: StrategyInvocation, index: int, size: int) -> PromptBudgetExceeded:
    strategy = invocation.strategy
    per_item = " or scoring='per_item'" if getattr(strategy, "scoring", None) == "batch" else ""
    return PromptBudgetExceeded(
        f"{strategy.kind} call {index} renders {size} prompt characters; the judge prompt "
        f"budget MAX_JUDGE_PROMPT_CHARS is {MAX_JUDGE_PROMPT_CHARS}. Use fewer items, shorter "
        f"task judge guidance{per_item}"
    )


def judged_items(invocation: StrategyInvocation) -> tuple[JudgedItem, ...]:
    """Every invocation item as a judge sees it, in B6 declared order."""
    return tuple(
        JudgedItem(item_id=item.item_id, projection=item.projection) for item in invocation.items
    )


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


def _decided(result: ItemRanking | CombinedItems) -> StrategyOutcome:
    ranking = result if isinstance(result, ItemRanking) else None
    combined = result if isinstance(result, CombinedItems) else None
    return StrategyOutcome(
        status="decided",
        ranking=ranking,
        combined=combined,
        failure_code=None,
        fallback_combine=None,
    )


def _failed(
    invocation: StrategyInvocation, code: FailureCode | StrategyFailureCode | None
) -> StrategyOutcome:
    """A failure under the declared ``on_failure``: ``failed``, or B6's deterministic fallback."""
    on_failure = invocation.strategy.on_failure
    fallback = None if on_failure == "fail" else on_failure.combine.kind
    return StrategyOutcome(
        status="failed" if fallback is None else "fallback",
        ranking=None,
        failure_code=code,
        fallback_combine=fallback,
    )


def decide(
    kind: StrategyKind, invocation: StrategyInvocation, calls: tuple[JudgeCallEvidence, ...]
) -> StrategyOutcome:
    """Outcome of a finished chain: the first failed call ends it under ``on_failure``."""
    precall = precall_failure(kind, invocation)
    if precall is not None:
        if calls:
            raise StrategyError(f"a strategy that fails before any call ({precall}) recorded one")
        return _failed(invocation, precall)
    failed = next((call for call in calls if call.status != "decided"), None)
    pending = None if failed is not None else next_call(kind, invocation, calls)
    if pending is not None:
        # A decided chain stops early only where its next call would exceed the budget.
        request = call_request(invocation_sha256(invocation), pending, calls)
        if not calls or prompt_chars(pending, request) <= MAX_JUDGE_PROMPT_CHARS:
            raise StrategyError("strategy evidence ends before the planned call chain is complete")
        return _failed(invocation, "prompt_too_large")
    if failed is None:
        try:
            return _decided(kind.fold(invocation, tuple(call.payload for call in calls)))
        except StrategyFoldFailure as failure:
            return _failed(invocation, failure.code)
    if failed is not calls[-1]:
        raise StrategyError("a strategy call chain continued after a failed call")
    return _failed(invocation, failed.failure_code)
