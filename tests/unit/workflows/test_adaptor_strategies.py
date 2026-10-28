"""B6-2 deterministic adaptor strategy core: pure functions over typed items.

Each test names the defect it catches. Fixtures use neutral metric specs from
``tests.helpers.metric_fixtures``; nothing here trains, scores or calls an LLM.
"""

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from agent.schemas.literature_review import LiteratureReviewOutput
from agent.schemas.proposal import AgentCard, ExpertContextItem
from agent.schemas.validator import ValidatorOutput
from execute_tools.evaluation_metric import MetricIdentityConflictError
from tests.helpers.metric_fixtures import accuracy_like_spec, error_like_spec
from workflows.adaptors import (
    AdaptorInputRef,
    AdaptorItem,
    AdaptorStrategyError,
    Combined,
    RankEntry,
    Ranking,
    build_adaptor_record,
    combine,
    run_deterministic_adaptor,
    select,
)
from workflows.adaptors.record import canonical_sha256
from workflows.definition.adaptor_strategies import (
    AllSelect,
    CardinalityBound,
    CollectCombine,
    ConcatItemsCombine,
    FieldRankCombine,
    FirstAdmissibleSelect,
    MetricRankCombine,
    PassCombine,
    PerItemDistribute,
    ReplicateDistribute,
    SingleDistribute,
    SplitItemsDistribute,
    ThresholdSelect,
    TopKSelect,
    derive_cardinality,
)
from workflows.definition.models import ResultSource

HIGHER = accuracy_like_spec("fixture_metric")
LOWER = error_like_spec("fixture_metric")
METRIC_RANK = MetricRankCombine(score="best_valid_formal")


def ref(position: int, port: str = "inputs") -> AdaptorInputRef:
    return AdaptorInputRef(
        port=port,
        position=position,
        source=ResultSource(node=f"node{position}"),
        record_sha256=f"{position:064x}",
    )


def tuning(position, valid, *, formal=None, spec=HIGHER, state="succeeded") -> AdaptorItem:
    value = HyperparamTuningOutput(
        run_name=f"run{position}",
        model_type="fixture",
        file_index=0,
        status="completed",
        completed_rounds=1,
        total_attempts=1,
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:10:00Z",
        best_formal_denoising_score=valid if formal is None else formal,
        best_valid_formal_denoising_score=valid,
        metric_spec=spec,
    )
    return item(position, "tuning.output", value, state)


def validation(position, passed) -> AdaptorItem:
    value = ValidatorOutput(
        passed=passed,
        model_type="fixture",
        plugin_registered=True,
        tests_passed=passed,
        description_valid=True,
        config_fields_valid=True,
        instantiation_passed=True,
        gradient_check_passed=True,
        llm_review_passed=True,
    )
    return item(position, "validation.output", value)


def finding(content, confidence):
    return ExpertContextItem(
        source="ml_literature_review",
        kind="literature",
        content=content,
        source_ref=f"ref:{content}",
        confidence=confidence,
    )


def literature(position, *confidences) -> AdaptorItem:
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
        findings=[finding(f"r{position}f{i}", c) for i, c in enumerate(confidences)],
        run_name=f"review{position}",
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:01:00Z",
    )
    return item(position, "literature.output", value)


def item(position, contract, value, state="succeeded") -> AdaptorItem:
    return AdaptorItem(
        ref=ref(position),
        contract=contract,
        state=state,
        value=value if state == "succeeded" else None,
    )


def decide(items, combine_strategy, select_strategy, distribute, metric=HIGHER):
    return run_deterministic_adaptor(
        tuple(items),
        combine_strategy=combine_strategy,
        select_strategy=select_strategy,
        distribute_strategy=distribute,
        metric=metric,
    )


def emitted_runs(outcome):
    return [o.value.run_name if o.value else None for o in outcome.outputs]


def test_metric_rank_direction_comes_from_the_run_metric_spec():
    # Defect: a hard-coded max()/sorted(reverse=True) ignores a lower-is-better metric.
    scores = (0.2, 0.9, 0.5)
    for spec, winner in ((HIGHER, "run1"), (LOWER, "run0")):
        items = [tuning(i, s, spec=spec) for i, s in enumerate(scores)]
        outcome = decide(items, METRIC_RANK, TopKSelect(k=1), SingleDistribute(), spec)
        assert emitted_runs(outcome) == [winner]
        assert outcome.ranking is not None and outcome.ranking.direction == spec.direction


