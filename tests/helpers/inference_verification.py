"""Admission must not turn incomplete inference observations into capacity facts."""

from __future__ import annotations

from agent.schemas.preflight import StaticPhaseDecision, StaticPreflightEvidence
from core.runtime_control.gpu_measurement_hold import ObservedReservation
from core.runtime_control.gpu_measurement_identity import (
    build_planned_identity,
    build_realized_identity,
)
from core.runtime_control.gpu_measurement_runner import (
    HostMemoryBound,
    PhaseMeasurement,
    PrephaseMeasurementRun,
    ProcessEvidence,
)
from core.runtime_control.gpu_measurement_spec import (
    InferenceBatchObservation,
    InferenceDataCoverage,
    RealismEvidence,
)
from core.runtime_control.gpu_requirement import (
    CandidateMeasurementRequest,
    MeasurementDeadline,
    SamplingCoverage,
)
from core.runtime_control.inference_measurement_binding import InferenceMeasurementBinding
from core.runtime_control.inference_verification_evidence import InferenceVerification

MIB = 1024**2


def _static(*, cap_mib=900, batch=2):
    return StaticPreflightEvidence(
        phases=(
            StaticPhaseDecision(
                phase="training",
                batch_size=2,
                vram_cap_bytes=cap_mib * MIB,
                vram_estimate_bytes=100 * MIB,
                estimator="training_saved_tensors_v1",
            ),
            StaticPhaseDecision(
                phase="inference",
                batch_size=batch,
                vram_cap_bytes=cap_mib * MIB,
                vram_estimate_bytes=2000 * MIB,
                estimator="inference_leaf_sum_v1",
            ),
        )
    )


def _verification(
    *, peak_bytes=500 * MIB, held_bytes=500 * MIB, driver_mib=800, samples=5, batch=2
):
    count = (samples + batch - 1) // batch
    request = CandidateMeasurementRequest(
        model_type="synthetic",
        request_id="req-inference",
        device_uuid="GPU-example",
        phase="inference",
        deadline_seconds=60,
        planned_identity=build_planned_identity(
            model_type="synthetic", model_config={}, train_config={}, inference_batch_size=batch
        ),
    )
    binding = InferenceMeasurementBinding(
        assembly_sha256="a" * 64,
        plugin_sources_sha256="b" * 64,
        runtime_sha256="c" * 64,
        request_sha256="d" * 64,
    )

    def phase(name, start, units):
        return PhaseMeasurement(
            phase=name,
            status="COMPLETED",
            started_at=start,
            ended_at=start + 10,
            elapsed_seconds=10,
            driver_tree_peak_mib=driver_mib,
            allocator_peak_mib=held_bytes // MIB,
            allocator_reserved_peak_mib=peak_bytes // MIB,
            allocator_reserved_peak_bytes=peak_bytes,
            observed_reservations=tuple(
                ObservedReservation(
                    hold_id=f"req-inference:{name}:{i}",
                    started_at=start + i + 1,
                    ended_at=start + i + 1.5,
                    reserved_before_bytes=held_bytes,
                    reserved_after_bytes=held_bytes,
                    acknowledged=True,
                    driver_samples=3,
                    required_samples=3,
                )
                for i in range(units)
            ),
            coverage=SamplingCoverage(interval_seconds=0.1, samples_taken=30),
            own_pids=(4242,),
            units_executed=units,
            units_requested=units,
        )

    sizes = [min(batch, samples - offset) for offset in range(0, samples, batch)]
    run = PrephaseMeasurementRun(
        label="synthetic",
        request=request,
        inference_binding=binding,
        worker_status="COMPLETED",
        report_present=True,
        observed_device_uuid="GPU-example",
        reported_request_id=request.request_id,
        realized_identity=build_realized_identity(
            model_type="synthetic",
            optimizer_type="adamw",
            seg_size=40000,
            batch_size=1,
            precision="float32",
            parameter_count=100,
            trainable_parameter_count=100,
            inference_batch_size=batch,
        ),
        phases=(phase("setup", 100, 1), phase("inference", 120, count)),
        realism=RealismEvidence(
            forward_calls=count,
            inference_batches=count,
            inference_grad_free=True,
            inference_data=InferenceDataCoverage(
                dataset_samples=samples,
                selected_samples=samples,
                consumed_samples=samples,
                selected_batches=count,
                batches=tuple(
                    InferenceBatchObservation(
                        shape=(size, 4),
                        storage_dtype="float32",
                        input_dtype="float32",
                        output_shape=(size, 1),
                    )
                    for size in sizes
                ),
            ),
        ),
        deadline=MeasurementDeadline(budget_seconds=60, elapsed_seconds=30),
        host_memory=HostMemoryBound(limit_bytes=2**30, peak_tree_rss_bytes=1000000),
        process=ProcessEvidence(worker_pid=4242, worker_pgid=4242, exit_code=0),
    )
    return InferenceVerification(
        static_evidence=_static(batch=batch),
        max_batches=count,
        request=request,
        binding=binding,
        measurement=run,
    )
