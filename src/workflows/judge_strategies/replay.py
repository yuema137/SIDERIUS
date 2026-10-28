"""``replay_llm_strategy``: re-derive a recorded outcome without contacting a provider.

The invocation's ``strategy.json`` is anchored by the digest B6 recorded. Every
call is re-planned and its request re-derived from the invocation, then verified
against its anchored evidence (request, prompt, response schema, route, payload
admissibility); the pure decision is re-run and must equal the recorded outcome.
Unaccounted files under the evidence directory refuse.
"""

import hashlib
from pathlib import Path

from pydantic import ValidationError

from agent.judge.evidence import JudgeEvidenceError, verify_call_evidence
from agent.schemas.data_analysis.common import canonical_json_bytes
from agent.schemas.judge import JudgeCallEvidence, JudgeRoutes

from .kinds import implemented_kind
from .models import (
    STRATEGY_EVIDENCE_FILE,
    StrategyError,
    StrategyEvidence,
    StrategyInvocation,
    StrategyResult,
    invocation_sha256,
)
from .plan import call_path, call_request, decide, strategy_route


def _read_anchored(path: Path, expected_sha256: str) -> StrategyEvidence:
    try:
        data = path.read_bytes()
    except FileNotFoundError as error:
        raise StrategyError(f"strategy evidence is missing: {path}") from error
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise StrategyError(f"strategy evidence digest differs from its anchor: {path}")
    try:
        record = StrategyEvidence.model_validate_json(data)
    except ValidationError as error:
        raise StrategyError(f"strategy evidence is malformed: {path}") from error
    if canonical_json_bytes(record) != data:
        raise StrategyError(f"strategy evidence is not canonical: {path}")
    return record


def _require_accounted(evidence_dir: Path, accounted: set[Path]) -> None:
    for path in sorted(evidence_dir.rglob("*")):
        if not path.is_dir() and path not in accounted:
            raise StrategyError(f"strategy evidence file not accounted for by replay: {path}")


def replay_llm_strategy(
    invocation: StrategyInvocation, routes: JudgeRoutes, *, expected_sha256: str
) -> StrategyResult:
    """The recorded result of ``invocation``, verified; never calls a provider.

    ``expected_sha256`` is the evidence digest B6 recorded (``StrategyResult``).
    Raises ``StrategyError`` on any missing, foreign, reordered, truncated,
    extended, tampered or unaccounted evidence, or a re-derived outcome mismatch.
    """
    strategy = invocation.strategy
    kind = implemented_kind(strategy)
    route = strategy_route(strategy, routes)
    evidence_dir = invocation.evidence_dir
    strategy_path = evidence_dir / STRATEGY_EVIDENCE_FILE
    record = _read_anchored(strategy_path, expected_sha256)
    digest = invocation_sha256(invocation)
    if record.invocation_sha256 != digest:
        raise StrategyError("strategy evidence belongs to another invocation")
    bound = kind.call_bound(strategy, len(invocation.items))
    if (record.strategy_kind, record.static_call_bound) != (strategy.kind, bound):
        raise StrategyError("strategy evidence kind or call bound differs from the invocation")
    calls: tuple[JudgeCallEvidence, ...] = ()
    accounted = {strategy_path}
    for anchor in record.calls:
        if calls and calls[-1].status != "decided":
            raise StrategyError("strategy evidence records a call after a failed call")
        planned = kind.plan_call(invocation, len(calls))
        if planned is None:
            raise StrategyError("strategy evidence records more calls than the strategy plans")
        path = call_path(evidence_dir, len(calls), planned.role)
        try:
            evidence = verify_call_evidence(
                path,
                expected_sha256=anchor,
                request=call_request(digest, planned, calls),
                template=planned.template,
                route=route,
            )
        except (JudgeEvidenceError, FileNotFoundError) as error:
            raise StrategyError(f"strategy call {len(calls)} is refused: {error}") from error
        calls += (evidence,)
        accounted.add(path)
    if (
        calls
        and calls[-1].status == "decided"
        and kind.plan_call(invocation, len(calls)) is not None
    ):
        raise StrategyError("strategy evidence ends before the planned call chain is complete")
    if decide(kind, invocation, calls) != record.outcome:
        raise StrategyError("re-derived strategy outcome differs from the recorded outcome")
    _require_accounted(evidence_dir, accounted)
    return StrategyResult(outcome=record.outcome, evidence_sha256=expected_sha256)
