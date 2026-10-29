"""B2-6 LLM strategy framework and ``rubric-rank/v1``.

Each test names the defect it catches. No provider is contacted: a stub bridge
returns rubric verdicts, so no API key is needed.
"""

import ast
import json
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from agent.judge.call import JudgeRunContext
from agent.judge.rubric_template import RUBRIC_TEMPLATE
from agent.schemas.data_analysis.common import canonical_json_bytes, canonical_sha256
from agent.schemas.judge import (
    CallRequest,
    ItemProjection,
    JudgedItem,
    JudgeRoute,
    JudgeRoutes,
    ProjectedField,
    RubricScoringRequest,
)
from agent.schemas.judge_task import JudgeTaskBlocks, RubricCriterion, RubricSpec, rubric_ref
from agent.schemas.literature_review import LiteratureReviewOutput
from agent.schemas.proposal import AgentCard, ExpertContextItem
from workflows.adaptors import (
    AdaptorInputRef,
    AdaptorItem,
    AdaptorStrategyError,
    Combined,
    RankEntry,
    Ranking,
    Unit,
    select,
)
from workflows.definition.adaptor_strategies import (
    AllSelect,
    CardinalityBound,
    Fallback,
    FirstAdmissibleSelect,
    PassCombine,
    ThresholdSelect,
    TopKSelect,
)
from workflows.definition.llm_strategies import LLMStrategy, RubricRankStrategy
from workflows.definition.models import InputPort, ResultSource
from workflows.judge_strategies import (
    IMPLEMENTED_KINDS,
    StrategyError,
    StrategyInvocation,
    admit_llm_strategy,
    replay_llm_strategy,
    run_llm_strategy,
    strategy_items,
)
from workflows.judge_strategies.models import StrategyEvidence

_SRC = Path(__file__).resolve().parents[3] / "src"
ROUTE = JudgeRoute(
    provider="openai",
    model_id="judge-fixture",
    reasoning_effort=None,
    max_output_tokens=512,
    max_retries=1,
)
ROUTES = JudgeRoutes(aggregate=ROUTE, max_judge_calls=20)
RUBRIC = RubricSpec(
    schema_version="siderius.rubric/v1",
    id="novelty",
    version="1",
    criteria=(
        RubricCriterion(name="novelty", description="How new is the idea.", weight=2.0),
        RubricCriterion(name="rigor", description="How well supported.", weight=1.0),
    ),
    scale_min=1,
    scale_max=5,
)


def strategy(**overrides) -> RubricRankStrategy:
    fields = {
        "route_slot": "aggregate",
        "max_calls": 9,
        "guidance": "none",
        "criterion": "Which review is most useful for the next proposal?",
        "rubric": rubric_ref(RUBRIC),
        "scoring": "per_item",
        "repeats": 1,
    }
    return RubricRankStrategy(**{**fields, **overrides})


def literature(position: int, state: str = "succeeded") -> AdaptorItem:
    value = LiteratureReviewOutput(
        agent_card=AgentCard(
            agent_name="ml_literature_review",
            role="role",
            expertise_domain="domain",
            coverage="coverage",
            limitations="limitations",
            trust_guidance="guidance",
            trust_level="soft_prior",
        ),
        findings=[
            ExpertContextItem(
                source="ml_literature_review",
                kind="literature",
                content=f"finding {position}",
                source_ref=f"ref:{position}",
                confidence=0.5,
            )
        ],
        run_name=f"review{position}",
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:01:00Z",
    )
    return AdaptorItem(
        ref=AdaptorInputRef(
            port="reviews",
            position=position,
            source=ResultSource(node=f"review{position}"),
            record_sha256=f"{position:064x}",
        ),
        contract="literature.output",
        state=state,
        value=value if state == "succeeded" else None,
    )


