"""C10 — environment bootstrap and readiness self-test.

The whole eleven-step sequence runs here without a GPU, a dataset or an
LLM: every heavy seam is injected. What is tested is the SEQUENCE and its
refusals — a bootstrap that says READY when the environment cannot
measure would be worse than no bootstrap at all.

The acceptance criterion from the design doc is exercised directly: a
fresh environment (empty temp registry) reaches a correct verdict with no
hand-edited source or JSON.
"""

from __future__ import annotations

import pytest

from core.runtime_control.bootstrap import (
    BootstrapDependencies,
    run_bootstrap,
)
from core.runtime_control.calibration_registry import CalibrationRegistry
from core.runtime_control.probe import (
    ContentionSnapshot,
    ProbeCaps,
    ProbeResult,
    RealizedModelProperties,
)
from core.runtime_control.registry_schemas import (
    ExecutionEnvironmentProfile,
    HardwareCompatibilityProfile,
)

HARDWARE = HardwareCompatibilityProfile(
    accelerator_vendor="NVIDIA",
    accelerator_model="bootstrap-test-gpu",
    gpu_count=1,
    vram_gb=32.0,
    torch_version="2.7.0",
)


class _Window:
    def __init__(self, classification="single_candidate_idle"):
        self.classification = classification
        self.samples = (ContentionSnapshot(telemetry_available=True),) * 5
        self.reasons = ("test",)
        # Part of the ContentionWindow contract (FU-C-1). `None` is the
        # legitimate value when no device was named — a CPU host or an
        # unnamed device — and the bootstrap then reports external activity
        # as `unknown` rather than inventing `absent`.
        self.occupancy = None

    def raw_telemetry(self):
        return {"samples": [], "classification": self.classification}


class _Guard:
    checks = ("a", "b", "c")
    policy_identity = "runtime_decision_policy@1.0.0+test"


def _probe_result(**over) -> ProbeResult:
    base = dict(
        status="ok",
        model_identity="bootstrap_model",
        realized=RealizedModelProperties(
            parameter_count=45_408,
            trainable_parameter_count=45_408,
            parameter_memory_gb=0.001,
            dtype="float32",
        ),
        setup_seconds=1.5,
        train_ms_per_step=17.6,
        train_ms_spread=(17.0, 18.2),
        inference_ms_per_batch=8.1,
        inference_ms_spread=(7.9, 8.4),
        peak_vram_gb=1.2,
        concurrency_identity="single_candidate_idle",
        contention=ContentionSnapshot(telemetry_available=True, foreign_compute_processes=0),
        caps=ProbeCaps(),
        wall_seconds=20.0,
    )
    base.update(over)
    return ProbeResult(**base)


def _deps(tmp_path, **over) -> BootstrapDependencies:
    from core.runtime_control.probe import probe_observations

    def _observations(result, *, hardware_compatibility_id, execution_environment_id, workload):
        return probe_observations(
            result,
            hardware_compatibility_id=hardware_compatibility_id,
            execution_environment_id=execution_environment_id,
            workload=workload,
            software_stack={"torch": "2.7.0"},
            source_run={"run_name": "bootstrap_test"},
        )

    base = dict(
        collect_hardware=lambda: HARDWARE,
        collect_environment=lambda **kw: ExecutionEnvironmentProfile(**kw),
        build_registry=lambda: CalibrationRegistry(tmp_path / "runtime_calibration"),
        dataset_check=lambda: (True, str(tmp_path / "data")),
        sample_contention=lambda **kw: _Window(),
        build_executors=lambda **kw: object(),
        run_probe=lambda **kw: _probe_result(),
        build_observations=_observations,
        launch_self_test=lambda **kw: _Guard(),
        device_vram_gb=lambda: 32.0,
    )
    base.update(over)
    return BootstrapDependencies(**base)


def _run(tmp_path, **over):
    return run_bootstrap(
        model_type="bootstrap_model",
        model_config={"segmentation_size": 40_000},
        train_config={"batch_size": 8, "epochs": 1},
        loss_config={"loss_type": "ce"},
        deps=_deps(tmp_path, **over),
    )


