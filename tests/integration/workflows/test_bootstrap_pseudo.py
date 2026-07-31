"""C10 pseudo integration — the bootstrap sequence over the REAL
subsystems, with only the device-touching seams faked.

Real here: the probe engine, the D3 contention classifier, the versioned
calibration registry (hash-verified), the observation builder, and the
production launch guard. Faked: the executors (no torch), the telemetry
sampler (no nvidia-smi) and the hardware collectors (no CUDA).

This is the closest thing to a real bootstrap that can run in CI, and it
is what makes the operator-gated GPU run a matter of swapping the device
seams rather than exercising untested wiring.
"""

from __future__ import annotations

import pytest

from core.runtime_control.bootstrap import BootstrapDependencies, run_bootstrap
from core.runtime_control.calibration_policy import sample_contention_window
from core.runtime_control.calibration_registry import CalibrationRegistry
from core.runtime_control.launch_guard import run_launch_self_test
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

    def _run_probe(*, model_identity, executors, caps, device_vram_gb, expected_peer_pids):
        # REAL probe engine.
        return run_bounded_probe(
            model_identity=model_identity,
            executors=executors,
            caps=ProbeCaps(**caps),
            device_vram_gb=device_vram_gb,
            expected_peer_pids=expected_peer_pids,
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
        dataset_check=lambda: (True, str(tmp_path)),
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
        """Three consistent bootstraps promote the buckets — the honest
        path from "measured once" to "calibrated"."""
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

    def test_a_contended_gpu_refuses_before_measuring(self, tmp_path):
        report = _bootstrap(tmp_path, snapshot=BUSY)
        assert report.ready is False
        assert report.observation_ids == ()
        failure = report.failures[0]
        assert failure.name == "contention window"
        assert failure.data["classification"] == "foreign_contended"
        # Nothing from a dirty baseline reached the registry.
        registry = CalibrationRegistry(tmp_path / "runtime_calibration")
        assert registry.load_manifest().observation_ids == []

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