def invocation(tmp_path: Path, n: int = 3, **overrides) -> StrategyInvocation:
    fields = {
        "adaptor_id": "rank_reviews",
        "iteration": 2,
        "strategy": strategy(),
        "items": strategy_items(tuple(literature(i) for i in range(n))),
        "output_contract": "literature.output",
        "expected_count": CardinalityBound(min=1, max=1),
        "rubric": RUBRIC,
        "evidence_dir": tmp_path / "adaptors" / "rank_reviews.judge",
    }
    return StrategyInvocation(**{**fields, **overrides})


# item_id -> criterion -> scores per repeat (cycled by the call's repeat order)
TABLE = {
    "reviews:0": {"novelty": [2], "rigor": [5]},  # total 2*2 + 5 = 9
    "reviews:1": {"novelty": [4], "rigor": [1]},  # total 4*2 + 1 = 9 (tie with reviews:0)
    "reviews:2": {"novelty": [5], "rigor": [3]},  # total 5*2 + 3 = 13
}


class StubBridge:
    """Scores the items listed in the prompt from ``table``; counts calls per item."""

    def __init__(self, table=TABLE, *, mutate=None) -> None:
        self.table = table
        self.mutate = mutate
        self.calls: list[str] = []
        self.seen: dict[str, int] = {}

    def set_run_context(self, **kwargs) -> None:
        pass

    def generate(self, system_prompt: str, user_prompt: str, *, label: str):
        self.calls.append(label)
        facts = json.loads(user_prompt.split("Facts (JSON):\n", 1)[1])
        entries = []
        for item in facts["items"]:
            item_id = item["item_id"]
            repeat = self.seen.get(item_id, 0)
            self.seen[item_id] = repeat + 1
            scores = [
                {"criterion": name, "score": values[repeat % len(values)]}
                for name, values in self.table[item_id].items()
            ]
            entries.append({"item_id": item_id, "scores": scores})
        verdict = {"kind": "rubric", "item_scores": entries, "rationale": "fixture"}
        return self.mutate(verdict, len(self.calls)) if self.mutate else verdict


def run(value: StrategyInvocation, bridge: StubBridge, tmp_path: Path):
    return run_llm_strategy(
        value,
        ROUTES,
        context=JudgeRunContext(workspace=tmp_path, iteration=2, run_name="r", run_id="run-1"),
        bridge_factory=lambda _route: bridge,
    )


def test_rubric_ranking_is_code_weighted_and_ties_keep_input_order(tmp_path):
    """Defect: totals ignore weights, rank lower-first, or break ties against input order.

    Hand-computed weighted means (novelty=2, rigor=1, Σw=3): reviews:2 = 13/3,
    reviews:0 = 9/3 and reviews:1 = 9/3 tie, so input order puts reviews:0 first.
    Unweighted means would be 4, 3.5, 2.5.
    """
    result = run(invocation(tmp_path), StubBridge(), tmp_path)
    ranking = result.outcome.ranking
    assert result.outcome.status == "decided"
    assert ranking is not None
    assert ranking.order == ("reviews:2", "reviews:0", "reviews:1")
    assert [score.weighted_mean for score in ranking.scores] == [13 / 3, 3.0, 3.0]


def test_median_of_repeats_is_taken_per_criterion(tmp_path):
    """Defect: repeats are averaged (or the last repeat wins) instead of the median.

    reviews:0 novelty repeats (1, 2, 5): median 2, mean 2.67, last 5.
    """
    table = {**TABLE, "reviews:0": {"novelty": [1, 2, 5], "rigor": [5]}}
    value = invocation(tmp_path, strategy=strategy(repeats=3))
    bridge = StubBridge(table)
    ranking = run(value, bridge, tmp_path).outcome.ranking
    assert ranking is not None
    score = next(s for s in ranking.scores if s.item_id == "reviews:0")
    assert [c.value for c in score.per_criterion] == [2.0, 5.0]
    assert score.weighted_mean == 3.0
    assert len(bridge.calls) == 9  # per_item: 3 items x 3 repeats


