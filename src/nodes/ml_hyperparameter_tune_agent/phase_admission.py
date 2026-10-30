"""Shared training/inference admission recovery, without candidate replanning."""

from typing import Literal

from pydantic import TypeAdapter, ValidationError

from core.runtime_control.admission import AdmissionDecision, AdmissionReason
from nodes.ml_hyperparameter_tune_agent import runtime
from nodes.ml_hyperparameter_tune_agent.contracts import (
    AttemptIdentity,
    PreparedAttempt,
    RunBindings,
)
from nodes.ml_hyperparameter_tune_agent.records import RESOURCE_ADMISSION_STATUS


def normalize_phase_admission_refusal(status: dict) -> AdmissionDecision:
    """Normalize once for both the refusal record and the phase stop decision.

    Preserve recognized reason codes even when the full decision cannot validate.
    Missing/unknown codes become policy_unavailable; retain raw evidence for diagnosis.
    """
    raw = status.get("admission") or {}
    admission = dict(raw) if isinstance(raw, dict) else {}
    admission["reason_code"] = admission.get("reason_code") or "policy_unavailable"
    try:
        return AdmissionDecision.model_validate(admission)
    except ValidationError:
        try:
            reason_code = TypeAdapter(AdmissionReason).validate_python(admission["reason_code"])
        except ValidationError:
            reason_code = "policy_unavailable"
        return AdmissionDecision(
            admitted=False,
            reason_code=reason_code,
            requirement_source="unavailable",
            reason=str(status.get("message") or "The environment refused the phase."),
            evidence={"invalid_admission": raw},
        )


def run_admitted_skill(
    bindings: RunBindings,
    prepared: PreparedAttempt,
    identity: AttemptIdentity,
    *,
    phase: Literal["training", "inference"],
) -> tuple[dict, AdmissionDecision | None]:
    """Retry sampler failures within remaining attempt slots; record final refusal.

    Retrying the refused phase cannot repeat successful training when inference
    sampling fails. No worker started on a refusal. Exhaustion is an environment
    abort, never negative model evidence or a reason to request a new plan.
    """
    inputs = bindings.agent_input
    budget = (
        inputs.attempts_per_formal_round if identity.is_formal_round else inputs.attempts_per_round
    )
    remaining = max(1, budget - identity.attempt_in_round + 1)
    for sample_attempt in range(remaining):
        status = runtime._run_skill(f"{phase}_skill", bindings.sandbox, **prepared.active_params)
        if status.get("status") != RESOURCE_ADMISSION_STATUS:
            return status, None
        refusal = normalize_phase_admission_refusal(status)
        if refusal.refusal_kind == "transient_sampling" and sample_attempt + 1 < remaining:
            print(f"  Retrying {phase} admission sampling ({sample_attempt + 1}/{remaining})")
            continue
        status = {**status, "admission": refusal.model_dump(mode="json")}
        runtime._handle_admission_refusal(
            status,
            ordering=prepared.ordering,
            phase=phase,
            sandbox=bindings.sandbox,
            exp_id=prepared.exp_id,
            model_type=prepared.model_type,
            file_index=bindings.file_index,
            record_params=prepared.record_params,
            expert_advice_str=bindings.expert_advice_str,
            hypothesis=prepared.hypothesis,
            round_index=identity.round_index,
            attempt_in_round=identity.attempt_in_round,
            candidate_id=inputs.candidate_id,
            experiment_arm=inputs.experiment_arm,
            is_trial=prepared.plan.is_trial,
        )
        return status, refusal if refusal.refusal_kind != "resource" else None
    raise AssertionError("positive admission sampling budget required")
