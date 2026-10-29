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
    # Replay precondition: an earlier met condition must not hide a later mismatch.
    with pytest.raises(StopConditionError, match=r"condition 1 .*'accuracy'"):
        decide(
            (0.5, 0.4),
            [
                NoImprovementStop(completed_bodies=1),
                MetricThresholdStop(metric_id="accuracy", threshold=0.1),
            ],
        )


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


DIGEST_A, DIGEST_B = "a" * 64, "b" * 64


def judged_input(scores, conditions, *, final=10, decision="absent"):
    from tools.candidate_worker.loop_stop import JudgeBoundaryVerdict

    bodies = tuple(
        BodyScore(iteration=i, valid_formal=value, metric_spec=None)
        for i, value in enumerate(scores, start=1)
    )
    verdict = (
        None
        if decision == "absent"
        else JudgeBoundaryVerdict(
            iteration=len(bodies),
            decision=decision,
            evidence_path="candidate_run/iteration_002/judge/stop.json",
            evidence_sha256=DIGEST_A,
            request_sha256=DIGEST_B,
        )
    )
    return StopEvaluationInput(
        iteration=len(bodies),
        final_iteration=final,
        conditions=tuple(conditions),
        bodies=bodies,
        metric=spec(),
        judge_verdict=verdict,
    )


def test_judge_is_consulted_only_where_no_deterministic_bound_decides():
    """Each case would spend a provider call (or veto a metric stop) if the predicate drifted."""
    from tools.candidate_worker.loop_stop import needs_stop_judge
    from workflows.definition import JudgeStop

    judge = JudgeStop(criterion="plateau", min_completed_bodies=2)
    threshold = MetricThresholdStop(metric_id="score", threshold=0.8)
    # Declared first, still evaluated after the deterministic threshold that fires.
    assert not needs_stop_judge(judged_input((0.5, 0.9), [judge, threshold]))
    assert decide((0.5, 0.9), [judge, threshold]).reason.kind == "metric_threshold"
    # Below min_completed_bodies, and at the final boundary: never judged.
    assert not needs_stop_judge(judged_input((0.5,), [judge, threshold]))
    assert not needs_stop_judge(judged_input((0.5, 0.6), [judge], final=2))
    assert needs_stop_judge(judged_input((0.5, 0.6), [judge, threshold]))


def test_recorded_verdict_decides_and_an_unrecorded_one_fails_closed():
    """Fails if a stop verdict loses its evidence anchor, an abstention stops the loop,
    or a missing verdict is read as continue instead of refusing."""
    from tools.candidate_worker.loop_stop import JudgeStopReason
    from workflows.definition import JudgeStop

    conditions = [NoImprovementStop(completed_bodies=5), JudgeStop(criterion="plateau")]
    stopped = evaluate_stop(judged_input((0.5, 0.6), conditions, decision="stop"))
    assert stopped.reason == JudgeStopReason(
        condition_index=1,
        iteration=2,
        evidence_path="candidate_run/iteration_002/judge/stop.json",
        evidence_sha256=DIGEST_A,
        request_sha256=DIGEST_B,
    )
    for decision in ("continue", None):
        output = evaluate_stop(judged_input((0.5, 0.6), conditions, decision=decision))
        assert output.decision == "continue" and output.reason is None
    with pytest.raises(StopConditionError, match=r"condition 1 \(judge\) has no recorded verdict"):
        evaluate_stop(judged_input((0.5, 0.6), conditions))


def test_evaluator_module_never_imports_a_provider_or_the_judge_effect():
    """Fails if the pure evaluator gains a provider or judge-call import: readback runs it
    at every boundary, and an effect there could re-call the LLM on verification."""
    import tools.candidate_worker.loop_stop as module

    tree = ast.parse(Path(module.__file__).read_text())
    imported = [
        getattr(node, "module", None) or alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    ]
    assert not [name for name in imported if name.startswith(("agent.llm_bridge", "agent.judge"))]


def anchored(scores, conditions, *, anchor=0, final=10, decision="absent"):
    return judged_input(scores, conditions, final=final, decision=decision).model_copy(
        update={"input_anchor": anchor}
    )