@pytest.mark.parametrize("bound", [RUBRIC.scale_min, RUBRIC.scale_max])
def test_weighted_mean_stays_on_the_rubric_scale(tmp_path, bound):
    """Defect: the aggregate leaves [scale_min, scale_max] (e.g. an un-normalized sum),
    so a rubric threshold would depend on how the weights happen to be scaled."""
    table = {item_id: {"novelty": [bound], "rigor": [bound]} for item_id in TABLE}
    ranking = run(invocation(tmp_path), StubBridge(table), tmp_path).outcome.ranking
    assert ranking is not None
    assert {score.weighted_mean for score in ranking.scores} == {float(bound)}


def _combined(value: StrategyInvocation, ranking) -> Combined:
    """The B6 ranking B6-8 builds from an ``ItemRanking`` (exact rubric values)."""
    by_id = {item.item_id: (index, item) for index, item in enumerate(value.items)}
    units = tuple(
        Unit(
            value=literature(index).value,
            element_contract="literature.output",
            inputs=(item.ref,),
            role="selected",
        )
        for index, item in by_id.values()
    )
    entries = tuple(
        RankEntry(
            unit=by_id[s.item_id][0],
            ref=by_id[s.item_id][1].ref,
            value=s.weighted_mean,
            exact=s.weighted_mean_exact,
        )
        for s in ranking.scores
    )
    return Combined(
        combine_kind="rubric-rank/v1",
        units=units,
        ranking=Ranking(basis="rubric", entries=entries),
    )


def test_rubric_threshold_reads_the_weighted_mean_on_the_rubric_scale(tmp_path):
    """Defect: threshold(basis=rubric, at_least=4) keeps items below 4 on the 1..5 scale.

    Means are 13/3, 3 and 3: only reviews:2 clears 4 (a weighted sum, 13/9/9, would
    keep all three).
    """
    value = invocation(tmp_path)
    ranking = run(value, StubBridge(), tmp_path).outcome.ranking
    assert ranking is not None
    kept = select(ThresholdSelect(basis="rubric", at_least=4.0), _combined(value, ranking), None)
    assert [value.items[index].item_id for index in kept] == ["reviews:2"]


def decimal_rubric(novelty: float, rigor: float) -> RubricSpec:
    weights = (novelty, rigor)
    criteria = tuple(
        criterion.model_copy(update={"weight": weight})
        for criterion, weight in zip(RUBRIC.criteria, weights, strict=True)
    )
    return RUBRIC.model_copy(update={"criteria": criteria})


@pytest.mark.parametrize(
    ("weights", "true_four"),
    [
        pytest.param((0.1, 0.2), (2, 5), id="0.1/0.2-float-gives-3.999999999999999"),
        pytest.param((0.1, 0.3), (1, 5), id="0.1/0.3-binary-weights-are-not-the-declared-decimals"),
    ],
)
def test_decimal_weights_are_exact_for_ties_thresholds_and_the_scale_bound(
    tmp_path, weights, true_four
):
    """Defect: float arithmetic on weights 0.1/0.2 gives (2,5) -> 3.999999999999999 and
    (4,4) -> 4.0, reversing the input-order tie, dropping a true 4 at at_least=4, and
    letting an all-max item drift off scale_max."""
    table = {
        "reviews:0": {"novelty": [true_four[0]], "rigor": [true_four[1]]},  # 4 exactly
        "reviews:1": {"novelty": [4], "rigor": [4]},  # 4 exactly: ties reviews:0
        "reviews:2": {"novelty": [5], "rigor": [5]},  # all-max: exactly scale_max
    }
    rubric = decimal_rubric(*weights)
    value = invocation(tmp_path, strategy=strategy(rubric=rubric_ref(rubric)), rubric=rubric)
    ranking = run(value, StubBridge(table), tmp_path).outcome.ranking
    assert ranking is not None
    assert ranking.order == ("reviews:2", "reviews:0", "reviews:1")
    assert [s.weighted_mean_exact for s in ranking.scores] == ["5", "4", "4"]
    assert ranking.scores[0].weighted_mean == float(rubric.scale_max)
    kept = select(ThresholdSelect(basis="rubric", at_least=4.0), _combined(value, ranking), None)
    assert sorted(kept) == [0, 1, 2]


