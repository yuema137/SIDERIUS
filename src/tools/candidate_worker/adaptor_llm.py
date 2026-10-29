"""Execute and replay an adaptor whose COMBINE is an LLM kind (B6-8a).

B2 (``workflows.judge_strategies``) owns the calls, evidence, folds and readback;
B6 (``workflows.adaptors``) owns admissibility, SELECT, DISTRIBUTE and the
deterministic fallback. This module only builds the invocation from verified
inputs, maps the B2 outcome onto the B6 core, and anchors the strategy evidence in
the adaptor record. The worker runs the strategy; the verifier replays it from the
recorded anchor and never contacts a provider.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from agent.judge import call as judge_call
from agent.judge.call import JudgeRunContext
from agent.schemas.judge import JudgeRoutes
from agent.schemas.judge_task import JudgeTaskDeclarations, RubricRefError, resolve_rubric_ref
from agent.schemas.proposal import ProposalOutput, mint_candidate_id
from core.run_invariants import load_run_invariants
from workflows.adaptors import (
    AdaptorInputRef,
    AdaptorItem,
    AdaptorOutcome,
    AdaptorRecord,
    Combined,
    RankEntry,
    Ranking,
    Unit,
    build_adaptor_record,
    combine,
)
from workflows.adaptors.combine import whole_units
from workflows.adaptors.record import StrategyEvidenceRef
from workflows.adaptors.run import admissible_items, select_and_distribute
from workflows.custom_adaptors.contracts import native_type
from workflows.definition import AdaptorInstance
from workflows.definition.adaptor_strategies import derive_cardinality
from workflows.definition.adaptor_validation import output_contract
from workflows.definition.llm_strategies import (
    LLM_STRATEGY_TYPES,
    LLMStrategy,
    RubricRankStrategy,
)
from workflows.judge_strategies import (
    CombinedItems,
    ItemRanking,
    StrategyError,
    StrategyInvocation,
    StrategyOutcome,
    replay_llm_strategy,
    run_llm_strategy,
    strategy_call_bound,
    strategy_items,
)

from .layout import adaptor_dir

if TYPE_CHECKING:
    from .models import CandidateRunReceipt, CandidateRunRequest

#: Rubric source of ``rubric-rank/v1`` (decision D3): the task composition only.
RUBRIC_SOURCE = "the task composition manifest's `rubrics:` section"


class UnsupportedRubricSource(StrategyError):
    """A strategy names a rubric the task does not declare (experiment rubrics are unsupported)."""


@dataclass(frozen=True)
class JudgeAdaptorContext:
    """Everything an LLM COMBINE needs beyond its items; ``replay`` selects readback.

    ``replay`` maps an adaptor id to the strategy evidence digest its recorded
    adaptor record anchors; with it, the strategy is replayed, never run.
    """

    workspace: Path
    run_name: str
    run_id: str
    routes: JudgeRoutes
    declarations: JudgeTaskDeclarations | None
    replay: Mapping[str, str] | None = None


def llm_adaptors(adaptors: tuple[AdaptorInstance, ...]) -> tuple[AdaptorInstance, ...]:
    return tuple(item for item in adaptors if isinstance(item.combine, LLM_STRATEGY_TYPES))


def run_judge_routes(request: "CandidateRunRequest", initial: "CandidateRunReceipt") -> JudgeRoutes:
    """The run's judge routes and cap from its captured (digest-checked) LLM config.

    Worker and verifier read the same immutable launch snapshot. When the run also
    holds a workspace run lock with judge routes (a training run), they must agree.
    """
    from tools.workflow_preview.config import parse_config
    from workflows.llm_config import WorkflowLLMConfig, locked_judge_routes

    from .fanout_inputs import captured_contents

    contents = captured_contents(request, Path(initial.workspace), iteration=1, verify=True)
    config = (
        parse_config(contents["llm_config"])
        if "llm_config" in contents
        else WorkflowLLMConfig.default()
    )
    routes = locked_judge_routes(config.judge)
    if routes is None:
        raise StrategyError("an LLM COMBINE kind requires WorkflowLLMConfig.judge routes")
    invariants = load_run_invariants(initial.workspace)
    locked = None if invariants is None else invariants.judge_routes
    if locked is not None and locked != routes:
        raise StrategyError("the captured judge routes differ from the run lock")
    return routes


def _strategy(adaptor: AdaptorInstance) -> LLMStrategy:
    strategy = adaptor.combine
    if not isinstance(strategy, LLM_STRATEGY_TYPES):
        raise StrategyError(f"adaptor {adaptor.id} has a deterministic COMBINE")
    return strategy


def admit_llm_adaptors(
    adaptors: tuple[AdaptorInstance, ...],
    routes: JudgeRoutes,
    declarations: JudgeTaskDeclarations | None,
    *,
    bodies: int,
    stop_calls: int,
) -> None:
    """Launch-time static checks before any effect (decisions D3, D4).

    Every rubric resolves against the task's rubrics, task guidance exists where
    declared, every route slot is configured, and the run's static judge call bound
    ``Σ(adaptor static_call_bound) × bodies + stop_calls`` fits the locked
    ``max_judge_calls`` (an absent cap refuses).
    """
    total = stop_calls
    for adaptor in adaptors:
        strategy = _strategy(adaptor)
        _rubric(strategy, declarations)
        _guidance(strategy, declarations)
        if getattr(routes, strategy.route_slot) is None:
            raise StrategyError(
                f"adaptor {adaptor.id} requires a WorkflowLLMConfig.judge.{strategy.route_slot} route"
            )
        capacity = sum(len(binding.sources) for binding in adaptor.bindings)
        total += strategy_call_bound(strategy, capacity) * bodies
    if routes.max_judge_calls is None:
        raise StrategyError("LLM COMBINE kinds require WorkflowLLMConfig.judge.max_judge_calls")
    if total > routes.max_judge_calls:
        raise StrategyError(
            f"the run may make {total} judge calls; max_judge_calls is {routes.max_judge_calls}"
        )


def judge_adaptor_context(
    request: "CandidateRunRequest",
    initial: "CandidateRunReceipt",
    declarations: JudgeTaskDeclarations | None,
) -> JudgeAdaptorContext | None:
    """The worker's context for the run's LLM COMBINE adaptors, admitted before any effect.

    ``None`` when no adaptor has an LLM COMBINE. The static call sum covers every
    body of an authored loop plus its JudgeStop bound (``loop_stop.judge_call_bound``).
    """
    from .loop_stop import judge_call_bound

    definition = request.preview.document.definition
    adaptors = llm_adaptors(definition.adaptors)
    if not adaptors:
        return None
    routes = run_judge_routes(request, initial)
    loop = definition.loop
    admit_llm_adaptors(
        adaptors,
        routes,
        declarations,
        bodies=1 if loop is None else loop.final_iteration,
        stop_calls=0 if loop is None else judge_call_bound(loop),
    )
    return JudgeAdaptorContext(
        workspace=Path(initial.workspace),
        run_name=initial.run_name,
        run_id=initial.run_id,
        routes=routes,
        declarations=declarations,
    )


def replay_context(
    request: "CandidateRunRequest", initial: "CandidateRunReceipt", records: Mapping[str, str]
) -> JudgeAdaptorContext | None:
    """The verifier's context: judge declarations recomposed from the task manifest and the
    strategy evidence anchors of the recorded adaptor records (``records``: id -> anchor)."""
    from workflows.task_composition import compose_judge_declarations

    if not llm_adaptors(request.preview.document.definition.adaptors):
        return None
    manifest = next(item.path for item in request.files if item.reference == "task.manifest")
    return JudgeAdaptorContext(
        workspace=Path(initial.workspace),
        run_name=initial.run_name,
        run_id=initial.run_id,
        routes=run_judge_routes(request, initial),
        declarations=compose_judge_declarations(manifest),
        replay=records,
    )


def _rubric(strategy: LLMStrategy, declarations: JudgeTaskDeclarations | None):
    if not isinstance(strategy, RubricRankStrategy):
        return None
    rubrics = () if declarations is None else declarations.rubrics
    try:
        return resolve_rubric_ref(strategy.rubric, rubrics)
    except RubricRefError as error:
        raise UnsupportedRubricSource(
            f"rubric {strategy.rubric.id!r} version {strategy.rubric.version!r} must be "
            f"declared in {RUBRIC_SOURCE} ({error.reason}); experiment-owned rubrics are "
            "not supported"
        ) from error


def _guidance(strategy: LLMStrategy, declarations: JudgeTaskDeclarations | None):
    if strategy.guidance != "task_blocks":
        return None
    blocks = None if declarations is None else declarations.blocks
    if blocks is None:
        raise StrategyError(
            f"{strategy.kind} declares guidance 'task_blocks' but the task declares no judge_blocks"
        )
    return blocks


def judge_evidence_dir(workspace: Path, adaptor_id: str, iteration: int) -> Path:
    return adaptor_dir(workspace, iteration=iteration) / f"{adaptor_id}.judge"


def decide_llm(
    adaptor: AdaptorInstance,
    items: tuple[AdaptorItem, ...],
    *,
    iteration: int,
    context: JudgeAdaptorContext,
) -> tuple[AdaptorOutcome, AdaptorRecord]:
    """Run (worker) or replay (verifier) the LLM COMBINE, then SELECT and DISTRIBUTE."""
    strategy = _strategy(adaptor)
    admissions, admissible = admissible_items(items)
    record_args = {
        "adaptor_id": adaptor.id,
        "iteration": iteration,
        "combine": strategy,
        "select": adaptor.select,
        "distribute": adaptor.distribute,
    }
    if not admissible:  # B6 never invokes B2 with zero admissible items
        outcome = AdaptorOutcome(
            status="rejected", reason="no_admissible_input", admissions=admissions
        )
        return outcome, build_adaptor_record(**record_args, outcome=outcome)
    evidence_dir = judge_evidence_dir(context.workspace, adaptor.id, iteration)
    invocation = StrategyInvocation(
        adaptor_id=adaptor.id,
        iteration=iteration,
        strategy=strategy,
        items=strategy_items(admissible),
        output_contract=output_contract(adaptor),
        expected_count=derive_cardinality(adaptor.select, adaptor.distribute),
        rubric=_rubric(strategy, context.declarations),
        task_guidance=_guidance(strategy, context.declarations),
        evidence_dir=evidence_dir,
    )
    if context.replay is None:
        result = run_llm_strategy(
            invocation,
            context.routes,
            context=JudgeRunContext(
                workspace=context.workspace,
                iteration=iteration,
                run_name=context.run_name,
                run_id=context.run_id,
            ),
            # Resolved at call time, so the provider owner stays the single bridge factory.
            bridge_factory=lambda route: judge_call.bridge_for_route(route),
        )
    else:
        result = replay_llm_strategy(
            invocation, context.routes, expected_sha256=context.replay[adaptor.id]
        )
    outcome = _outcome(adaptor, result.outcome, admissible, admissions)
    anchor = StrategyEvidenceRef(
        path=f"{evidence_dir.name}/strategy.json", sha256=result.evidence_sha256
    )
    record = build_adaptor_record(
        **record_args,
        outcome=outcome,
        fallback=result.outcome.fallback_combine,
        strategy_evidence=anchor,
    )
    return outcome, record


def _outcome(
    adaptor: AdaptorInstance,
    decided: StrategyOutcome,
    admissible: tuple[AdaptorItem, ...],
    admissions: tuple,
) -> AdaptorOutcome:
    """Map a B2 outcome onto the B6 core: rank, synthesize, fall back or fail."""
    strategy = _strategy(adaptor)
    if decided.status == "failed":
        return AdaptorOutcome(status="failed", reason="judge_failure", admissions=admissions)
    if decided.status == "fallback":
        on_failure = strategy.on_failure
        assert on_failure != "fail"
        combined = combine(on_failure.combine, admissible, None)
    elif decided.ranking is not None:
        combined = _ranked(strategy.kind, decided.ranking, admissible)
    else:
        assert decided.combined is not None
        combined = _synthesized(strategy.kind, decided.combined, admissible)
    return select_and_distribute(
        combined,
        admissions,
        select_strategy=adaptor.select,
        distribute_strategy=adaptor.distribute,
        metric=None,
    )


def _item_id(ref: AdaptorInputRef) -> str:
    return f"{ref.port}:{ref.position}"


def _ranked(kind: str, ranking: ItemRanking, admissible: tuple[AdaptorItem, ...]) -> Combined:
    """A rubric ranking carries exact weighted means; a debate ranking is ordinal."""
    units = whole_units(admissible)
    unit_of = {_item_id(item.ref): index for index, item in enumerate(admissible)}
    scores = {score.item_id: score for score in ranking.scores or ()}
    entries = []
    for item_id in ranking.order:
        unit = unit_of[item_id]
        score = scores.get(item_id)
        entries.append(
            RankEntry(
                unit=unit,
                ref=admissible[unit].ref,
                value=None if score is None else score.weighted_mean,
                exact=None if score is None else score.weighted_mean_exact,
            )
        )
    basis = "rubric" if ranking.scores is not None else "judge"
    return Combined(
        combine_kind=kind, units=units, ranking=Ranking(basis=basis, entries=tuple(entries))
    )


def _identified(value: BaseModel, content_sha256: str) -> BaseModel:
    if isinstance(value, ProposalOutput):
        return value.model_copy(update={"candidate_id": mint_candidate_id(content_sha256)})
    return value


def _synthesized(
    kind: str, combined: CombinedItems, admissible: tuple[AdaptorItem, ...]
) -> Combined:
    """New values, re-validated by their native type, with their parents as lineage.

    A synthesized ``proposal.output`` gets its system identity here, at the adaptor
    boundary and before any implementation: ``mint_candidate_id`` of the value's
    canonical digest (the B2 evidence keeps the author-unset value).
    """
    refs = {_item_id(item.ref): item.ref for item in admissible}
    value_type = native_type(combined.contract)
    units = tuple(
        Unit(
            value=_identified(value_type.model_validate(item.value), item.value_sha256),
            element_contract=combined.contract,
            inputs=tuple(refs[parent] for parent in item.parents),
            role="synthesized",
        )
        for item in combined.items
    )
    return Combined(combine_kind=kind, units=units)
