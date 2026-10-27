"""Pure stop-condition evaluator: hardcoded literals, no workspace, no native history."""

import ast
from pathlib import Path

import pytest

from execute_tools.evaluation_metric import MetricSpec, PresenceScoreabilityContract
from tools.candidate_worker.loop_stop import (
    BodyScore,
    MetricThresholdReason,
    NoImprovementReason,
    StopConditionError,
    StopEvaluationInput,
    evaluate_stop,
)
from workflows.definition import MetricThresholdStop, NoImprovementStop


def spec(direction="higher", metric_id="score"):
    return MetricSpec(
        id=metric_id,
        direction=direction,
        aggregation="mean",
        scoreability=PresenceScoreabilityContract(),
    )


def decide(scores, conditions, *, direction="higher", final=10, metric=True):
    bodies = tuple(
        BodyScore(iteration=i, valid_formal=value, metric_spec=None)
        for i, value in enumerate(scores, start=1)
    )
    return evaluate_stop(
        StopEvaluationInput(
            iteration=len(bodies),
            final_iteration=final,
            conditions=tuple(conditions),
            bodies=bodies,
            metric=spec(direction) if metric else None,
        )
    )


@pytest.mark.parametrize(
    ("direction", "scores", "expected"),
    [
        # Fails on a direction flip or a hardcoded `>`: 0.9 reaches 0.8 only when higher.
        ("higher", (0.5, 0.9), (0.9, 2)),
        ("lower", (0.9, 0.5), (0.5, 2)),
        ("higher", (0.5, 0.7), None),
        ("lower", (0.7, 0.9), None),
    ],
)
def test_threshold_uses_declared_direction(direction, scores, expected):
    threshold = 0.8 if direction == "higher" else 0.6
    output = decide(
        scores, [MetricThresholdStop(metric_id="score", threshold=threshold)], direction=direction
    )
    if expected is None:
        assert output.decision == "continue" and output.reason is None
        return
    assert output.reason == MetricThresholdReason(
        condition_index=0,
        iteration=2,
        metric_id="score",
        direction=direction,
        threshold=threshold,
        incumbent=expected[0],
        incumbent_iteration=expected[1],
    )


def test_threshold_tie_stops_and_incumbent_tie_is_not_an_improvement():
    # is_at_least: a tie at the threshold stops (fails if replaced by is_better).
    tied = decide((0.8,), [MetricThresholdStop(metric_id="score", threshold=0.8)])
    assert tied.decision == "stop"
    # Strict incumbent: an equal value is non-improving (fails if `is_at_least` is used).
    output = decide((0.7, 0.7, None), [NoImprovementStop(completed_bodies=2)])
    assert output.reason == NoImprovementReason(
        condition_index=0,
        iteration=3,
        k=2,
        non_improving_bodies=2,
        last_improvement_iteration=1,
        incumbent=0.7,
    )


def test_no_improvement_counts_from_first_valid_value_without_off_by_one():
    condition = [NoImprovementStop(completed_bodies=2)]
    # A body without a valid formal is non-improving; the first valid value improves.
    assert decide((None,), condition).decision == "continue"
    assert decide((None, None), condition).reason.last_improvement_iteration is None
    assert decide((None, 0.4, 0.3), condition).decision == "continue"
    assert decide((None, 0.4, 0.3, 0.2), condition).reason.non_improving_bodies == 2


def test_first_declared_met_condition_wins_and_final_boundary_has_no_reason():
    conditions = [
        NoImprovementStop(completed_bodies=1),
        MetricThresholdStop(metric_id="score", threshold=0.1),
    ]
    assert decide((0.5, 0.4), conditions).reason.kind == "no_improvement"
    assert decide((0.5, 0.4), conditions[::-1]).reason.condition_index == 0
    assert decide((0.5, 0.4), conditions[::-1]).reason.kind == "metric_threshold"
    # The final limit owns its boundary, even when a condition is met there.
    assert decide((0.5, 0.4), conditions, final=2).decision == "continue"


def test_unknown_metric_or_mismatched_id_fails_instead_of_ignoring_the_condition():
    with pytest.raises(StopConditionError, match=r"no_improvement.*requires a run metric"):
        decide((0.5,), [NoImprovementStop(completed_bodies=1)], metric=False)
    with pytest.raises(StopConditionError, match=r"'accuracy'.*'score'"):
        decide((0.5,), [MetricThresholdStop(metric_id="accuracy", threshold=0.1)])


def test_incumbent_matches_native_completed_history_fold():
    """Guards divergent incumbent semantics between the evaluator and research_history."""
    from core.chain_state import ChainState
    from tests.unit.workflows.test_model_exploration import (
        _make_interpretation_output,
        _make_proposal_output,
        _make_tune_output,
    )
    from workflows.research_history import advance_completed_history

    metric = spec("lower")
    values = (0.9, None, 0.4, 0.4, 0.6)
    state = ChainState.cold_start()
    for index, value in enumerate(values):
        output = _make_tune_output(f"m{index}", 0.1, metric_spec=metric)
        output.best_valid_formal_denoising_score = value
        advance_completed_history(
            state,
            _make_interpretation_output(),
            _make_proposal_output(f"m{index}"),
            output,
            required_gate_ids=None,
            run_metric_spec=metric,
            bound_metric_spec=metric,
        )
    reason = decide(values, [NoImprovementStop(completed_bodies=2)], direction="lower").reason
    assert state.chain_formal_incumbent_reference == 0.4
    assert (reason.incumbent, reason.last_improvement_iteration) == (0.4, 3)


def test_evaluator_module_never_imports_native_history_carriers():
    import tools.candidate_worker.loop_stop as module

    tree = ast.parse(Path(module.__file__).read_text())
    imported = [
        name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for name in (getattr(node, "module", None) or "", *(a.name for a in node.names))
    ]
    assert imported and not [
        name for name in imported if "chain_state" in name or "research_history" in name
    ]