def test_order_uses_the_exact_mean_when_display_floats_collide(tmp_path):
    """Defect: ranking sorts on the display float, so distinct exact means that round to
    the same float fall back to input order. Weights (1.0, 1e-16): (1,1) is exactly 1,
    (1,2) is 10000000000000002/10000000000000001; both display as 1.0."""
    rubric = decimal_rubric(1.0, 1e-16)
    table = {
        "reviews:0": {"novelty": [1], "rigor": [1]},
        "reviews:1": {"novelty": [1], "rigor": [2]},
    }
    value = invocation(tmp_path, n=2, strategy=strategy(rubric=rubric_ref(rubric)), rubric=rubric)
    ranking = run(value, StubBridge(table), tmp_path).outcome.ranking
    assert ranking is not None
    assert ranking.order == ("reviews:1", "reviews:0")
    assert [score.weighted_mean for score in ranking.scores] == [1.0, 1.0]
    assert [score.weighted_mean_exact for score in ranking.scores] == [
        "10000000000000002/10000000000000001",
        "1",
    ]


def test_llm_supplied_total_is_refused_not_used(tmp_path):
    """Defect: a verdict carrying its own total is accepted and could replace code arithmetic."""

    def with_total(verdict, _index):
        verdict["item_scores"][0]["weighted_total"] = 99
        return verdict

    result = run(invocation(tmp_path), StubBridge(mutate=with_total), tmp_path)
    assert result.outcome.status == "failed"
    assert result.outcome.failure_code == "invalid_payload"


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda v, _i: {**v, "item_scores": []}, id="no-items"),
        pytest.param(
            lambda v, _i: {**v, "item_scores": [{**v["item_scores"][0], "item_id": "reviews:9"}]},
            id="foreign-item",
        ),
        pytest.param(
            lambda v, _i: {
                **v,
                "item_scores": [
                    {**v["item_scores"][0], "scores": [{"criterion": "novelty", "score": 6}]}
                ],
            },
            id="missing-criterion",
        ),
    ],
)
def test_incomplete_or_out_of_scale_verdict_ends_the_chain_with_its_fallback(tmp_path, mutate):
    """Defect: a verdict that skips an item/criterion or leaves the scale is folded, or the
    chain keeps calling after it, or the declared fallback is not reported to B6."""
    fallback = Fallback(combine=PassCombine())
    value = invocation(tmp_path, strategy=strategy(on_failure=fallback))
    bridge = StubBridge(mutate=mutate)
    result = run(value, bridge, tmp_path)
    assert len(bridge.calls) == 1
    assert result.outcome.status == "fallback"
    assert result.outcome.fallback_combine == "pass/v1"
    assert result.outcome.failure_code in {"invalid_payload", "inadmissible_choice"}
    assert replay_llm_strategy(value, ROUTES, expected_sha256=result.evidence_sha256) == result


def test_out_of_scale_score_is_inadmissible(tmp_path):
    """Defect: an integer outside the declared scale reaches the weighted mean."""

    def too_high(verdict, _index):
        verdict["item_scores"][0]["scores"][0]["score"] = 6
        return verdict

    result = run(invocation(tmp_path), StubBridge(mutate=too_high), tmp_path)
    assert (result.outcome.status, result.outcome.failure_code) == ("failed", "inadmissible_choice")


def test_inadmissible_or_reordered_inputs_never_reach_the_judge():
    """Defect: a rejected input or a completion-ordered tuple is projected for judging."""
    with pytest.raises(AdaptorStrategyError, match="admissible items only"):
        strategy_items((literature(0), literature(1, state="rejected")))
    with pytest.raises(AdaptorStrategyError, match="not declared order"):
        strategy_items((literature(1), literature(0)))