@pytest.mark.parametrize("ask_first", [False, True])
def test_met_stop_condition_beats_a_met_input_request_in_either_declared_order(ask_first):
    """Fails if a met ``request_input`` condition pauses a loop a met ``stop`` must end,
    or if declared order alone (not the action) decided between them."""
    ask = MetricThresholdStop(metric_id="score", threshold=0.8, on_met="request_input")
    stop = NoImprovementStop(completed_bodies=1)
    conditions = [ask, stop] if ask_first else [stop, ask]
    output = decide((0.9, 0.85), conditions)
    assert output.decision == "stop"
    assert output.reason.kind == "no_improvement"
    assert output.reason.condition_index == conditions.index(stop)
    # With the stop condition unmet, the same boundary asks instead.
    alone = decide((0.5, 0.9), conditions)
    assert alone.decision == "request_input"
    assert alone.reason.condition_index == conditions.index(ask)


def test_input_request_refires_only_after_a_fresh_stretch_from_its_anchor():
    """Fails if a resumed ``request_input`` condition re-fires at the very next boundary
    (whole-run counting), if a threshold asks twice, or if a ``stop`` condition starts
    counting from the anchor."""
    ask = NoImprovementStop(completed_bodies=2, on_met="request_input")
    scores = (0.9, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
    # Paused after body 5 (anchor 5): body 6 is one body later, body 7 is two.
    assert evaluate_stop(anchored(scores[:6], [ask], anchor=5)).decision == "continue"
    asked = evaluate_stop(anchored(scores, [ask], anchor=5))
    assert asked.decision == "request_input"
    assert asked.reason.non_improving_bodies == 6
    # Without an anchor the whole-run count already fires at body 3.
    assert evaluate_stop(anchored(scores[:3], [ask])).decision == "request_input"
    threshold = MetricThresholdStop(metric_id="score", threshold=0.8, on_met="request_input")
    assert evaluate_stop(anchored((0.5, 0.9), [threshold])).decision == "request_input"
    for count in (3, 4):
        later = anchored((0.5, 0.9, 0.95, 0.99)[:count], [threshold], anchor=2)
        assert evaluate_stop(later).decision == "continue"
    stop = NoImprovementStop(completed_bodies=2)
    assert evaluate_stop(anchored(scores[:6], [stop], anchor=5)).decision == "stop"


def test_input_request_judge_counts_its_minimum_from_the_anchor():
    """Fails if a ``request_input`` judge is consulted (a provider call) before
    ``min_completed_bodies`` have passed since the last pause, or if a ``stop`` judge
    starts honouring the anchor."""
    from tools.candidate_worker.loop_stop import needs_stop_judge, skipped_stop_judge
    from workflows.definition import JudgeStop

    ask = JudgeStop(criterion="plateau", min_completed_bodies=2, on_met="request_input")
    scores = (0.5, 0.6, 0.7, 0.8, 0.9)
    assert not needs_stop_judge(anchored(scores[:4], [ask], anchor=3))
    assert needs_stop_judge(anchored(scores, [ask], anchor=3))
    stop = JudgeStop(criterion="plateau", min_completed_bodies=2)
    assert needs_stop_judge(anchored(scores[:4], [stop], anchor=3))
    # Skip telemetry uses the same eligibility: no skip below the anchored minimum.
    threshold = MetricThresholdStop(metric_id="score", threshold=0.1)
    assert skipped_stop_judge(anchored(scores[:4], [ask, threshold], anchor=3)) is None
    assert skipped_stop_judge(anchored(scores, [ask, threshold], anchor=3)) == (0, 1)
    # A judge "stop" verdict takes the condition's action.
    output = evaluate_stop(anchored(scores, [ask], anchor=3, decision="stop"))
    assert output.decision == "request_input" and output.reason.kind == "judge"


def test_input_summary_reports_the_incumbent_and_the_stretch_since_the_last_pause():
    """Fails if the Monitor summary reads a recomputed or segment-local fact."""
    from tools.candidate_worker.loop_stop import InputRequestSummary, input_summary

    value = anchored((0.5, 0.9, 0.4, None, 0.3), [NoImprovementStop(completed_bodies=2)], anchor=2)
    assert input_summary(value) == InputRequestSummary(
        iteration=5,
        final_iteration=10,
        metric_id="score",
        direction="higher",
        incumbent=0.9,
        incumbent_iteration=2,
        non_improving_bodies=3,
        input_anchor=2,
        bodies_since_input=3,
    )