def test_inadmissible_items_never_reach_ranking_even_with_the_best_raw_score():
    # Defect: ranking on the raw formal score, or admitting rejected/skipped/unscoreable inputs.
    items = [
        tuning(0, None, formal=99.0),  # scored, but no Health-valid formal record
        tuning(1, None),  # no formal score at all
        tuning(2, None, state="skipped"),
        tuning(3, None, state="rejected"),
        tuning(4, 0.1),
    ]
    outcome = decide(items, METRIC_RANK, TopKSelect(k=1), SingleDistribute())
    assert [a.admission for a in outcome.admissions] == [
        "health_invalid",
        "not_scoreable",
        "skipped",
        "rejected",
        "admissible",
    ]
    assert emitted_runs(outcome) == ["run4"]
    assert [e.unit for e in outcome.ranking.entries] == [0]


def test_metric_ties_resolve_to_declared_order_not_value_identity():
    # Defect: an unstable or value-keyed sort makes the tie winner depend on input arrival.
    items = [tuning(0, 0.5), tuning(1, 0.9), tuning(2, 0.9)]
    first = decide(items, METRIC_RANK, TopKSelect(k=2), PerItemDistribute(count=2, on_short="fail"))
    assert emitted_runs(first) == ["run1", "run2"]
    permuted = items[::-1]
    permuted = [p.model_copy(update={"ref": ref(i)}) for i, p in enumerate(permuted)]
    second = decide(
        permuted, METRIC_RANK, TopKSelect(k=2), PerItemDistribute(count=2, on_short="fail")
    )
    assert emitted_runs(second) == ["run2", "run1"]


def test_metric_rank_refuses_a_foreign_metric_identity_or_a_missing_run_metric():
    # Defect: ranking scores stamped with another metric (same id, opposite direction).
    items = [tuning(0, 0.2), tuning(1, 0.4, spec=LOWER)]
    with pytest.raises(MetricIdentityConflictError):
        decide(items, METRIC_RANK, TopKSelect(k=1), SingleDistribute())
    with pytest.raises(AdaptorStrategyError, match="requires the run metric"):
        decide(items[:1], METRIC_RANK, TopKSelect(k=1), SingleDistribute(), metric=None)


def test_threshold_on_metric_includes_ties_keeps_declared_order_and_names_the_run_metric():
    # Defect: `>` instead of is_at_least, ranked instead of declared order, or a
    # threshold silently applied to a metric other than the run's.
    items = [tuning(i, s, spec=LOWER) for i, s in enumerate((0.3, 0.1, 0.5, 0.2))]
    keep = ThresholdSelect(basis="metric", metric_id="fixture_metric", at_least=0.3)
    outcome = decide(items, METRIC_RANK, keep, PerItemDistribute(count=4, on_short="skip"), LOWER)
    assert emitted_runs(outcome) == ["run0", "run1", "run3", None]
    assert [o.status for o in outcome.outputs][-1] == "skipped"
    wrong = ThresholdSelect(basis="metric", metric_id="other", at_least=0.3)
    with pytest.raises(AdaptorStrategyError, match="names metric"):
        decide(items, METRIC_RANK, wrong, PerItemDistribute(count=4, on_short="skip"), LOWER)


def _rubric_combined(contract, items):
    base = combine(PassCombine(), tuple(items), None)
    ranking = Ranking(
        basis="rubric",
        entries=(
            RankEntry(unit=1, ref=items[1].ref, value=8.0),
            RankEntry(unit=0, ref=items[0].ref, value=5.0),
        ),
    )
    assert base.units[0].element_contract == contract
    return Combined(combine_kind="rubric-rank/v1", units=base.units, ranking=ranking)