def test_replay_equals_run_and_refuses_tampered_or_unaccounted_evidence(tmp_path):
    """Defect: readback trusts edited payloads, a re-anchored truncation, or stray files."""
    value = invocation(tmp_path, strategy=strategy(scoring="batch", repeats=2))
    result = run(value, StubBridge(), tmp_path)
    assert replay_llm_strategy(value, ROUTES, expected_sha256=result.evidence_sha256) == result

    calls_dir = value.evidence_dir / "calls"
    call = calls_dir / "001_scorer.json"
    original_call = call.read_bytes()
    edited = json.loads(original_call)
    edited["payload"]["item_scores"][0]["scores"][0]["score"] = 1
    call.write_bytes(canonical_json_bytes(edited))
    with pytest.raises(StrategyError, match="call 1 is refused"):
        replay_llm_strategy(value, ROUTES, expected_sha256=result.evidence_sha256)
    call.write_bytes(original_call)

    record_path = value.evidence_dir / "strategy.json"
    original_record = record_path.read_bytes()
    record = json.loads(original_record)
    record["calls"] = record["calls"][:1]
    record_path.write_bytes(canonical_json_bytes(record))
    with pytest.raises(StrategyError, match="differs from its anchor"):
        replay_llm_strategy(value, ROUTES, expected_sha256=result.evidence_sha256)
    with pytest.raises(StrategyError, match="before the planned call chain is complete"):
        replay_llm_strategy(value, ROUTES, expected_sha256=canonical_sha256(record))
    record_path.write_bytes(original_record)

    # Re-anchored record with a reversed ranking: the re-derived outcome must refuse it.
    record = json.loads(original_record)
    ranking = record["outcome"]["ranking"]
    ranking["order"] = ranking["order"][::-1]
    ranking["scores"] = ranking["scores"][::-1]
    record_path.write_bytes(canonical_json_bytes(record))
    with pytest.raises(StrategyError, match="outcome differs"):
        replay_llm_strategy(value, ROUTES, expected_sha256=canonical_sha256(record))
    record_path.write_bytes(original_record)

    (calls_dir / "002_scorer.json").write_bytes(original_call)
    with pytest.raises(StrategyError, match="not accounted for"):
        replay_llm_strategy(value, ROUTES, expected_sha256=result.evidence_sha256)


def test_replay_refuses_evidence_of_another_invocation_or_route(tmp_path):
    """Defect: evidence recorded for other items, another order or another route replays."""
    value = invocation(tmp_path)
    result = run(value, StubBridge(), tmp_path)
    items = value.items
    reordered = value.model_copy(update={"items": (items[1], items[0], items[2])})
    with pytest.raises(StrategyError, match="another invocation"):
        replay_llm_strategy(reordered, ROUTES, expected_sha256=result.evidence_sha256)
    other_route = JudgeRoutes(aggregate=ROUTE.model_copy(update={"model_id": "other"}))
    with pytest.raises(StrategyError, match="call 0 is refused"):
        replay_llm_strategy(value, other_route, expected_sha256=result.evidence_sha256)


def test_run_refuses_before_any_call(tmp_path):
    """Defect: a misconfigured invocation contacts the provider or reuses old evidence."""
    bridge = StubBridge()
    with pytest.raises(StrategyError, match=r"judge\.aggregate route"):
        run_llm_strategy(
            invocation(tmp_path),
            JudgeRoutes(debate=ROUTE),
            context=JudgeRunContext(workspace=tmp_path, iteration=2, run_name="r", run_id="i"),
            bridge_factory=lambda _route: bridge,
        )
    with pytest.raises(StrategyError, match="max_calls"):
        run(invocation(tmp_path, strategy=strategy(max_calls=2)), bridge, tmp_path)
    stale = invocation(tmp_path)
    stale.evidence_dir.mkdir(parents=True)
    (stale.evidence_dir / "leftover.json").write_text("{}")
    with pytest.raises(StrategyError, match="never reused"):
        run(stale, bridge, tmp_path)
    assert bridge.calls == []


