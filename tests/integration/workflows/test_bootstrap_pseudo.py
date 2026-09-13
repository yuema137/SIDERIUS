"""C10 pseudo integration — the bootstrap sequence over the REAL
subsystems, with only the device-touching seams faked.

Real here: the probe engine, the D3 contention classifier, the versioned
calibration registry (hash-verified), the observation builder, and the
production launch guard. Faked: the executors (no torch), the telemetry
sampler (no nvidia-smi) and the hardware collectors (no CUDA).

This is deterministic subsystem-composition evidence, not GPU timing or
measurement-validity qualification. The pseudo hardware has no device UUID,
so occupancy and measurement validity remain absent. See the integration
README for the exact offline command; ordinary unit CI excludes this module.
"""

from __future__ import annotations

import pytest

from core.runtime_control.bootstrap import BootstrapDependencies, run_bootstrap
from core.runtime_control.calibration_policy import sample_contention_window
from core.runtime_control.calibration_registry import CalibrationRegistry
from core.runtime_control.launch_guard import run_launch_self_test
from core.runtime_control.measurement_capability import ResolvedMeasurementCapability
from core.runtime_control.probe import (
    ContentionSnapshot,
    ProbeCaps,
    ProbeExecutors,
    RealizedModelProperties,
    probe_observations,
    run_bounded_probe,
)
from core.runtime_control.registry_schemas import (
    ExecutionEnvironmentProfile,
    HardwareCompatibilityProfile,
)

REALIZED = RealizedModelProperties(
    parameter_count=45_408,
    trainable_parameter_count=45_408,
    parameter_memory_gb=0.001,
    dtype="float32",
)
IDLE = ContentionSnapshot(
    telemetry_available=True,
    foreign_compute_processes=0,
    gpu_utilization_pct=1.0,
    gpu_memory_used_gb=0.2,
)
BUSY = ContentionSnapshot(
    telemetry_available=True,
    foreign_compute_processes=1,
    foreign_compute_pids=(9999,),
    gpu_utilization_pct=90.0,
    gpu_memory_used_gb=20.0,
)


def _executors(train_ms=17.6, infer_ms=8.1) -> ProbeExecutors:
    train = iter([train_ms] * 20)
    infer = iter([infer_ms] * 20)
    return ProbeExecutors(
        setup=lambda: REALIZED,
        train_step=lambda: next(train),
        inference_batch=lambda: next(infer),
        peak_vram_gb=lambda: 1.2,
    )


def _deps(tmp_path, *, snapshot=IDLE) -> BootstrapDependencies:
    def _sample(**kwargs):
        # REAL D3 classifier, deterministic samples, no sleeping.
        return sample_contention_window(
            device_vram_gb=kwargs.get("device_vram_gb", 32.0),
            expected_peer_pids=kwargs.get("expected_peer_pids", ()),
            capture=lambda *a, **k: snapshot,
            sleep=lambda _s: None,
        )

    def _run_probe(
        *,
        model_identity,
        executors,
        caps,
        device_vram_gb,
        expected_peer_pids,
        device_identity=None,
    ):
        # REAL probe engine. `device_identity` mirrors the production
        # injector (V20 FU-C-1): the bootstrap flow names its device so the
        # probe can build an occupancy window and produce a
        # `MeasurementValidity`. An injector that does not accept it is an
        # incomplete implementation of the deps contract — which is exactly
        # how FU-C-1 broke this suite silently.
        return run_bounded_probe(
            model_identity=model_identity,
            executors=executors,
            caps=ProbeCaps(**caps),
            device_vram_gb=device_vram_gb,
            expected_peer_pids=expected_peer_pids,
            device_identity=device_identity,
            contention_window=_sample,
        )

    def _observations(result, *, hardware_compatibility_id, execution_environment_id, workload):
        # REAL observation builder.
        return probe_observations(
            result,
            hardware_compatibility_id=hardware_compatibility_id,
            execution_environment_id=execution_environment_id,
            workload=workload,
            software_stack={"torch": "2.7.0"},
            source_run={"run_name": "bootstrap_pseudo"},
        )

    return BootstrapDependencies(
        collect_hardware=lambda: HardwareCompatibilityProfile(
            accelerator_vendor="NVIDIA",
            accelerator_model="pseudo-gpu",
            gpu_count=1,
            vram_gb=32.0,
            torch_version="2.7.0",
        ),
        collect_environment=lambda **kw: ExecutionEnvironmentProfile(**kw),
        build_registry=lambda: CalibrationRegistry(tmp_path / "runtime_calibration"),
        # Supply the task-owned verdict directly: the real resolver would
        # make this fixture depend on the host's CUDA and dataset availability.
        measurement_capability=lambda: ResolvedMeasurementCapability(
            task_identity="pseudo_bootstrap_task",
            dataset_adapter="pseudo_bootstrap_adapter",
            data_shape_class="pseudo_bootstrap_shape",
            probe_available=True,
            target_device="pseudo-gpu",
            dataset_root=str(tmp_path),
            supported_phases=("training", "inference"),
        ),
        sample_contention=_sample,
        build_executors=lambda **kw: _executors(),
        run_probe=_run_probe,
        build_observations=_observations,
        # REAL launch guard, without demanding a device.
        launch_self_test=lambda **kw: run_launch_self_test(require_probe_runner=False),
        device_vram_gb=lambda: 32.0,
    )