class TestHappyPath:
    def test_a_fresh_environment_reaches_ready(self, tmp_path):
        """The design-doc acceptance criterion: empty registry, no hand
        edits, correct verdict."""
        report = _run(tmp_path)
        assert report.ready is True
        assert report.failures == ()
        assert len(report.observation_ids) == 2  # training + inference
        assert report.hardware_profile_id and report.environment_profile_id

    def test_every_step_runs_in_order(self, tmp_path):
        names = [step.name for step in _run(tmp_path).steps]
        assert names == [
            "inspect accelerator",
            "hardware compatibility profile",
            "execution environment profile",
            "dataset",
            "contention window",
            "probe executors",
            "bounded training probe",
            "bounded inference probe",
            "setup + VRAM",
            "record observations",
            "registry self-validation",
            "launch self-test",
        ]

    def test_it_records_the_four_measured_quantities(self, tmp_path):
        steps = {step.name: step for step in _run(tmp_path).steps}
        assert steps["bounded training probe"].data["train_ms_per_step"] == 17.6
        assert steps["bounded inference probe"].data["inference_ms_per_batch"] == 8.1
        assert steps["setup + VRAM"].data["setup_seconds"] == 1.5
        assert steps["setup + VRAM"].data["peak_vram_gb"] == 1.2
        assert steps["contention window"].data["classification"] == "single_candidate_idle"

    def test_writes_go_only_through_the_registry(self, tmp_path):
        """Nothing outside the registry directory is created — no config
        file the operator would have to edit by hand."""
        report = _run(tmp_path)
        created = {p.name for p in tmp_path.iterdir()}
        assert created == {"runtime_calibration"}
        registry = CalibrationRegistry(tmp_path / "runtime_calibration")
        assert sorted(registry.load_manifest().observation_ids) == sorted(report.observation_ids)

    def test_records_survive_a_hash_verified_read_back(self, tmp_path):
        report = _run(tmp_path)
        registry = CalibrationRegistry(tmp_path / "runtime_calibration")
        for observation_id in report.observation_ids:
            observation = registry.load_observation(observation_id)
            assert observation.provenance == "bounded_live_probe"
            assert observation.validation_status == "unvalidated"

    def test_the_verdict_renders_for_an_operator(self, tmp_path):
        text = _run(tmp_path).render()
        assert "READY" in text and "NOT READY" not in text
        assert "bounded training probe" in text
        assert "registry" in text


class TestRefusals:
    """Every refusal must be actionable — a verdict without a remedy is
    just a failure message."""

    def _first_failure(self, report):
        assert report.ready is False
        assert report.failures, "a NOT READY report must name the failing step"
        return report.failures[0]

    def test_no_accelerator(self, tmp_path):
        def _boom():
            raise RuntimeError("hardware profile collection requires CUDA")

        failure = self._first_failure(_run(tmp_path, collect_hardware=_boom))
        assert failure.name == "inspect accelerator"
        assert "CUDA" in failure.remedy

    def test_no_dataset(self, tmp_path):
        failure = self._first_failure(
            _run(tmp_path, dataset_check=lambda: (False, "not found at '/data/tidmad'"))
        )
        assert failure.name == "dataset"
        assert "TIDMAD" in failure.remedy

    def test_external_activity_is_recorded_but_does_NOT_refuse(self, tmp_path):
        """RE-GROUNDED 2026-08-06 (operator).

        This previously asserted that a `foreign_contended` window REFUSED
        readiness with "another process is using this GPU… stop the other
        workload". That gate was wrong in three ways, all measured on real
        hardware: presence decided readiness; a REGISTERED peer was privileged
        over an identical unregistered process; and the remedy told operators
        SIDERIUS needs an empty GPU.

        External activity is now CONTEXT. The window is still sampled and
        still recorded — it is useful provenance — but it no longer decides.
        Whether the measurement can be trusted is decided downstream by
        measurement INTEGRITY, and whether the candidate may run is decided
        separately by admission.
        """
        report = _run(tmp_path, sample_contention=lambda **kw: _Window("foreign_contended"))
        step = {s.name: s for s in report.steps}["contention window"]

        assert step.ok is True, "external presence must not refuse readiness"
        assert step.remedy == "", "no remedy — nothing was wrong"
        assert step.data["classification"] == "foreign_contended"  # still recorded
        assert step.data["decides_readiness"] is False
        assert "external_activity" in step.data

    def test_telemetry_failure(self, tmp_path):
        def _boom(**kw):
            raise RuntimeError("nvidia-smi unavailable")

        failure = self._first_failure(_run(tmp_path, sample_contention=_boom))
        assert failure.name == "contention window"
        assert "nvidia-smi" in failure.remedy

    def test_unbuildable_model(self, tmp_path):
        def _boom(**kw):
            raise KeyError("unknown_model")

        failure = self._first_failure(_run(tmp_path, build_executors=_boom))
        assert failure.name == "probe executors"

    @pytest.mark.parametrize("status", ["oom", "wall_cap", "load_failure"])
    def test_a_failed_probe_reports_the_measured_outcome(self, tmp_path, status):
        report = _run(
            tmp_path,
            run_probe=lambda **kw: _probe_result(
                status=status,
                error="measured failure",
                train_ms_per_step=None,
                train_ms_spread=None,
                inference_ms_per_batch=None,
                inference_ms_spread=None,
            ),
        )
        failure = self._first_failure(report)
        assert failure.name == "bounded probe"
        assert status in failure.detail
        assert report.observation_ids == ()

    def test_an_unwritable_registry(self, tmp_path):
        def _boom(result, **kw):
            raise OSError("read-only file system")

        failure = self._first_failure(_run(tmp_path, build_observations=_boom))
        assert failure.name == "record observations"
        assert "not writable" in failure.remedy

    def test_a_failing_launch_self_test_blocks_readiness(self, tmp_path):
        def _boom(**kw):
            raise RuntimeError("static evidence produced REJECT")

        report = _run(tmp_path, launch_self_test=_boom)
        failure = self._first_failure(report)
        assert failure.name == "launch self-test"
        # The observations were still recorded — the measurement happened.
        assert len(report.observation_ids) == 2

    def test_an_environment_problem_is_a_verdict_not_an_exception(self, tmp_path):
        """A bootstrap tool that crashes teaches the operator nothing."""
        for override in (
            {"collect_hardware": lambda: (_ for _ in ()).throw(RuntimeError("no gpu"))},
            {"dataset_check": lambda: (False, "missing")},
            {"device_vram_gb": lambda: (_ for _ in ()).throw(RuntimeError("no device"))},
        ):
            report = _run(tmp_path, **override)
            assert report.ready is False
            assert report.render()


