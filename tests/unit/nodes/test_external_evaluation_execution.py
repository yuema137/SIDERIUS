"""Bound complete evaluation reaches native interpretation without private I/O."""

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from execute_tools.evaluation_execution import (
    CandidateEvaluationResult,
    bind_candidate_evaluation,
    candidate_evaluation_executor,
)
from execute_tools.evaluation_metric import (
    MetricResult,
    NotScoreableResult,
    ScoreabilityFailure,
    ScoreabilityVerdict,
)
from workflows.task_composition import compose_run_task_bindings

execution = importlib.import_module("nodes.ml_hyperparameter_tune_agent.execution")


class Evaluator:
    def __init__(self, *, eligible=True, fault=None):
        self.eligible, self.fault = eligible, fault
        self.requests = []

    def evaluate(self, request):
        self.requests.append(request)
        if self.fault == "transport":
            raise RuntimeError("fixture evaluator unavailable")
        metric = MetricResult(
            metric_id="other_metric" if self.fault == "metric" else request.metric.id,
            direction=request.metric.direction,
            scalar=float("nan") if self.fault == "nonfinite" else 0.25,
            per_sample=None,
        )
        if self.fault == "refusal":
            metric = NotScoreableResult(
                metric_id=request.metric.id,
                direction=request.metric.direction,
                verdict=ScoreabilityVerdict(
                    contract_id="synthetic_contract",
                    failures=(
                        ScoreabilityFailure(requirement="complete", detail="missing prediction"),
                    ),
                ),
            )
        return CandidateEvaluationResult(
            run_name=request.run_name,
            exp_id="stale" if self.fault == "identity" else request.exp_id,
            model_type=request.model_type,
            candidate_digest="fixture-digest",
            receipt_path="/operator/receipt.json",
            requested_scope={"wrong": True} if self.fault == "scope" else request.requested_scope,
            evaluated_scope={"split": "validation", "all_samples": True},
            metric=metric,
            health_status="valid" if self.eligible and self.fault != "health" else "invalid",
            health_gate_results=(),
            health_config_digest="fixture-config",
            eligible_for_selection=self.eligible,
            secondary_errors={"unrequested": "error"} if self.fault == "secondary" else {},
            failure_reason=None if self.eligible else "fixture blocking refusal",
        )


@pytest.fixture
def attempt(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[3]
    metric = compose_run_task_bindings(
        str(root / "configs/task_composition/quickstart.yaml")
    ).metric
    bindings = SimpleNamespace(
        agent_input=SimpleNamespace(retain_model_outputs=False, degenerate_penalty_score=None),
        file_index=0,
        expert_advice_str="",
        reference_scores=None,
        run_deliverable_naming=None,
        run_name="run",
        sandbox=SimpleNamespace(base_dir=str(tmp_path), dirs={"models": str(tmp_path / "models")}),
        workspace=str(tmp_path),
        run_task_data_path=None,
        run_metric=metric,
        run_secondary_metrics=(),
    )
    prepared = SimpleNamespace(
        record_params={},
        hypothesis="fixture",
        ordering=None,
        exp_id="candidate",
        model_type="regressor",
        plan=SimpleNamespace(is_trial=False),
        task_scopes=SimpleNamespace(evaluation=None),
        eval_sample_set={0: [1]},
        active_params={"model_config": {"width": 2}, "train_config": {"epochs": 2}},
    )
    events = []
    monkeypatch.setattr(
        execution, "_emit_attempt_record", lambda sandbox, record, *a, **kw: events.append(record)
    )

    def forbid_local(*a, **kw):
        pytest.fail("bound external evaluation fell back to private local execution")

    monkeypatch.setattr(execution, "_run_local_evaluation_phase", forbid_local)
    monkeypatch.setattr(
        execution, "finalize_attempt_outputs", lambda **kw: events.append("cleanup")
    )

    def run():
        return execution.run_inference_scoring_health(
            bindings,
            prepared,
            SimpleNamespace(attempt_in_round=1, round_index=1),
            SimpleNamespace(name="training"),
            train_time=1.0,
            training_results=SimpleNamespace(legacy_payload={"final_loss": 2.0}, history=None),
        )

    return run, events


@pytest.mark.parametrize("eligible", [True, False])
def test_native_caller_preserves_evaluator_scope_health_and_diagnosis(attempt, eligible):
    run, events = attempt
    evaluator = Evaluator(eligible=eligible)
    with bind_candidate_evaluation(evaluator):
        result = run()
    assert len(evaluator.requests) == 1
    assert result.external_evaluation.evaluated_scope == {
        "split": "validation",
        "all_samples": True,
    }
    assert result.external_evaluation.requested_scope == {"sample_set": {"0": [1]}}
    assert result.external_evaluation.metric.scalar == 0.25
    assert result.score_results["denoising_score"] == (0.25 if eligible else None)
    assert result.is_degenerate is (not eligible)
    assert result.train_results == {"final_loss": 2.0}
    assert result.training_diagnosis.state == "absent"
    assert result.scoring_time >= 0
    assert events == ["cleanup"]
    assert candidate_evaluation_executor() is None


@pytest.mark.parametrize(
    "fault", ["transport", "identity", "metric", "scope", "nonfinite", "health", "secondary"]
)
def test_broken_external_evaluation_cannot_fall_back_or_skip_cleanup(attempt, fault):
    run, events = attempt
    with bind_candidate_evaluation(Evaluator(fault=fault)):
        with pytest.raises((RuntimeError, ValueError)):
            run()
    assert events == ["cleanup"]
    assert candidate_evaluation_executor() is None


def test_nested_binding_restores_previous_executor_on_exception():
    outer, inner = Evaluator(), Evaluator()
    with bind_candidate_evaluation(outer):
        with pytest.raises(RuntimeError), bind_candidate_evaluation(inner):
            assert candidate_evaluation_executor() is inner
            raise RuntimeError("interrupted nested call")
        assert candidate_evaluation_executor() is outer
    assert candidate_evaluation_executor() is None


def test_scientific_refusal_keeps_original_receipt_in_failure_record(attempt):
    run, events = attempt
    with bind_candidate_evaluation(Evaluator(eligible=False, fault="refusal")):
        outcome = run()
    assert outcome.signal.value == "next_attempt"
    record, cleaned = events
    assert cleaned == "cleanup"
    assert record["status"] == "error_scoring"
    assert record["failure_type"] == "not_scoreable"
    assert record["external_evaluation"]["receipt_path"] == "/operator/receipt.json"
    assert (
        record["external_evaluation"]["metric"]["verdict"]["failures"][0]["detail"]
        == "missing prediction"
    )
