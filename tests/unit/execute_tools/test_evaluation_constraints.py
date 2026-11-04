"""Feasibility constraints are declared scoreability: violated means never selected (#1295)."""

import math
from types import SimpleNamespace

import pytest

from agent.schemas.hyperparam_tuning import ExperimentRecord
from execute_tools.evaluation_aggregation import aggregate_evaluation, constrain_primary
from execute_tools.evaluation_child import (
    EvaluationNotScoreableError,
    aggregate_child_outcome,
    validate_child_evaluation,
)
from execute_tools.evaluation_metric import (
    MetricResult,
    MetricSpec,
    NotScoreableResult,
    PresenceScoreabilityContract,
)
from execute_tools.evaluation_results import EvaluationTransportError
from execute_tools.metric_order import MetricOrder
from nodes.ml_hyperparameter_tune_agent.policy import _best_trial_winner, _select_best_records
from nodes.ml_hyperparameter_tune_agent.records import _build_scoring_failure_record
from workflows.evaluation_composition import compose_evaluation
from workflows.evaluation_selection import selection_binding

PRIMARY = MetricSpec(
    id="accuracy",
    direction="higher",
    aggregation="mean",
    scoreability=PresenceScoreabilityContract(),
)
ERROR = MetricSpec(
    id="error", direction="lower", aggregation="mean", scoreability=PresenceScoreabilityContract()
)


def composed(constraints, *, formula=False):
    spec = {
        "components": [
            {"kind": "metric", "id": "quality", "metric": "accuracy", "meaning": "Accuracy"},
            {"kind": "metric", "id": "err", "metric": "error", "meaning": "Error", "units": "ms"},
        ],
        "selection": {"kind": "primary"},
        "constraints": constraints,
    }
    if formula:
        spec["selection"] = {
            "kind": "formula",
            "formula": {
                "family": "weighted_sum",
                "params": {
                    "terms": [
                        {
                            "component": "quality",
                            "weight": 1.0,
                            "lower": 0.0,
                            "upper": 1.0,
                            "out_of_range": "refuse",
                        }
                    ]
                },
            },
        }
    evaluation = compose_evaluation(
        {"evaluation": spec}, ".", {"accuracy": PRIMARY, "error": ERROR}, None
    )
    assert evaluation is not None
    return evaluation


def accuracy(value, **kwargs):
    return MetricResult(metric_id="accuracy", direction="higher", scalar=value, **kwargs)


def error(value):
    return MetricResult(metric_id="error", direction="lower", scalar=value)


def test_violated_constraint_refuses_with_named_reason_and_feasible_keeps_source():
    """Without enforcement the infeasible candidate would stay scoreable and selectable."""
    evaluation = composed([{"component": "quality", "op": ">=", "threshold": 0.9}])
    refused, evidence = constrain_primary(evaluation, PRIMARY, accuracy(0.85), [])
    assert isinstance(refused, NotScoreableResult)
    assert refused.metric_id == "accuracy"
    assert [f.detail for f in refused.verdict.failures] == [
        "constraint quality >= 0.9 violated: 0.85"
    ]
    assert evidence is not None and evidence.aggregate is None
    assert evidence.constraints[0].satisfied is False

    source = accuracy(0.95, per_sample=[0.9, 1.0])
    kept, evidence = constrain_primary(evaluation, PRIMARY, source, [])
    assert kept == source  # the source scalar and per-sample evidence rank unchanged
    assert evidence is not None and evidence.aggregate == 0.95
    assert evidence.constraints[0].satisfied is True


@pytest.mark.parametrize(
    ("op", "satisfied"), [(">=", True), (">", False), ("<=", True), ("<", False)]
)
def test_bound_inclusivity_is_exact_at_the_threshold(op, satisfied):
    """A tolerance or a swapped operator would flip the boundary verdict."""
    evaluation = composed([{"component": "err", "op": op, "threshold": 0.3}])
    outcome, _ = constrain_primary(evaluation, PRIMARY, accuracy(0.5), [error(0.3)])
    assert isinstance(outcome, MetricResult) is satisfied


@pytest.mark.parametrize("secondaries", [[], [error(math.nan)]])
def test_missing_or_nonfinite_constraint_value_fails_closed(secondaries):
    """An unmeasured constraint must never be treated as satisfied."""
    evaluation = composed([{"component": "err", "op": "<=", "threshold": 5.0}])
    outcome, _ = constrain_primary(evaluation, PRIMARY, accuracy(0.9), secondaries)
    assert isinstance(outcome, NotScoreableResult)
    assert outcome.verdict.failures[0].requirement == "constraint:err"


