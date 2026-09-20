"""A public task composes and executes without shipping private metric source."""

import shutil
from pathlib import Path

import pytest
import yaml

from execute_tools.evaluation_execution import (
    CandidateEvaluationRequest,
    CandidateEvaluationResult,
    bind_candidate_evaluation,
)
from execute_tools.evaluation_metric import (
    CandidateEvaluationMetric,
    MetricResult,
    NoRunMetricError,
    bind_run_metric,
    resolve_run_metric,
)
from workflows.task_composition import (
    TaskCompositionError,
    compose_metric_from_manifest,
    compose_run_task_bindings,
)


@pytest.fixture
def public_task(tmp_path):
    source = Path(__file__).resolve().parents[3] / "tests/fixtures/step10_p1/fourth_task"
    task = tmp_path / "public"
    shutil.copytree(source, task)
    original = compose_run_task_bindings(str(task / "composition.yaml"))
    manifest = yaml.safe_load((task / "composition.yaml").read_text())
    (task / manifest["metric"]["implementation"]["file"]).unlink()
    manifest["metric"]["implementation"] = {
        "module": "execute_tools.evaluation_metric",
        "symbol": "CandidateEvaluationMetric",
    }
    (task / "composition.yaml").write_text(yaml.safe_dump(manifest))
    return task, original


def test_missing_private_implementation_composes_with_explicit_candidate_execution(
    public_task, tmp_path
):
    task, original = public_task
    composition = compose_run_task_bindings(str(task / "composition.yaml"))
    assert isinstance(composition.metric, CandidateEvaluationMetric)
    assert composition.metric.spec.model_dump() == original.metric.spec.model_dump()
    assert composition.semantic_fingerprint != original.semantic_fingerprint
    moved = tmp_path / "relocated"
    shutil.copytree(task, moved)
    assert (
        compose_run_task_bindings(str(moved / "composition.yaml")).semantic_fingerprint
        == composition.semantic_fingerprint
    )
    with (
        bind_run_metric(composition.metric),
        pytest.raises(NoRunMetricError, match="complete evaluator"),
    ):
        resolve_run_metric()
    with pytest.raises(TaskCompositionError, match="not the local scoring child"):
        compose_metric_from_manifest(str(task / "composition.yaml"))


def test_declared_candidate_metric_calls_actual_executor_and_checks_scientific_identity(
    public_task, tmp_path
):
    task, _ = public_task
    metric = compose_run_task_bindings(str(task / "composition.yaml")).metric
    calls = []

    class Executor:
        def evaluate(self, request):
            calls.append(request)
            return CandidateEvaluationResult(
                run_name=request.run_name,
                exp_id=request.exp_id,
                model_type=request.model_type,
                candidate_digest="test",
                receipt_path="/evaluator/result.json",
                requested_scope=request.requested_scope,
                evaluated_scope={"complete": True},
                metric=MetricResult(
                    metric_id=request.metric.id, direction=request.metric.direction, scalar=0.75
                ),
                health_status="valid",
                health_gate_results=(),
                health_config_digest="test",
                eligible_for_selection=True,
            )

    request = CandidateEvaluationRequest(
        run_name="run",
        exp_id="attempt",
        model_type="candidate",
        workspace=str(tmp_path),
        models_dir=str(tmp_path / "models"),
        model_configuration={},
        training_configuration={},
        requested_scope={"subset": [1]},
        metric=metric.spec,
        is_trial=True,
    )
    with bind_candidate_evaluation(Executor()), bind_run_metric(metric):
        assert resolve_run_metric() is metric
        result = metric.evaluate_candidate(request)
        assert result.metric.scalar == 0.75
        wrong = request.model_copy(
            update={"metric": request.metric.model_copy(update={"aggregation": "different"})}
        )
        with pytest.raises(ValueError, match="composed metric declaration"):
            metric.evaluate_candidate(wrong)
    assert calls == [request]
