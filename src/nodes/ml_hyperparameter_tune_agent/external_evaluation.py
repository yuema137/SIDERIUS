"""Adapt an explicit complete-evaluation executor to native tuner stage facts."""

import time

from execute_tools.evaluation_execution import (
    CandidateEvaluationExecutor,
    CandidateEvaluationRefused,
    CandidateEvaluationRequest,
    execute_candidate_evaluation,
)
from execute_tools.evaluation_metric import MetricResult, NotScoreableResult
from execute_tools.health_checks.schemas import GateAction
from nodes.ml_hyperparameter_tune_agent.contracts import (
    AttemptStage,
    EvaluationPhaseEvidence,
    PreparedAttempt,
    RunBindings,
)


def run_external_evaluation(
    executor: CandidateEvaluationExecutor,
    bindings: RunBindings,
    prepared: PreparedAttempt,
    stage: AttemptStage,
) -> EvaluationPhaseEvidence:
    """Preserve evaluator facts; common native interpretation and cleanup run next."""
    scope = prepared.task_scopes.evaluation
    request = CandidateEvaluationRequest(
        run_name=bindings.run_name,
        exp_id=str(prepared.exp_id),
        model_type=prepared.model_type,
        workspace=bindings.workspace,
        models_dir=bindings.sandbox.dirs["models"],
        model_configuration=prepared.active_params["model_config"],
        training_configuration=prepared.active_params["train_config"],
        loss_configuration=prepared.active_params["loss_config"],
        model_io=bindings.run_model_io,
        requested_scope=(
            scope.model_dump(mode="json")
            if scope is not None
            else {"sample_set": {str(k): v for k, v in prepared.eval_sample_set.items()}}
        ),
        metric=bindings.run_metric.spec,
        secondary_metrics=tuple(metric.spec for metric in bindings.run_secondary_metrics),
        is_trial=prepared.plan.is_trial,
    )
    stage.name = "scoring"
    started = time.perf_counter()
    result = execute_candidate_evaluation(executor, request)
    elapsed = time.perf_counter() - started
    if isinstance(result.metric, NotScoreableResult):
        raise CandidateEvaluationRefused(result)
    assert isinstance(result.metric, MetricResult)
    metric = result.metric
    score_results = {
        "denoising_score": metric.scalar,
        "file_vector": metric.per_sample,
        "is_degenerate": not result.eligible_for_selection,
        "failure_reason": result.failure_reason,
        "gate_action": (
            GateAction.CONTINUE if result.eligible_for_selection else GateAction.INVALIDATE_ROUND
        ).value,
        "health_gate_results": [
            item.model_dump(mode="json") for item in result.health_gate_results
        ],
    }
    return EvaluationPhaseEvidence(
        # No local inference skill ran. Combined evaluation wall time belongs
        # to this external stage and is labelled in its persisted evidence.
        inf_status={"status": "success", "execution": "external_complete_evaluation"},
        inference_time=0.0,
        scoring_time=elapsed,
        score_res={"status": "success", "results": score_results},
        metric_payload=metric.model_dump(mode="json", exclude={"per_sample"}),
        secondary_results=list(result.secondary_results),
        secondary_refusals=list(result.secondary_refusals),
        secondary_errors=dict(result.secondary_errors),
        external_evaluation=result,
    )