def _bootstrap(tmp_path, **over):
    return run_bootstrap(
        model_type="pseudo_bootstrap_model",
        model_config={"segmentation_size": 40_000},
        train_config={"batch_size": 8, "epochs": 1},
        loss_config={"loss_type": "ce"},
        deps=_deps(tmp_path, **over),
        caps={
            "max_wall_seconds": 30.0,
            "n_warmup_steps": 2,
            "n_timed_train_steps": 5,
            "n_timed_inference_batches": 3,
        },
    )


class TestBootstrapPseudo:
    def test_a_fresh_environment_bootstraps_to_ready(self, tmp_path):
        report = _bootstrap(tmp_path)
        assert report.ready is True, report.render()
        assert len(report.observation_ids) == 2

    def test_the_recorded_evidence_is_usable_by_the_next_run(self, tmp_path):
        """The point of bootstrapping: the registry now holds evidence a
        later run can price against."""
        report = _bootstrap(tmp_path)
        registry = CalibrationRegistry(tmp_path / "runtime_calibration")

        from core.runtime_control.calibration_policy import bucket_key, evaluate_promotions

        observations = list(registry.iter_observations())
        assert len(observations) == 2
        operations = {o.operation for o in observations}
        assert operations == {"training", "inference"}

        # One clean observation per bucket is a CANDIDATE, not calibration.
        assert evaluate_promotions(observations, generation=0) == []
        level, promotion = registry.bucket_status(bucket_key(observations[0]))
        assert (level, promotion) == ("unvalidated", None)

        # And it is local evidence, so a later run sees it as a prior until
        # more measurements agree.
        estimate = registry.as_estimate(
            observations[0], current_environment_id=report.environment_profile_id or ""
        )
        assert estimate.provenance == "historical_observation_prior"

    def test_repeated_bootstraps_accumulate_toward_calibration(self, tmp_path):
        """Three distinct training observations promote their bucket.

        Inference timing is identical, so its single content-addressed
        observation remains an unvalidated prior.
        """
        from core.runtime_control.calibration_policy import evaluate_promotions

        for train_ms in (17.6, 17.9, 18.1):
            deps = _deps(tmp_path)
            run_bootstrap(
                model_type="pseudo_bootstrap_model",
                model_config={"segmentation_size": 40_000},
                train_config={"batch_size": 8, "epochs": 1},
                loss_config={"loss_type": "ce"},
                deps=deps.model_copy(
                    update={
                        # bind the loop variable (B023): a default arg must
                        # precede **kwargs, so the binding goes first.
                        "build_executors": lambda _ms=train_ms, **kw: _executors(train_ms=_ms),
                    }
                ),
                caps={
                    "max_wall_seconds": 30.0,
                    "n_warmup_steps": 2,
                    "n_timed_train_steps": 5,
                    "n_timed_inference_batches": 3,
                },
            )
        registry = CalibrationRegistry(tmp_path / "runtime_calibration")
        promotions = evaluate_promotions(registry.iter_observations(), generation=0)
        levels = {p.level for p in promotions}
        assert levels == {"validated"}
        assert {
            registry.load_observation(observation_id).operation
            for promotion in promotions
            for observation_id in promotion.source_observation_ids
        } == {"training"}

    def test_a_busy_gpu_is_recorded_and_still_measured(self, tmp_path):
        """RE-GROUNDED 2026-08-06 (operator).

        This previously asserted that a busy GPU refused BEFORE measuring:
        `ready is False`, no observations recorded. That was the presence
        gate, and it made SIDERIUS unusable on a shared device — a stable
        sole-occupant holder produced `ready=False` on real hardware while
        `MeasurementValidity` was never even reached.

        External activity is now CONTEXT. The window is recorded, the run
        proceeds to actual measurement, and trustworthiness is decided by
        measurement INTEGRITY rather than by whether the device was busy.
        """
        report = _bootstrap(tmp_path, snapshot=BUSY)
        step = {s.name: s for s in report.steps}["contention window"]

        assert step.ok is True, "a busy GPU must not refuse before measuring"
        assert step.data["classification"] == "foreign_contended"  # still recorded
        assert step.data["decides_readiness"] is False
        # The run proceeded past the window into real measurement.
        assert len(report.steps) > 5
        steps = {s.name: s for s in report.steps}
        # A failed executor build also produces six steps; require the real
        # probe and observation path, not merely that step-count threshold.
        assert steps["bounded training probe"].ok
        assert steps["bounded inference probe"].ok
        assert len(report.observation_ids) == 2

    @pytest.mark.parametrize("run_twice", [True])
    def test_bootstrapping_twice_is_safe(self, tmp_path, run_twice):
        """Re-running must not corrupt or duplicate the registry: identical
        content is content-addressed to the same record."""
        first = _bootstrap(tmp_path)
        second = _bootstrap(tmp_path)
        assert first.ready and second.ready
        assert set(first.observation_ids) == set(second.observation_ids)
        registry = CalibrationRegistry(tmp_path / "runtime_calibration")
        assert len(registry.load_manifest().observation_ids) == 2
