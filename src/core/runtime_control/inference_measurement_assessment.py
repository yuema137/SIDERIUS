"""Complete reusable inference evidence assessment, independent of static refusal."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.runtime_control.gpu_measurement_classifier import classify_measurement
from core.runtime_control.gpu_measurement_runner import PrephaseMeasurementRun
from core.runtime_control.gpu_requirement import CandidateMeasurementRequest
from core.runtime_control.inference_checkpoint_reference import InferenceCheckpointReference
from core.runtime_control.inference_measurement_binding import InferenceMeasurementBinding

Disposition = Literal["admitted", "capacity_refused", "unavailable"]


class InferenceMeasurementAssessment(BaseModel):
    """A bounded workload verdict, with whole-worker demand only after all checks."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    disposition: Disposition
    detail: str
    worker_requirement_mib: int | None = Field(default=None, ge=0)


def assess_inference_measurement(
    *,
    request: CandidateMeasurementRequest | None,
    binding: InferenceMeasurementBinding | None,
    run: PrephaseMeasurementRun | None,
    batch_size: int,
    max_batches: int,
    cap_mib: int,
    checkpoint: InferenceCheckpointReference | None = None,
    unavailable_reason: str = "",
) -> InferenceMeasurementAssessment:
    """Require setup, holds, evaluation geometry, source identity and clean exit."""
    if batch_size < 1 or max_batches < 1 or cap_mib < 0:
        raise ValueError(
            "inference assessment needs positive workload bounds and a nonnegative cap"
        )
    disposition, detail = _assess(
        request=request,
        binding=binding,
        run=run,
        batch_size=batch_size,
        max_batches=max_batches,
        cap_mib=cap_mib,
        checkpoint=checkpoint,
        unavailable_reason=unavailable_reason,
    )
    peak = None
    if disposition == "admitted":
        assert run is not None
        peaks = [run.phase(name) for name in ("setup", "inference")]
        peak = max(
            p.driver_tree_peak_mib
            for p in peaks
            if p is not None and p.driver_tree_peak_mib is not None
        )
    return InferenceMeasurementAssessment(
        disposition=disposition, detail=detail, worker_requirement_mib=peak
    )


def _assess(
    *,
    request: CandidateMeasurementRequest | None,
    binding: InferenceMeasurementBinding | None,
    run: PrephaseMeasurementRun | None,
    batch_size: int,
    max_batches: int,
    cap_mib: int,
    checkpoint: InferenceCheckpointReference | None,
    unavailable_reason: str,
) -> tuple[Disposition, str]:
    if run is None:
        return (
            "unavailable",
            unavailable_reason or "No bounded inference measurement exists",
        )
    if (
        request is None
        or run.request != request
        or binding is None
        or run.inference_binding != binding
        or run.request.phase != "inference"
        or run.request.planned_identity.inference_batch_size != batch_size
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
    if checkpoint is not None and run.verified_checkpoint != checkpoint:
        return "unavailable", "Inference checkpoint was not verified and loaded for this request"
    if checkpoint is None and run.verified_checkpoint is not None:
        return "unavailable", "Unexpected checkpoint in fresh-model inference measurement"
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
        from core.runtime_control.measurement_hold_assessment import reservation_hold_refusal

        refusal = reservation_hold_refusal(
            observed,
            request_id=run.request.request_id,
            expected_count=1 if name == "setup" else run.realism.inference_batches,
        )
        if refusal is not None:
            return "unavailable", refusal
    data = run.realism.inference_data
    if (
        data is None
        or data.consumed_samples != data.selected_samples
        or data.selected_samples != min(data.dataset_samples, batch_size * max_batches)
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
        or any(size != batch_size for size in sizes[:-1])
        or not sizes
        or not 0 < sizes[-1] <= batch_size
        or any(
            not batch.output_shape or batch.output_shape[0] != batch.shape[0]
            for batch in data.batches
        )
    ):
        return "unavailable", "Evaluation batch geometry differs from the requested workload"
    if checkpoint is not None:
        return "admitted", (
            f"Bounded inference measurement passed at batch {batch_size}: "
            f"{data.consumed_samples}/{data.dataset_samples} evaluation samples with "
            f"verified checkpoint {checkpoint.checkpoint_sha256}. "
            "This does not certify later inputs or scientific performance."
        )
    return "admitted", (
        f"Bounded inference verification passed at batch {batch_size}: "
        f"{data.consumed_samples}/{data.dataset_samples} evaluation samples. "
        "This does not certify later inputs or trained-weight behavior."
    )
