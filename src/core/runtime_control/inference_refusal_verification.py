"""Bounded evidence for one inference-only structural refusal.

The static observation is never rewritten as a successful estimate. This
module owns the separate decision to admit a bounded observed workload. It
does not search for a batch, cache observations, or modify training admission.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

from agent.schemas.preflight import StaticPreflightEvidence
from agent.skills.evaluate_vram_skill.isolated_probe import IsolatedProbeSpec
from core.inference_preflight_policy import InferencePreflightPolicy
from core.runtime_control.gpu_accounting import device_identity_from_hardware
from core.runtime_control.gpu_measurement_identity import build_planned_identity
from core.runtime_control.gpu_measurement_runner import (
    PrephaseMeasurementRun,
    run_prephase_measurement,
)
from core.runtime_control.gpu_measurement_spec import GpuMeasurementSpec
from core.runtime_control.gpu_requirement import CandidateMeasurementRequest
from core.runtime_control.inference_measurement_binding import (
    MeasurementSources,
    inference_measurement_binding,
)
from core.runtime_control.inference_verification_evidence import (
    InferenceVerification,
    eligible_inference_refusal,
)
from core.subprocess_env import subprocess_env


def verify_inference_refusal(
    *,
    static_evidence: StaticPreflightEvidence,
    static_spec: IsolatedProbeSpec,
    hardware_context: Any,
    policy: InferencePreflightPolicy,
    deadline_at: float,
) -> InferenceVerification:
    """Spend the remaining preflight budget on one worker, without batch search."""
    phase = eligible_inference_refusal(static_evidence)
    if phase is None:
        raise ValueError("Only an inference-only VRAM refusal can request bounded verification")
    base = InferenceVerification(static_evidence=static_evidence, max_batches=policy.max_batches)
    reference = static_spec.task_probe_data
    device = device_identity_from_hardware(hardware_context)
    remaining = deadline_at - time.monotonic()
    if reference is None or reference.evaluation_scope_payload is None:
        return base.model_copy(
            update={"unavailable_reason": "No explicit task evaluation scope was transported"}
        )
    hardware = static_spec.hardware
    if (
        device is None
        or device.logical_index is None
        or hardware is None
        or not hardware.device_available
    ):
        return base.model_copy(
            update={"unavailable_reason": "No verified CUDA device identity is available"}
        )
    if remaining <= 0:
        return base.model_copy(
            update={
                "unavailable_reason": "The total preflight deadline was spent on structural inspection"
            }
        )
    nonce = uuid.uuid4().hex
    root = Path(static_spec.result_path).parent / "inference_verification"
    prefix = root / nonce
    request = CandidateMeasurementRequest(
        model_type=static_spec.model_type,
        planned_identity=build_planned_identity(
            model_type=static_spec.model_type,
            model_config=static_spec.model_config_payload,
            train_config=static_spec.train_config,
            inference_batch_size=phase.batch_size,
            segmentation_applicability=reference.segmentation_applicability,
        ),
        request_id=nonce,
        device_uuid=device.uuid,
        phase="inference",
        deadline_seconds=remaining,
    )
    spec = GpuMeasurementSpec(
        label=f"{static_spec.label}:inference-verification",
        request=request,
        model_config_payload=static_spec.model_config_payload,
        train_config=static_spec.train_config,
        loss_config=static_spec.loss_config,
        expected_custom_loss_snapshot=static_spec.expected_custom_loss_snapshot,
        device=f"cuda:{device.logical_index}",
        data_dir=reference.sampling.data_dir,
        task_probe_data=reference,
        model_io_contract=static_spec.model_io_contract,
        plugin_dir=static_spec.plugin_dir,
        loss_dir=static_spec.loss_dir,
        inference_batches=policy.max_batches,
        inference_batch_size=phase.batch_size,
        result_path=str(prefix.with_suffix(".json")),
        journal_path=str(prefix.with_suffix(".jsonl")),
        sampler_ready_path=str(prefix.with_suffix(".ready")),
        setup_complete_path=str(prefix.with_suffix(".setup")),
        reservation_ack_path=str(prefix.with_suffix(".reservation")),
        phase_complete_path=str(prefix.with_suffix(".inference")),
        worker_memory_limit_bytes=static_spec.worker_memory_limit_bytes,
        max_phase_seconds=remaining,
        sampler_ready_timeout_seconds=remaining,
    )
    binding = inference_measurement_binding(
        spec, environ=subprocess_env(plugin_dir=spec.plugin_dir, loss_dir=spec.loss_dir)
    )
    sources = MeasurementSources.model_validate(
        binding.model_dump(include=set(MeasurementSources.model_fields))
    )
    if static_spec.candidate_sources is None or sources != static_spec.candidate_sources:
        return base.model_copy(
            update={
                "unavailable_reason": "Candidate sources changed or were not pinned before structural inspection"
            }
        )
    spec = spec.model_copy(update={"inference_binding": binding})
    run = run_prephase_measurement(spec, device=device, deadline_at=deadline_at)
    raw_path = prefix.with_suffix(".run.json")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(run.model_dump_json(indent=2), encoding="utf-8")
    compact = PrephaseMeasurementRun.model_validate(run.model_dump(exclude={"samples", "journal"}))
    return InferenceVerification(
        static_evidence=static_evidence,
        max_batches=policy.max_batches,
        request=request,
        binding=binding,
        measurement=compact,
        raw_evidence_path=str(raw_path),
    )


def verification_from_result(result: dict[str, Any]) -> InferenceVerification | None:
    raw = result.get("inference_verification")
    if raw is None:
        return None
    verification = InferenceVerification.model_validate(raw)
    if verification.static_evidence != StaticPreflightEvidence.model_validate(
        result.get("static_preflight_evidence")
    ):
        raise ValueError("Inference verification does not describe this static observation")
    return verification


def preflight_allows_execution(result: dict[str, Any]) -> bool:
    verification = verification_from_result(result)
    return (
        verification.assessment[0] == "admitted" if verification else result.get("feasible", True)
    )


def preflight_inference_batch(result: dict[str, Any]) -> int | None:
    verification = verification_from_result(result)
    if verification is not None and verification.assessment[0] == "admitted":
        phase = eligible_inference_refusal(verification.static_evidence)
        assert phase is not None
        return phase.batch_size
    return result.get("inference_batch")


def preflight_refusal_detail(result: dict[str, Any]) -> str:
    from agent.skills.evaluate_vram_skill.evidence import render_static_refusal

    verification = verification_from_result(result)
    if verification is not None:
        return verification.assessment[1]
    raw = result.get("static_preflight_evidence")
    if raw is not None:
        return render_static_refusal(StaticPreflightEvidence.model_validate(raw))
    return str(result.get("verdict", "No decision evidence recorded."))


def preflight_refusal_suggestion(result: dict[str, Any]) -> str:
    verification = verification_from_result(result)
    if verification is not None:
        return (
            "Inspect the bounded inference measurement and its evaluation coverage "
            "before changing the candidate. No layer-level cause was measured."
        )
    return str(
        result.get(
            "suggestion", "Inspect the recorded refusal evidence before changing the candidate."
        )
    )