def test_formula_constraint_on_unreferenced_secondary_refuses_the_utility():
    """Constraints are judged on raw values, also under formula selection."""
    evaluation = composed([{"component": "err", "op": "<=", "threshold": 5.0}], formula=True)
    outcome, evidence = aggregate_evaluation(evaluation, PRIMARY, accuracy(0.9), [error(7.0)])
    assert isinstance(outcome, NotScoreableResult)
    assert [f.requirement for f in outcome.verdict.failures] == ["constraint:err"]
    assert evidence.constraints[0].raw == 7.0


def test_parent_rederives_constraint_verdicts_instead_of_trusting_the_child():
    """A child payload claiming feasibility for a violated constraint must fail transport."""
    evaluation = composed([{"component": "err", "op": "<=", "threshold": 5.0}])
    composition = SimpleNamespace(metric=SimpleNamespace(spec=PRIMARY), evaluation=evaluation)
    carrier = SimpleNamespace(selection_binding=selection_binding(composition))
    secondaries = {"secondary_metric_results": [error(2.0).model_dump(mode="json")]}
    outcome, fields = aggregate_child_outcome(composition, accuracy(0.9), secondaries)
    payload = {
        **fields,
        "denoising_score": outcome.scalar,
        "metric_result": outcome.model_dump(mode="json"),
    }
    assert validate_child_evaluation(payload, carrier) is not None
    payload["secondary_metric_results"] = [error(7.0).model_dump(mode="json")]
    with pytest.raises(EvaluationTransportError, match="constraint"):
        validate_child_evaluation(payload, carrier)


def _success(exp_id, score, *, is_trial):
    record = {
        "exp_id": exp_id,
        "status": "success",
        "denoising_score": score,
        "health_gate_enabled": False,
    }
    if is_trial:
        record["is_trial"] = True
    return record


@pytest.mark.parametrize("is_trial", [False, True])
def test_infeasible_candidate_is_excluded_from_tuner_selection(is_trial):
    """The higher-scoring infeasible round must not become best, valid best or trial winner."""
    evaluation = composed([{"component": "err", "op": "<=", "threshold": 5.0}])
    refusal, evidence = constrain_primary(evaluation, PRIMARY, accuracy(0.99), [error(9.0)])
    assert isinstance(refusal, NotScoreableResult) and evidence is not None
    infeasible = _build_scoring_failure_record(
        EvaluationNotScoreableError(refusal, evidence),
        exp_id="infeasible",
        model_type="m",
        file_index=0,
        record_params={},
        timing={"train_time_s": 1.0, "inference_time_s": 1.0, "scoring_time_s": 1.0},
        expert_advice_str="",
        hypothesis="",
        round_index=1,
        attempt_in_round=1,
    )
    if is_trial:
        infeasible["is_trial"] = True
    ExperimentRecord.model_validate(infeasible)  # the persisted shape is a valid record
    assert "violated: 9.0" in infeasible["memory"]["conclusion"]
    assert "Infeasible" in infeasible["memory"]["memory_update"]
    feasible = _success("feasible", 0.7, is_trial=is_trial)
    order = MetricOrder(PRIMARY)
    tracks = _select_best_records(
        [infeasible, feasible], order=order, required_gate_ids=frozenset()
    )
    assert tracks.top is feasible and tracks.valid is feasible
    winner = _best_trial_winner([infeasible, feasible], order=order, required_gate_ids=frozenset())
    assert winner is (feasible if is_trial else None)


def test_feasible_constrained_record_keeps_its_per_sample_evidence():
    """Only formula utility lacks a per-sample decomposition; a constrained source has one."""
    evaluation = composed([{"component": "quality", "op": ">=", "threshold": 0.5}])
    source = accuracy(0.8, per_sample=[0.7, 0.9])
    outcome, evidence = constrain_primary(evaluation, PRIMARY, source, [])
    assert evidence is not None
    record = ExperimentRecord.model_validate(
        {
            "exp_id": "feasible",
            "status": "success",
            "model_type": "m",
            "timestamp": "t",
            "file_index": 0,
            "params": {},
            "timing": {"train_time_s": 1.0, "inference_time_s": 1.0, "scoring_time_s": 1.0},
            "denoising_score": 0.8,
            "file_vector": [0.7, 0.9],
            "metric_result": outcome.model_dump(mode="json"),
            "evaluation_result": evidence.model_dump(mode="json"),
        }
    )
    assert record.evaluation_result is not None
    assert record.evaluation_result.constraints[0].satisfied
