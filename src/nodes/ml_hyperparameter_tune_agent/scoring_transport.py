"""Typed child score adoption and source-independent Health invocation context."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from execute_tools.evaluation_child import validate_child_evaluation
from execute_tools.health_checks.config import default_health_policy_path
from execute_tools.health_checks.schemas import PerSampleEvidence
from nodes.ml_hyperparameter_tune_agent.contracts import (
    AttemptIdentity,
    PreparedAttempt,
    RunBindings,
)
from nodes.ml_hyperparameter_tune_agent.round_health import build_evaluation_payload_fn


@dataclass(frozen=True)
class ChildScoreFacts:
    scalar: float | None
    file_vector: list[float | None]
    per_sample: PerSampleEvidence


def adopt_child_score(
    bindings: RunBindings, score: dict[str, Any], require_success: Callable
) -> ChildScoreFacts:
    """Adopt one scoring-child envelope after checking its status and evidence.

    Status comes first: a crashed or OOM-killed scorer (empty JSON) must keep
    its infrastructure status and stderr through ``require_success`` instead of
    surfacing as malformed evaluation evidence. The one non-success envelope
    inspected before that is a structured formula refusal (status ``error``
    with ``evaluation_result``), which ``validate_child_evaluation`` raises as
    a typed not-scoreable refusal carrying its component evidence.
    """
    results = score.get("results", {}) or {}
    carrier = getattr(bindings.agent_input, "task_composition_ref", None)
    status = score.get("status")
    if status == "success" or (status == "error" and "evaluation_result" in results):
        validate_child_evaluation(results, carrier)
    require_success(score)
    # F2 — carry the same three round facts the anchor route produces
    # in-process, so the round-boundary gate evaluation is genuinely
    # route-independent rather than an anchor branch with a second entrance.
    #
    # `per_sample_evidence` is TRANSPORTED, never inferred. The child sets
    # `file_vector` from `MetricResult.per_sample`, which is `None` exactly
    # when the metric declares no per-sample concept — so D18's mapping
    # applies verbatim. A payload that omits the key entirely has stated
    # NOTHING, and absence must not be read as `scalar_only`: that is the
    # distinction `PerSampleEvidence.UNDECLARED` exists to keep.
    return ChildScoreFacts(
        scalar=results.get("denoising_score"),
        file_vector=list(results.get("file_vector") or []),
        per_sample=(
            PerSampleEvidence.for_per_sample(results.get("file_vector"))
            if "file_vector" in results
            else PerSampleEvidence.UNDECLARED
        ),
    )


def health_arguments(
    bindings: RunBindings,
    prepared: PreparedAttempt,
    identity: AttemptIdentity,
    denoised_filename_fn: Callable,
) -> dict[str, Any]:
    """Build invocation context; round_health separately chooses source values."""
    inp = bindings.agent_input
    sandbox = bindings.sandbox
    return {
        "enabled": inp.health_gate_enabled,
        "round_index": identity.round_index,
        "config_path": inp.health_checks_config,
        "production_config_path": default_health_policy_path(),
        "task_health_binding": inp.task_composition_ref.task_health_binding
        if inp.task_composition_ref
        else None,
        "model_name": prepared.model_type,
        "run_name": bindings.run_name,
        "exp_id": prepared.exp_id,
        "models_dir": sandbox.dirs.get("models")
        if isinstance(getattr(sandbox, "dirs", None), dict)
        else None,
        "denoised_filename_fn": denoised_filename_fn,
        "evaluation_payload_fn": build_evaluation_payload_fn(
            task_data_path=bindings.run_task_data_path,
            deliverable_dir=sandbox.base_dir,
            exp_id=prepared.exp_id,
            run_name=bindings.run_name,
            model_type=prepared.model_type,
        ),
    }
