"""Training-specific eligibility for a bounded setup-plus-work observation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.runtime_control.gpu_measurement_classifier import classify_measurement
from core.runtime_control.gpu_measurement_runner import PrephaseMeasurementRun
from core.runtime_control.gpu_measurement_spec import GpuMeasurementSpec
from core.runtime_control.gpu_requirement_evidence import GpuRequirementOwnership
from core.runtime_control.inference_measurement_binding import measurement_request_digest
from core.runtime_control.measurement_hold_assessment import reservation_hold_refusal
from core.runtime_control.training_measurement_binding import validate_training_measurement_request


class TrainingMeasurementAssessment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    disposition: Literal["admitted", "capacity_refused", "unavailable"]
    detail: str
    worker_requirement_mib: int | None = Field(default=None, ge=0)


def assess_training_measurement(
    spec: GpuMeasurementSpec, run: PrephaseMeasurementRun, *, cap_mib: int
) -> TrainingMeasurementAssessment:
    """Never substitute target-only memory or parameter motion for complete evidence."""
    if isinstance(cap_mib, bool) or not isinstance(cap_mib, int) or cap_mib < 0:
        raise ValueError("training assessment requires a nonnegative cap")
    refusal = _evidence_refusal(spec, run)
    if refusal is not None:
        return TrainingMeasurementAssessment(disposition="unavailable", detail=refusal)
    peak = max(
        phase.driver_tree_peak_mib
        for name in ("setup", "training")
        if (phase := run.phase(name)) is not None and phase.driver_tree_peak_mib is not None
    )
    if peak > cap_mib:
        return TrainingMeasurementAssessment(
            disposition="capacity_refused",
            detail=f"Measured whole-worker driver peak {peak} MiB exceeds {cap_mib} MiB",
        )
    return TrainingMeasurementAssessment(
        disposition="admitted",
        worker_requirement_mib=peak,
        detail="Bounded training setup/work measurement passed; unseen workloads may peak higher",
    )


def _evidence_refusal(spec: GpuMeasurementSpec, run: PrephaseMeasurementRun) -> str | None:
    try:
        validate_training_measurement_request(spec)
    except ValueError as error:
        return str(error)
    binding = spec.training_binding
    if (
        binding is None
        or run.training_binding != binding
        or run.request != spec.request
        or binding.request_sha256
        != measurement_request_digest(spec, binding_field="training_binding")
    ):
        return "Training measurement request/source identity mismatch"
    if run.observed_device_uuid != spec.request.device_uuid:
        return "Training measurement device identity mismatch"
    ownership = GpuRequirementOwnership(
        domain="new_worker_process_tree", device_uuid=run.observed_device_uuid, process=run.process
    )
    if (
        ownership.completion_refusal
        or run.process.final_group_observation is None
        or run.deadline.reached_deadline
    ):
        return "Training worker did not establish a bounded clean completed lifecycle"
    if (
        run.host_memory.observations_complete is not True
        or run.host_memory.latest_observation is None
        or run.host_memory.latest_observation.status != "complete"
    ):
        return "training_host_monitoring_unavailable"
    raw = classify_measurement(run)
    if not raw.authoritative or raw.outcome != "COMPLETED_MEASUREMENT":
        return f"{raw.outcome}: {raw.detail}"
    realism = run.realism
    steps = realism.training_steps
    work = run.phase("training")
    if (
        work is None
        or steps is None
        or not steps.optimizer_matches_model_parameters
        or not 0
        < work.units_executed
        == realism.forward_calls
        == realism.backward_calls
        == realism.optimizer_steps
        == steps.connected_backward_calls
        or realism.inference_batches != 0
    ):
        return "Incomplete training optimizer/connected-backward evidence"
    for name in ("setup", "training"):
        phase = run.phase(name)
        if (
            phase is None
            or phase.status != "COMPLETED"
            or not phase.sampler_ready
            or not phase.coverage.complete
            or phase.driver_tree_peak_mib is None
        ):
            return f"Incomplete {name} sampling; observed memory is only a lower bound"
        refusal = reservation_hold_refusal(
            phase,
            request_id=spec.request.request_id,
            expected_count=1 if name == "setup" else realism.optimizer_steps,
        )
        if refusal:
            return refusal
    return _data_refusal(spec, run)


def _data_refusal(spec: GpuMeasurementSpec, run: PrephaseMeasurementRun) -> str | None:
    from ml_models.models_format_sandbox import TrainConfig

    config = TrainConfig.model_validate(spec.train_config)
    data = run.realism.training_data
    reference = spec.task_probe_data
    assert reference is not None
    if (
        data is None
        or data.sampling != reference.sampling
        or data.configured_batch_size != config.batch_size
    ):
        return "Training data sampling/configured batch evidence mismatch"
    expected_rows = min(data.materialized_dataset_rows, config.batch_size)
    if (
        (config.drop_last and expected_rows != config.batch_size)
        or data.observed_batch_rows != expected_rows
        or any(
            not shape or shape[0] != expected_rows
            for shape in (data.input_shape, data.target_shape, data.observed_output_shape)
        )
    ):
        return "Training batch geometry differs from the requested workload"
    if config.target_standardization == "none":
        if (
            data.fitting_sampling is not None
            or data.standardization is not None
            or run.realism.training_standardization is not None
        ):
            return "Unexpected training target standardization"
    elif (
        data.fitting_sampling != reference.sampling.model_copy(update={"train_portion": 1.0})
        or data.standardization is None
        or run.realism.training_standardization != data.standardization
    ):
        return "Missing or mismatched authorized training-pool standardization"
    return None
