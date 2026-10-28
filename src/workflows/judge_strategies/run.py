"""``run_llm_strategy``: the only function in this package that contacts a provider.

Each call goes through the B2-1 judge call (``agent.judge.call.run_judge_call``),
which publishes its own write-once evidence. The chain stops at the first failed
call. The invocation's write-once ``strategy.json`` then anchors every call in
order together with the decided outcome; B6 records its digest.
"""

from collections.abc import Callable
from pathlib import Path

from agent.judge.call import (
    JudgeBridge,
    JudgeRunContext,
    bridge_for_route,
    emit_judge_marker,
    run_judge_call,
)
from agent.judge.evidence import evidence_sha256
from agent.schemas.data_analysis.common import canonical_json_bytes, canonical_sha256
from agent.schemas.judge import JudgeCallEvidence, JudgeRoute, JudgeRoutes
from core.durable_io import publish_bytes_write_once

from .kinds import implemented_kind
from .models import (
    STRATEGY_EVIDENCE_FILE,
    StrategyError,
    StrategyEvidence,
    StrategyInvocation,
    StrategyResult,
    invocation_sha256,
)
from .plan import call_path, call_request, decide, next_call, strategy_route


def _require_fresh(evidence_dir: Path) -> None:
    if evidence_dir.exists() and any(evidence_dir.iterdir()):
        raise StrategyError(f"strategy evidence already exists; never reused: {evidence_dir}")


def run_llm_strategy(
    invocation: StrategyInvocation,
    routes: JudgeRoutes,
    *,
    context: JudgeRunContext,
    bridge_factory: Callable[[JudgeRoute], JudgeBridge] = bridge_for_route,
) -> StrategyResult:
    """Run one invocation's call chain, publish its evidence, return the outcome.

    Raises ``StrategyError`` before any provider contact for an unimplemented kind,
    an unconfigured route slot, a usage context of another iteration, a call bound
    above ``max_calls`` or a non-empty ``evidence_dir``. Call failures are evidence:
    the outcome is ``failed`` or, with a declared fallback, ``fallback``.
    """
    strategy = invocation.strategy
    kind = implemented_kind(strategy)
    route = strategy_route(strategy, routes)
    if context.iteration != invocation.iteration:
        raise StrategyError("usage context iteration differs from the invocation iteration")
    bound = kind.call_bound(strategy, len(invocation.items))
    if bound > strategy.max_calls:
        raise StrategyError(
            f"{strategy.kind} needs {bound} calls; max_calls is {strategy.max_calls}"
        )
    _require_fresh(invocation.evidence_dir)
    digest = invocation_sha256(invocation)
    calls: tuple[JudgeCallEvidence, ...] = ()
    while (planned := next_call(kind, invocation, calls)) is not None:
        evidence = run_judge_call(
            call_request(digest, planned, calls),
            template=planned.template,
            route=route,
            context=context,
            evidence_path=call_path(invocation.evidence_dir, len(calls), planned.role),
            max_calls=bound,
            bridge_factory=bridge_factory,
        )
        calls += (evidence,)
        if evidence.status != "decided":
            break
    record = StrategyEvidence(
        invocation_sha256=digest,
        strategy_kind=strategy.kind,
        static_call_bound=bound,
        calls=tuple(evidence_sha256(call) for call in calls),
        outcome=decide(kind, invocation, calls),
    )
    data = canonical_json_bytes(record)
    publish_bytes_write_once(str(invocation.evidence_dir / STRATEGY_EVIDENCE_FILE), data)
    if record.outcome.status == "skipped":
        # Telemetry only (best effort): the skipped invocation is visible in the usage ledger.
        emit_judge_marker(
            route,
            context,
            label=f"judge.{strategy.kind.split('/')[0]}.skipped",
            extra={"adaptor_id": invocation.adaptor_id, "items": len(invocation.items)},
            bridge_factory=bridge_factory,
        )
    return StrategyResult(outcome=record.outcome, evidence_sha256=canonical_sha256(record))
