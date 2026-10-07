"""Typed evidence and admission authority for bounded inference observations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.schemas.preflight import StaticPhaseDecision, StaticPreflightEvidence
from core.runtime_control.gpu_measurement_classifier import classify_measurement
from core.runtime_control.gpu_measurement_runner import PrephaseMeasurementRun
from core.runtime_control.gpu_requirement import CandidateMeasurementRequest
from core.runtime_control.inference_measurement_binding import InferenceMeasurementBinding

Disposition = Literal["admitted", "capacity_refused", "unavailable"]


def eligible_inference_refusal(evidence: StaticPreflightEvidence) -> StaticPhaseDecision | None:
    """Only the final inference VRAM refusal after a passing training check."""
    if tuple(phase.phase for phase in evidence.phases) != ("training", "inference"):
        return None
    training, inference = evidence.phases
    if training.binding_caps or inference.binding_caps != ("vram",):
        return None
    return inference


class InferenceVerification(BaseModel):
    """Compact replayable decision evidence; raw samples remain in the workspace."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    version: Literal["bounded-inference-v1"] = "bounded-inference-v1"
    static_evidence: StaticPreflightEvidence
    max_batches: int = Field(gt=0)
    request: CandidateMeasurementRequest | None = None
    binding: InferenceMeasurementBinding | None = None
    measurement: PrephaseMeasurementRun | None = None
    raw_evidence_path: str | None = None
    unavailable_reason: str = ""

    @model_validator(mode="after")
    def _must_describe_an_eligible_refusal(self):
        if eligible_inference_refusal(self.static_evidence) is None:
            raise ValueError("Bounded inference verification cannot clear this static refusal")
        return self

    @property
    def assessment(self) -> tuple[Disposition, str]:
        phase = eligible_inference_refusal(self.static_evidence)
        assert phase is not None
        run = self.measurement
        if run is None:
            return (
                "unavailable",
                self.unavailable_reason or "No bounded inference measurement exists",
            )
        if (
            self.request is None
            or run.request != self.request
            or self.binding is None
            or run.inference_binding != self.binding
            or run.request.phase != "inference"
            or run.request.planned_identity.inference_batch_size != phase.batch_size
        ):
            return "unavailable", "Inference measurement request/source identity mismatch"
        if run.observed_device_uuid != run.request.device_uuid:
            return "unavailable", "Inference measurement device identity mismatch"
        if run.process.orphans_remaining:
            return "unavailable", "Inference measurement left an unreaped process group"
        if (
            run.process.exit_code != 0
            or run.process.term_sent
            or run.process.kill_sent
            or run.process.group_cleanup_required
            or run.deadline.reached_deadline
        ):
            return (
                "unavailable",
                "Inference worker did not complete within its bounded process lifecycle",
            )
        cap_mib = phase.vram_cap_bytes // 1024**2
        requirement = classify_measurement(run, vram_cap_mib=cap_mib)
        if requirement.outcome in {"MEASURED_CUDA_OOM", "MEASURED_PEAK_ABOVE_VRAM_CAP"}:
            return "capacity_refused", requirement.detail
        if not requirement.authoritative or requirement.outcome != "COMPLETED_MEASUREMENT":
            return "unavailable", f"{requirement.outcome}: {requirement.detail}"
        for name in ("setup", "inference"):
            observed = run.phase(name)
            if (
                observed is None
                or observed.status != "COMPLETED"
                or not observed.sampler_ready
                or not observed.coverage.complete
                or observed.driver_tree_peak_mib is None
            ):
                return (
                    "unavailable",
                    f"Incomplete {name} sampling; observed memory is only a lower bound",
                )
            if observed.driver_tree_peak_mib > cap_mib:
                return (
                    "capacity_refused",
                    f"Measured {name} driver peak {observed.driver_tree_peak_mib} MiB exceeds {cap_mib} MiB",
                )
            peak = observed.allocator_reserved_peak_bytes
            holds = observed.observed_reservations
            expected_count = 1 if name == "setup" else run.realism.inference_batches
            if peak is None or not holds or len(holds) != expected_count:
                return "unavailable", f"Missing {name} reservation hold evidence"
            for sequence, hold in enumerate(holds):
                if (
                    not hold.acknowledged
                    or hold.required_samples < 1
                    or hold.driver_samples < hold.required_samples
                    or hold.hold_id != f"{run.request.request_id}:{name}:{sequence}"
                    or hold.reserved_before_bytes != hold.reserved_after_bytes
                    or hold.started_at < observed.started_at
                    or hold.ended_at > observed.ended_at
                ):
                    return "unavailable", f"Incomplete or inconsistent {name} reservation hold"
            if peak > max(hold.reserved_before_bytes for hold in holds):
                return (
                    "unavailable",
                    f"{name} reserved high-water was not resident during a driver-observed hold",
                )
        data = run.realism.inference_data
        if (
            data is None
            or data.consumed_samples != data.selected_samples
            or data.selected_samples
            != min(data.dataset_samples, phase.batch_size * self.max_batches)
            or data.selected_batches != len(data.batches)
            or run.realism.inference_batches != data.selected_batches
            or run.realism.forward_calls != data.selected_batches
            or run.realism.backward_calls != 0
            or run.realism.optimizer_steps != 0
            or run.realism.inference_grad_free is not True
        ):
            return "unavailable", "Incomplete or inconsistent evaluation workload coverage"
        sizes = [batch.shape[0] for batch in data.batches if batch.shape]
        if (
            len(sizes) != data.selected_batches
            or sum(sizes) != data.selected_samples
            or any(size != phase.batch_size for size in sizes[:-1])
            or not sizes
            or not 0 < sizes[-1] <= phase.batch_size
            or any(
                not batch.output_shape or batch.output_shape[0] != batch.shape[0]
                for batch in data.batches
            )
        ):
            return "unavailable", "Evaluation batch geometry differs from the requested workload"
        return "admitted", (
            f"Bounded inference verification passed at batch {phase.batch_size}: "
            f"{data.consumed_samples}/{data.dataset_samples} evaluation samples. "
            "This does not certify later inputs or trained-weight behavior."
        )