@pytest.mark.parametrize(
    ("status", "failure_code", "fields"),
    [
        ("failed", "prompt_too_large", fields)
        for fields in ({}, {"unsent_prompt_chars": 400001}, {"unsent_prompt_sha256": "b" * 64})
    ]
    + [
        (status, failure_code, fields)
        for status, failure_code in [
            ("decided", None),
            ("skipped", None),
            *[
                (status, code)
                for status in ("failed", "fallback")
                for code in (
                    "insufficient_items",
                    "primary_unavailable",
                    "cardinality_mismatch",
                    "provider_error",
                    "invalid_payload",
                    "inadmissible_choice",
                    "deadline",
                )
            ],
        ]
        for fields in (
            {"unsent_prompt_chars": 400001},
            {"unsent_prompt_sha256": "b" * 64},
            {"unsent_prompt_chars": 400001, "unsent_prompt_sha256": "b" * 64},
        )
    ],
)
def test_unsent_prompt_fields_are_required_exactly_for_prompt_too_large(
    status, failure_code, fields
):
    """Defect: incomplete unsent measurements or measurements on other outcomes pass.

    Removing the cross-field validator must make the expected refusal fail;
    all other evidence invariants are satisfied independently.
    """
    no_calls = status == "skipped" or failure_code in {
        "insufficient_items",
        "primary_unavailable",
    }
    record = {
        "invocation_sha256": "a" * 64,
        "strategy_kind": "debate-judge/v1",
        "static_call_bound": 1,
        "calls": () if no_calls else ("c" * 64,),
        "outcome": {
            "status": status,
            "ranking": {"order": ("reviews:0",)} if status in {"decided", "skipped"} else None,
            "failure_code": failure_code,
            "fallback_combine": "pass/v1" if status == "fallback" else None,
        },
        **fields,
    }
    with pytest.raises(
        ValidationError,
        match="unsent prompt size and digest are required exactly for prompt_too_large",
    ):
        StrategyEvidence.model_validate(record)


def test_invocation_refuses_a_rubric_or_guidance_it_does_not_reference(tmp_path):
    """Defect: a changed rubric (same id/version) or undeclared guidance silently scores items."""
    edited = RUBRIC.model_copy(update={"scale_max": 7})
    with pytest.raises(ValidationError, match="not the one the strategy references"):
        invocation(tmp_path, rubric=edited)
    with pytest.raises(ValidationError, match="task guidance is supplied iff"):
        invocation(tmp_path, strategy=strategy(guidance="task_blocks"))
    with pytest.raises(ValidationError, match="task guidance is supplied iff"):
        invocation(tmp_path, task_guidance=JudgeTaskBlocks(evaluation_guidance="g"))


PORT = InputPort(name="reviews", contract="literature.output", cardinality="many", max_items=3)
TOP1 = TopKSelect(k=1)


def admit(select=TOP1, inputs=None, output_contract="literature.output", value=None):
    return admit_llm_strategy(
        value or strategy(),
        inputs=(PORT,) if inputs is None else inputs,
        output_contract=output_contract,
        select=select,
        cardinality=CardinalityBound(min=1, max=1),
    )