def test_rubric_ranking_filters_but_never_reorders_metric_scored_items():
    # Defect (Q-B2-2): an LLM rubric ranking reorders items carrying formal metric results,
    # or a metric threshold silently reads rubric totals.
    combined = _rubric_combined("tuning.output", [tuning(0, 0.1), tuning(1, 0.2)])
    rubric = ThresholdSelect(basis="rubric", at_least=6.0)
    assert select(rubric, combined, HIGHER) == (1,)
    with pytest.raises(AdaptorStrategyError, match="refused"):
        select(TopKSelect(k=1), combined, HIGHER)
    metric = ThresholdSelect(basis="metric", metric_id="fixture_metric", at_least=0.0)
    with pytest.raises(AdaptorStrategyError, match="cannot read"):
        select(metric, combined, HIGHER)
    literature_rank = _rubric_combined("literature.output", [literature(0, 0.1), literature(1)])
    assert select(TopKSelect(k=1), literature_rank, None) == (1,)


def test_empty_admissible_set_and_empty_selection_are_rejected_without_outputs():
    # Defect: an adaptor with nothing admissible or nothing selected emitting a value
    # (or crashing in COMBINE) instead of a typed rejection.
    none = decide(
        [validation(0, False), validation(1, False)],
        PassCombine(),
        FirstAdmissibleSelect(),
        SingleDistribute(),
    )
    assert (none.status, none.reason, none.outputs) == ("rejected", "no_admissible_input", ())
    keep = ThresholdSelect(basis="metric", metric_id="fixture_metric", at_least=1.0)
    nothing = decide([tuning(0, 0.2)], METRIC_RANK, keep, SingleDistribute())
    assert (nothing.status, nothing.reason, nothing.outputs) == (
        "rejected",
        "insufficient_items",
        (),
    )


def test_first_admissible_skips_a_rejected_branch_and_requires_pass():
    # Defect: "first" read as the first bound source rather than the first admissible one.
    items = [validation(0, False), validation(1, True), validation(2, True)]
    outcome = decide(items, PassCombine(), FirstAdmissibleSelect(), SingleDistribute())
    assert outcome.outputs[0].inputs == (ref(1),)
    with pytest.raises(AdaptorStrategyError, match="requires pass"):
        decide([tuning(0, 0.1)], METRIC_RANK, FirstAdmissibleSelect(), SingleDistribute())


def test_derived_cardinality_table_and_unsatisfiable_pairs():
    # Defect: a bound that lets SELECT hand DISTRIBUTE more values than it has outputs.
    fail3 = PerItemDistribute(count=3, on_short="fail")
    skip3 = PerItemDistribute(count=3, on_short="skip")
    split = SplitItemsDistribute(field="findings", count=3, on_short="fail")
    table = [
        (AllSelect(), SingleDistribute(), (1, 1)),
        (AllSelect(), skip3, (1, 3)),
        (AllSelect(), fail3, (3, 3)),
        (TopKSelect(k=2), skip3, (1, 2)),
        (TopKSelect(k=5), split, (1, 1)),
        (FirstAdmissibleSelect(), ReplicateDistribute(count=4), (1, 1)),
    ]
    for select_strategy, distribute, (low, high) in table:
        assert derive_cardinality(select_strategy, distribute) == CardinalityBound(
            min=low, max=high
        )
    with pytest.raises(ValidationError, match="unsatisfiable"):
        derive_cardinality(TopKSelect(k=2), fail3)


def test_per_item_shortfall_fails_or_skips_and_an_unbounded_select_is_refused():
    # Defect: a shortfall silently emitting fewer outputs under on_short="fail", or a
    # select that exceeds the distribute count being truncated.
    items = [validation(0, True), validation(1, True)]
    failed = decide(items, PassCombine(), AllSelect(), PerItemDistribute(count=2, on_short="fail"))
    assert failed.status == "succeeded"
    short = decide(
        items[:1], PassCombine(), AllSelect(), PerItemDistribute(count=2, on_short="fail")
    )
    assert (short.status, short.reason) == ("failed", "insufficient_items")
    skipped = decide(
        items[:1], PassCombine(), AllSelect(), PerItemDistribute(count=2, on_short="skip")
    )
    assert [o.status for o in skipped.outputs] == ["emitted", "skipped"]
    with pytest.raises(AdaptorStrategyError, match="at most 1"):
        decide(items, PassCombine(), AllSelect(), SingleDistribute())