class TestCliSurface:
    def test_the_parser_exposes_the_documented_flags(self):
        import importlib.util
        from pathlib import Path

        path = Path(__file__).resolve().parents[3] / "scripts" / "runtime_bootstrap.py"
        spec = importlib.util.spec_from_file_location("_c10_cli", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        parser = module.build_parser()
        flags = {action.dest for action in parser._actions}
        assert {
            "model",
            "segmentation_size",
            "batch_size",
            "data_dir",
            "registry_dir",
            "max_wall_seconds",
            "warmup_steps",
            "timed_train_steps",
            "timed_inference_batches",
            "expected_peer_pid",
            "dry_run",
            "as_json",
        } <= flags

    def test_defaults_are_bounded(self):
        import importlib.util
        from pathlib import Path

        path = Path(__file__).resolve().parents[3] / "scripts" / "runtime_bootstrap.py"
        spec = importlib.util.spec_from_file_location("_c10_cli2", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        args = module.build_parser().parse_args([])
        assert args.max_wall_seconds == 90.0
        assert args.timed_train_steps == 7
        assert args.timed_inference_batches == 5
        assert args.dry_run is False


class TestWorkloadMetadata:
    """Regression: the first real GPU bootstrap recorded
    `batch_size = n_timed_train_steps` (7 instead of 8) and no
    segment_length at all. D4 buckets and C7 applicability ranges are
    keyed on this metadata, so a wrong value mislabels the evidence for
    every future comparison — the run still said READY, which is exactly
    why this needs a test rather than an eye.
    """

    def test_the_recorded_workload_is_the_one_that_ran(self, tmp_path):
        captured: dict = {}

        def _capture(result, *, hardware_compatibility_id, execution_environment_id, workload):
            captured.update(workload)
            from core.runtime_control.probe import probe_observations

            return probe_observations(
                result,
                hardware_compatibility_id=hardware_compatibility_id,
                execution_environment_id=execution_environment_id,
                workload=workload,
                software_stack={"torch": "2.7.0"},
                source_run={"run_name": "t"},
            )

        report = run_bootstrap(
            model_type="bootstrap_model",
            model_config={"segmentation_size": 40_000},
            train_config={"batch_size": 8, "epochs": 1},
            loss_config={"loss_type": "ce"},
            deps=_deps(tmp_path, build_observations=_capture),
        )
        assert report.ready is True
        assert captured["batch_size"] == 8  # NOT the timed-step count
        assert captured["segment_length"] == 40_000
        # the cap counts are still recorded, under their own names
        assert captured["n_timed_train_steps"] == 7
        assert captured["n_timed_inference_batches"] == 5

    def test_the_persisted_observation_carries_it(self, tmp_path):
        report = _run(tmp_path)
        registry = CalibrationRegistry(tmp_path / "runtime_calibration")
        for observation_id in report.observation_ids:
            workload = registry.load_observation(observation_id).workload
            assert workload["batch_size"] == 8
            assert workload["segment_length"] == 40_000