def test_admission_accepts_rubric_rank_with_its_static_bound():
    """Defect: a valid declaration is refused, or the bound ignores repeats/scoring."""
    assert admit().admitted and admit().static_call_bound == 3
    assert admit(value=strategy(repeats=3)).static_call_bound == 9
    assert admit(value=strategy(scoring="batch", repeats=2)).static_call_bound == 2
    rubric_threshold = ThresholdSelect(basis="rubric", at_least=8.0)
    assert admit(select=rubric_threshold).admitted and admit(select=AllSelect()).admitted


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        pytest.param(
            {"inputs": (InputPort(name="r", contract="literature.output", cardinality="many"),)},
            "unbounded_port",
            id="many-port-without-max_items",
        ),
        pytest.param({"value": strategy(max_calls=2)}, "call_bound_exceeds_max_calls", id="cap"),
        pytest.param({"select": FirstAdmissibleSelect()}, "select_incompatible", id="first"),
        pytest.param({"inputs": ()}, "no_input_ports", id="no-ports"),
        pytest.param(
            {
                "value": strategy(scoring="batch", max_calls=1, repeats=1),
                "inputs": (
                    InputPort(
                        name="r", contract="literature.output", cardinality="many", max_items=17
                    ),
                ),
            },
            "batch_too_large",
            id="batch-prompt-bound",
        ),
        pytest.param(
            {"select": ThresholdSelect(basis="metric", metric_id="m", at_least=0.5)},
            "select_incompatible",
            id="metric-threshold",
        ),
        pytest.param({"output_contract": "proposal.output"}, "output_contract_mismatch", id="out"),
        pytest.param(
            {"inputs": (PORT, InputPort(name="p", contract="proposal.output", cardinality="one"))},
            "mixed_contracts",
            id="mixed",
        ),
        pytest.param(
            {
                "inputs": (InputPort(name="t", contract="tuning.output", cardinality="one"),),
                "output_contract": "tuning.output",
            },
            "metric_scored_reorder",
            id="Q-B2-2-top-k-over-metric-scored",
        ),
        pytest.param(
            {
                "inputs": (InputPort(name="t", contract="validation.output", cardinality="one"),),
                "output_contract": "validation.output",
                "select": AllSelect(),
            },
            "unprojectable_contract",
            id="no-projector",
        ),
    ],
)
def test_admission_refuses_each_invalid_combination(kwargs, code):
    """Defect: the named combination is admitted (one row per refusal rule)."""
    assert code in {refusal.code for refusal in admit(**kwargs).refusals}


def test_rubric_threshold_over_metric_scored_items_is_not_a_reorder():
    """Defect: Q-B2-2 refuses the filter it permits (threshold basis rubric / all)."""
    port = InputPort(name="t", contract="tuning.output", cardinality="one")
    for selector in (ThresholdSelect(basis="rubric", at_least=1.0), AllSelect()):
        codes = {
            r.code
            for r in admit(
                select=selector, inputs=(port,), output_contract="tuning.output"
            ).refusals
        }
        assert "metric_scored_reorder" not in codes


def test_every_declared_kind_is_implemented_and_an_unregistered_kind_is_refused(
    tmp_path, monkeypatch
):
    """Defect: a kind declared in the LLMStrategy union has no implementation (admission
    would refuse every use of it), or an unregistered kind is admitted or runs."""
    members = get_args(get_args(LLMStrategy)[0])
    declared = {get_args(member.model_fields["kind"].annotation)[0] for member in members}
    assert declared == set(IMPLEMENTED_KINDS)
    monkeypatch.setattr("workflows.judge_strategies.admission.IMPLEMENTED_KINDS", {}, raising=True)
    monkeypatch.setattr("workflows.judge_strategies.kinds.IMPLEMENTED_KINDS", {}, raising=True)
    assert [r.code for r in admit().refusals] == ["kind_not_implemented"]
    with pytest.raises(StrategyError, match="not implemented"):
        run(invocation(tmp_path), StubBridge(), tmp_path)


def rubric_request() -> CallRequest:
    projection = ItemProjection(
        contract="literature.output", fields=(ProjectedField(name="findings[0].content", text="x"),)
    )
    return CallRequest(
        invocation_sha256="b" * 64,
        call_role="scorer",
        call_index=0,
        prior_turns=(),
        content=RubricScoringRequest(
            rubric=RUBRIC,
            criterion="Which review is most useful?",
            repeat=0,
            items=(JudgedItem(item_id="reviews:0", projection=projection),),
            guidance=None,
        ),
    )