def test_field_rank_top_k_then_split_keeps_strongest_self_reported_findings():
    # Defect: ranking findings without the self-reported label, selecting an entry
    # with no confidence, or split altering any non-list field.
    review = literature(0, 0.4, None, 0.9, 0.4, 0.7)
    outcome = decide(
        [review],
        FieldRankCombine(field="confidence", order="descending"),
        TopKSelect(k=3),
        SplitItemsDistribute(field="findings", count=3, on_short="fail"),
        metric=None,
    )
    assert outcome.ranking.provenance == "self-reported"
    assert [e.value for e in outcome.ranking.entries] == [0.9, 0.7, 0.4, 0.4]
    assert [o.value.findings[0].content for o in outcome.outputs] == ["r0f2", "r0f4", "r0f0"]
    assert [o.inputs[0].item_path for o in outcome.outputs] == [
        "findings[2]",
        "findings[4]",
        "findings[0]",
    ]
    original = review.value.model_dump(mode="json", exclude={"findings"})
    for output in outcome.outputs:
        assert output.value.model_dump(mode="json", exclude={"findings"}) == original
    lower = decide(
        [review],
        FieldRankCombine(field="confidence", order="ascending"),
        TopKSelect(k=1),
        SingleDistribute(),
        metric=None,
    )
    assert [f.content for f in lower.outputs[0].value.findings] == ["r0f0"]
    with pytest.raises(AdaptorStrategyError, match="not catalogued"):
        combine(FieldRankCombine(field="content", order="descending"), (review,), None)


def test_split_refuses_more_entries_than_outputs_and_fails_or_skips_on_shortfall():
    # Defect: truncating a list longer than the static output count drops entries silently.
    def split(review, on_short):
        strategy = SplitItemsDistribute(field="findings", count=3, on_short=on_short)
        return decide([review], PassCombine(), AllSelect(), strategy, metric=None)

    assert split(literature(0, 0.1, 0.2, 0.3, 0.4), "skip").reason == "too_many_items"
    assert split(literature(0, 0.1, 0.2), "fail").reason == "insufficient_items"
    assert [o.status for o in split(literature(0, 0.1, 0.2), "skip").outputs] == [
        "emitted",
        "emitted",
        "skipped",
    ]


def test_collect_and_concat_preserve_declared_order_and_attribution():
    # Defect: losing which source contributed which value, or reordering by completion.
    reviews = [literature(0, 0.1), literature(1, 0.2, 0.3)]
    collected = decide(reviews, CollectCombine(), AllSelect(), SingleDistribute(), metric=None)
    entries = collected.outputs[0].value.entries
    assert [e.contribution_id for e in entries] == ["node0", "node1"]
    assert collected.outputs[0].role == "collected"
    concat = decide(
        reviews, ConcatItemsCombine(field="findings"), AllSelect(), SingleDistribute(), metric=None
    )
    value = concat.outputs[0].value
    assert [f.content for f in value.findings] == ["r0f0", "r1f0", "r1f1"]
    assert value.run_name == "review0"
    assert concat.outputs[0].inputs == (ref(0), ref(1))


def test_record_maps_every_emitted_output_to_its_inputs_and_digest():
    # Defect: a record that cannot be recomputed (digest of a different value) or that
    # attributes an output to an input that never reached it.
    items = [validation(0, False), validation(1, True)]
    outcome = decide(items, PassCombine(), AllSelect(), ReplicateDistribute(count=2))
    record = build_adaptor_record(
        adaptor_id="pick",
        iteration=1,
        combine=PassCombine(),
        select=AllSelect(),
        distribute=ReplicateDistribute(count=2),
        outcome=outcome,
    )
    assert [c.inputs for c in record.contributions] == [(ref(1),), (ref(1),)]
    assert {c.role for c in record.contributions} == {"replicated"}
    assert [o.sha256 for o in record.outputs] == [canonical_sha256(items[1].value)] * 2
    assert record.strategies == ("pass/v1", "all/v1", "replicate/v1")