def test_rubric_prompt_bytes_are_pinned_for_a_fixed_request():
    """Defect: rubric prompt, request or response schema drift without a template version bump."""
    request = rubric_request()
    identity = RUBRIC_TEMPLATE.identity(request)
    pins = (
        canonical_sha256(request),
        identity.template_sha256,
        identity.prompt_sha256,
        identity.response_schema_sha256,
    )
    assert pins == PINS


PINS = (
    "345abefce759e4a8efcd08d5c5536243987f991369c4f5c44f94061a967c3bcf",
    "10f9b57f6617c18502aeaa1f3b876f2521c4956ad6dae291e82de677c522505b",
    "12a45544271d27491375c8b740a48daddfdc07d1ed8ebef8bb36b7f5f1a8ee34",
    "aa3dc8ac13d44bcfaa3860371e26bb2f496257b9e9990d947ca0f5199f724e34",
)


def test_prompt_never_shows_criterion_weights():
    """Defect: weights reach the LLM, inviting it to aggregate instead of code."""
    _system, user = RUBRIC_TEMPLATE.render(rubric_request())
    assert "weight" not in user and "2.0" not in user


def test_projection_is_bounded_and_omits_self_reported_confidence():
    """Defect: a long review overflows the projection bound (crash) or leaks confidence."""
    item = literature(0)
    assert item.value is not None
    long_value = item.value.model_copy(
        update={
            "findings": [item.value.findings[0].model_copy(update={"content": "y" * 9000})] * 30
        }
    )
    projected = strategy_items((item.model_copy(update={"value": long_value}),))[0].projection
    texts = {field.name: field.text for field in projected.fields}
    assert len(texts["findings[0].content"]) == 4000
    assert texts["findings.omitted"] == "6"
    assert not any("confidence" in name for name in texts)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_rubric_fold_cannot_reach_metric_owners_and_replay_cannot_reach_a_provider():
    """Defect: a rubric total enters MetricOrder, or readback imports the provider path."""
    package = _SRC / "workflows" / "judge_strategies"
    rubric = _imports(package / "rubric_rank.py")
    assert not {m for m in rubric if "metric_order" in m or "evaluation_metric" in m}
    for module in (
        "replay.py",
        "plan.py",
        "kinds.py",
        "rubric_rank.py",
        "judge_merge.py",
        "primary_advisors.py",
        "debate_judge.py",
        "debate_templates.py",
        "synthesis.py",
    ):
        imported = _imports(package / module)
        assert not {m for m in imported if "llm_bridge" in m or m == "agent.judge.call"}, module


def test_rubric_per_item_scoring_is_not_capped_by_the_per_call_item_limit():
    """Defect: the per-call item cap also refuses per_item scoring, which lists one item
    per call (lists_every_item wrongly True)."""
    wide = InputPort(
        name="reviews", contract="literature.output", cardinality="many", max_items=200
    )
    admission = admit(value=strategy(max_calls=200), inputs=(wide,), select=AllSelect())
    assert admission.admitted, admission.refusals


def test_a_later_call_over_the_prompt_budget_ends_the_chain_as_recorded_evidence(
    tmp_path, monkeypatch
):
    """Defect: a chain whose later call would exceed the budget sends it anyway (or loses
    the earlier evidence), or replay cannot re-derive the early stop."""
    item = literature(1)
    assert item.value is not None
    big = item.value.model_copy(
        update={"findings": [item.value.findings[0].model_copy(update={"content": "x" * 4000})]}
    )
    items = strategy_items((literature(0), item.model_copy(update={"value": big})))
    value = invocation(tmp_path, items=items)
    small = 3000  # between the first (small) and the second (4000-char finding) prompt
    for module in ("run", "plan"):
        monkeypatch.setattr(f"workflows.judge_strategies.{module}.MAX_JUDGE_PROMPT_CHARS", small)
    bridge = StubBridge()
    result = run(value, bridge, tmp_path)
    assert len(bridge.calls) == 1
    assert (result.outcome.status, result.outcome.failure_code) == ("failed", "prompt_too_large")
    assert replay_llm_strategy(value, ROUTES, expected_sha256=result.evidence_sha256) == result
