"""Environment bootstrap and readiness self-test (C10).

Answers one question for a NEW machine: can this environment produce
measured runtime evidence, and is it therefore safe to launch on?

The eleven §12-directive steps, in order:

```text
 1 inspect the environment (accelerator, driver, stack)
 2 build the hardware compatibility profile
 3 build the execution environment profile
 4 validate the dataset
 5 sample the pre-probe contention window (recorded as CONTEXT only)
 6 build the probe executors for a real registered model
 7 bounded TRAINING probe
 8 bounded INFERENCE probe (same probe, separate measurement)
 9 persist observations through the versioned registry ONLY
10 re-read and verify every record (hash-checked)
11 run the SAME launch self-test production uses -> READY / NOT READY
```

Design constraints this module keeps:

* every step is individually mockable, so the whole sequence is unit
  tested without a GPU;
* nothing is written except through `CalibrationRegistry` — no hand-
  edited JSON, no config file the operator must touch;
* a refusal is actionable: each NOT READY carries the step that failed
  and what to do about it;
* contention at bootstrap time is RECORDED and flagged, never silently
  averaged into the baseline.

C10 proves an environment can bootstrap. It deliberately does NOT judge
estimator accuracy across families and scales — that is C12.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.runtime_control.gpu_accounting import device_identity_from_hardware
from core.runtime_control.measurement_validity import summarise_external_activity

#: Bounded by construction: bootstrap must never look like a training run.
DEFAULT_BOOTSTRAP_CAPS = {
    "max_wall_seconds": 90.0,
    "n_warmup_steps": 3,
    "n_timed_train_steps": 7,
    "n_timed_inference_batches": 5,
}


class BootstrapStep(BaseModel):
    """One step's outcome. ``ok=False`` always carries a remedy."""

    model_config = ConfigDict(frozen=True)

    name: str
    ok: bool
    detail: str = ""
    remedy: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class BootstrapReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    ready: bool
    steps: tuple[BootstrapStep, ...]
    registry_root: str | None = None
    observation_ids: tuple[str, ...] = ()
    hardware_profile_id: str | None = None
    environment_profile_id: str | None = None
    elapsed_seconds: float = Field(default=0.0, ge=0.0)

    @property
    def failures(self) -> tuple[BootstrapStep, ...]:
        return tuple(step for step in self.steps if not step.ok)

    def render(self) -> str:
        """Operator-facing verdict."""
        lines = ["", "=" * 68]
        lines.append("  SIDERIUS runtime bootstrap — " + ("READY" if self.ready else "NOT READY"))
        lines.append("=" * 68)
        for step in self.steps:
            mark = "ok  " if step.ok else "FAIL"
            lines.append(f"  [{mark}] {step.name}{(': ' + step.detail) if step.detail else ''}")
            if not step.ok and step.remedy:
                lines.append(f"         -> {step.remedy}")
        if self.registry_root:
            lines.append(f"  registry     : {self.registry_root}")
        if self.observation_ids:
            lines.append(f"  observations : {len(self.observation_ids)} recorded")
        # C-C7: "N recorded" is the number that misled for weeks -- the live
        # v1 registry showed 20 and was never once authoritative. The state
        # line says whether any of it can actually decide anything, and why
        # not when it cannot. Read-only and never raises; a reporting failure
        # must not change what bootstrap concluded.
        if self.registry_root:
            from core.runtime_control.calibration_state import collect_calibration_state

            # `root=` and not a constructed registry: CalibrationRegistry
            # mkdirs in __init__, so constructing it here would put the one
            # raising step OUTSIDE the collector's guard and hand render() an
            # exception from a read-only or vanished root.
            lines.append("  " + collect_calibration_state(root=self.registry_root).summary_line())
        lines.append(f"  elapsed      : {self.elapsed_seconds:.1f}s")
        if not self.ready:
            lines.append("")
            lines.append("  This environment cannot yet produce measured runtime evidence.")
            lines.append("  Fix the FAIL lines above and re-run; nothing was left half-written.")
        lines.append("=" * 68)
        return "\n".join(lines)


class BootstrapDependencies(BaseModel):
    """Injected seams — the whole sequence is unit tested through these."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    collect_hardware: Callable[[], Any]
    collect_environment: Callable[..., Any]
    build_registry: Callable[[], Any]
    dataset_check: Callable[[], tuple[bool, str]]
    sample_contention: Callable[..., Any]
    build_executors: Callable[..., Any]
    run_probe: Callable[..., Any]
    build_observations: Callable[..., list]
    launch_self_test: Callable[..., Any]
    device_vram_gb: Callable[[], float]


def run_bootstrap(
    *,
    model_type: str,
    model_config: dict[str, Any],
    train_config: dict[str, Any],
    loss_config: dict[str, Any],
    deps: BootstrapDependencies,
    caps: dict[str, Any] | None = None,
    data_dir: str | None = None,
    expected_peer_pids: tuple[int, ...] = (),
    clock: Callable[[], float] = time.monotonic,
) -> BootstrapReport:
    """Run the eleven bootstrap steps and return a readiness verdict.

    Never raises for an environment problem: an unusable environment is a
    RESULT (NOT READY with a remedy), not an exception. Only a programming
    error propagates.
    """
    started = clock()
    steps: list[BootstrapStep] = []
    registry_root: str | None = None
    hardware_id: str | None = None
    environment_id: str | None = None
    observation_ids: tuple[str, ...] = ()

    def _finish(ready: bool) -> BootstrapReport:
        return BootstrapReport(
            ready=ready,
            steps=tuple(steps),
            registry_root=registry_root,
            observation_ids=observation_ids,
            hardware_profile_id=hardware_id,
            environment_profile_id=environment_id,
            elapsed_seconds=round(clock() - started, 3),
        )

    # 1-2 — environment inspection + hardware compatibility profile
    try:
        hardware = deps.collect_hardware()
    except Exception as exc:
        steps.append(
            BootstrapStep(
                name="inspect accelerator",
                ok=False,
                detail=f"{type(exc).__name__}: {exc}",
                remedy=(
                    "Install a CUDA-capable torch build and make a device visible "
                    "(check CUDA_VISIBLE_DEVICES and `nvidia-smi`)."
                ),
            )
        )
        return _finish(False)
    steps.append(
        BootstrapStep(
            name="inspect accelerator",
            ok=True,
            detail=f"{hardware.accelerator_model} x{hardware.gpu_count}, "
            f"{hardware.vram_gb:.1f} GB, torch {hardware.torch_version}",
            data={"accelerator_model": hardware.accelerator_model},
        )
    )

    registry = deps.build_registry()
    registry_root = str(registry.root)
    hardware_id = registry.put_hardware_profile(hardware)
    steps.append(
        BootstrapStep(name="hardware compatibility profile", ok=True, detail=hardware_id[:19] + "…")
    )

    # 3 — execution environment profile
    environment_id = registry.put_environment_profile(
        deps.collect_environment(
            installation_id=registry.installation_id(),
            hardware_compatibility_id=hardware_id,
            concurrency_regime="single_candidate_idle",
        )
    )
    steps.append(
        BootstrapStep(
            name="execution environment profile", ok=True, detail=environment_id[:19] + "…"
        )
    )

    # 4 — dataset
    data_ok, data_detail = deps.dataset_check()
    steps.append(
        BootstrapStep(
            name="dataset",
            ok=data_ok,
            detail=data_detail,
            remedy=""
            if data_ok
            else (
                "Point the run at a readable TIDMAD directory "
                "(execute_tools/data_paths.py resolves it)."
            ),
        )
    )
    if not data_ok:
        return _finish(False)

    # 5 — pre-probe contention window (RECORDED as context; it does not
    #     decide readiness — see the note below)
    try:
        vram_gb = deps.device_vram_gb()
        window = deps.sample_contention(
            device_vram_gb=vram_gb, expected_peer_pids=expected_peer_pids
        )
    except Exception as exc:
        steps.append(
            BootstrapStep(
                name="contention window",
                ok=False,
                detail=f"{type(exc).__name__}: {exc}",
                remedy="GPU telemetry is unavailable; check `nvidia-smi` on this host.",
            )
        )
        return _finish(False)
    # V20 — external activity is CONTEXT, never readiness (operator,
    # 2026-08-06). This step used to refuse whenever the window was anything
    # other than idle-or-registered-peer:
    #
    #     contended = classification not in ("single_candidate_idle",
    #                                        "pairwise_expected_peer")
    #     if contended: return _finish(False)
    #
    # Three defects in one gate, all measured on real hardware (a stable
    # sole-occupant 5,104 MiB holder produced ready=False):
    #
    #   1. PRESENCE decided readiness — any unregistered PID refused,
    #      however stable, and `MeasurementValidity` was never reached;
    #   2. REGISTRATION was privileged — `pairwise_expected_peer` passed
    #      where an identical unregistered process was refused, making
    #      registration a correctness requirement;
    #   3. the remedy told operators to stop other workloads, i.e. that
    #      SIDERIUS requires an empty GPU.
    #
    # The window is still SAMPLED and RECORDED — it is useful provenance —
    # but it no longer decides. Whether the measurement can be trusted is
    # decided downstream by measurement integrity, and whether the candidate
    # may run is decided separately by admission.
    # Summarised from the accounting snapshots the window actually collected.
    # `occupancy` is present only when the caller named a device (FU-C-1); on
    # a CPU host or an unnamed device there are no snapshots and the summary
    # honestly reports `unknown` rather than inventing `absent`.
    _accounting = window.occupancy.snapshots if window.occupancy is not None else ()
    external = summarise_external_activity(_accounting, registered_pids=expected_peer_pids)
    steps.append(
        BootstrapStep(
            name="contention window",
            ok=True,
            detail=(
                f"{window.classification} ({len(window.samples)} samples) — "
                f"recorded as context; readiness is decided by measurement "
                f"integrity, not by external presence"
            ),
            data={
                "classification": window.classification,
                "reasons": list(window.reasons),
                "external_activity": external.model_dump(mode="json"),
                "decides_readiness": False,
            },
        )
    )

    # 6-8 — bounded probe (training and inference measured separately)
    try:
        executors = deps.build_executors(
            model_type=model_type,
            model_config=model_config,
            train_config=train_config,
            loss_config=loss_config,
            data_dir=data_dir,
        )
    except Exception as exc:
        steps.append(
            BootstrapStep(
                name="probe executors",
                ok=False,
                detail=f"{type(exc).__name__}: {exc}",
                remedy=f"Model {model_type!r} could not be prepared; check the registry entry.",
            )
        )
        return _finish(False)
    steps.append(BootstrapStep(name="probe executors", ok=True, detail=model_type))

    # FU-C-1. The probe path builds an occupancy window — and therefore a
    # `MeasurementValidity` verdict — only when the device is NAMED. Without
    # this the bootstrap CLI silently produced `measurement_validity=None`,
    # so V20 PR C's rule was unreachable from a real, production-supported
    # probe entry point: a stable neighbour would still deny the measurement
    # blocking authority.
    #
    # Resolved HERE, from the hardware record this flow already collected,
    # through the ONE permitted adapter. `None` (CPU host, or a record with
    # no UUID) stays None and fails closed — it is never repaired by
    # assuming device 0, which would conflate two cards of the same model.
    device_identity = device_identity_from_hardware(hardware)

    result = deps.run_probe(
        model_identity=model_type,
        executors=executors,
        caps=caps or DEFAULT_BOOTSTRAP_CAPS,
        device_vram_gb=vram_gb,
        expected_peer_pids=expected_peer_pids,
        device_identity=device_identity,
    )
    if result.status != "ok":
        steps.append(
            BootstrapStep(
                name="bounded probe",
                ok=False,
                detail=f"status={result.status}: {result.error}",
                remedy=(
                    "The probe could not measure this model here. An OOM or wall-cap "
                    "means the bootstrap model is too large for this device — pick a "
                    "smaller --model; a load failure means the model could not be built."
                ),
            )
        )
        return _finish(False)
    steps.append(
        BootstrapStep(
            name="bounded training probe",
            ok=result.train_ms_per_step is not None,
            detail=f"{result.train_ms_per_step:.2f} ms/step"
            if result.train_ms_per_step
            else "no training measurement",
            remedy="" if result.train_ms_per_step else "The probe produced no timed steps.",
            data={"train_ms_per_step": result.train_ms_per_step},
        )
    )
    steps.append(
        BootstrapStep(
            name="bounded inference probe",
            ok=result.inference_ms_per_batch is not None,
            detail=f"{result.inference_ms_per_batch:.2f} ms/batch"
            if result.inference_ms_per_batch
            else "no inference measurement",
            remedy="" if result.inference_ms_per_batch else "The probe produced no timed batches.",
            data={"inference_ms_per_batch": result.inference_ms_per_batch},
        )
    )
    steps.append(
        BootstrapStep(
            name="setup + VRAM",
            ok=True,
            detail=f"setup {result.setup_seconds:.2f}s, peak "
            + (f"{result.peak_vram_gb:.2f} GB" if result.peak_vram_gb else "n/a (CPU)"),
            data={
                "setup_seconds": result.setup_seconds,
                "peak_vram_gb": result.peak_vram_gb,
                "realized_parameter_count": (
                    result.realized.parameter_count if result.realized else None
                ),
            },
        )
    )
    if result.train_ms_per_step is None or result.inference_ms_per_batch is None:
        return _finish(False)

    # 9 — persist THROUGH THE REGISTRY ONLY
    try:
        records = deps.build_observations(
            result,
            hardware_compatibility_id=hardware_id,
            execution_environment_id=environment_id,
            # The workload the probe ACTUALLY ran. Derived from the caller's
            # configs, never from the caps: D4 buckets and C7 applicability
            # ranges are keyed on these, so a wrong value here mislabels the
            # evidence for every future comparison.
            workload={
                "batch_size": int(train_config.get("batch_size", 1)),
                "segment_length": int(model_config.get("segmentation_size", 0)),
                "n_timed_train_steps": result.caps.n_timed_train_steps,
                "n_timed_inference_batches": result.caps.n_timed_inference_batches,
                "probe": "bootstrap",
            },
        )
        observation_ids = tuple(registry.record_observation(record) for record in records)
    except Exception as exc:
        steps.append(
            BootstrapStep(
                name="record observations",
                ok=False,
                detail=f"{type(exc).__name__}: {exc}",
                remedy=f"The calibration registry at {registry_root} is not writable.",
            )
        )
        return _finish(False)
    steps.append(
        BootstrapStep(
            name="record observations",
            ok=True,
            detail=f"{len(observation_ids)} records (training + inference)",
        )
    )

    # 10 — read back and verify every record's content hash
    try:
        for observation_id in observation_ids:
            registry.load_observation(observation_id)
        manifest = registry.load_manifest()
    except Exception as exc:
        steps.append(
            BootstrapStep(
                name="registry self-validation",
                ok=False,
                detail=f"{type(exc).__name__}: {exc}",
                remedy="Records did not survive a hash-verified read-back; inspect the registry.",
            )
        )
        return _finish(False)
    steps.append(
        BootstrapStep(
            name="registry self-validation",
            ok=True,
            detail=f"generation {manifest.generation}, all records hash-verified",
        )
    )

    # 11 — the SAME self-test the launch guard runs
    try:
        guard = deps.launch_self_test(require_probe_runner=True)
    except Exception as exc:
        steps.append(
            BootstrapStep(
                name="launch self-test",
                ok=False,
                detail=f"{type(exc).__name__}: {exc}",
                remedy="The runtime decision subsystem is not launch-safe on this build.",
            )
        )
        return _finish(False)
    steps.append(
        BootstrapStep(
            name="launch self-test",
            ok=True,
            detail=f"{len(guard.checks)} checks | policy={guard.policy_identity}",
            data={"policy_identity": guard.policy_identity},
        )
    )
    return _finish(True)


def production_dependencies() -> BootstrapDependencies:
    """Wire the REAL collectors, probe and registry (lazy imports)."""
    from core.runtime_control.calibration_policy import sample_contention_window
    from core.runtime_control.calibration_registry import CalibrationRegistry
    from core.runtime_control.launch_guard import run_launch_self_test
    from core.runtime_control.probe import ProbeCaps, probe_observations, run_bounded_probe
    from core.runtime_control.probe_production import (
        collect_execution_environment_profile,
        collect_hardware_compatibility_profile,
        probe_device_vram_gb,
        production_probe_executors,
    )

    def _dataset_check() -> tuple[bool, str]:
        import os

        from execute_tools.data_paths import TIDMAD_DATA_DIR

        if TIDMAD_DATA_DIR and os.path.isdir(TIDMAD_DATA_DIR):
            return True, str(TIDMAD_DATA_DIR)
        return False, f"not found at {TIDMAD_DATA_DIR!r}"

    def _run_probe(
        *,
        model_identity,
        executors,
        caps,
        device_vram_gb,
        expected_peer_pids,
        device_identity=None,
    ):
        return run_bounded_probe(
            model_identity=model_identity,
            executors=executors,
            caps=ProbeCaps(**caps) if isinstance(caps, dict) else caps,
            device_vram_gb=device_vram_gb,
            expected_peer_pids=expected_peer_pids,
            device_identity=device_identity,
        )

    def _build_observations(
        result, *, hardware_compatibility_id, execution_environment_id, workload
    ):
        from core.runtime_control.provenance import capture_software_stack

        return probe_observations(
            result,
            hardware_compatibility_id=hardware_compatibility_id,
            execution_environment_id=execution_environment_id,
            workload=workload,
            # Shared with the tuner's probe path so both describe one stack
            # under one identity. Byte-identical to the dict literal this
            # replaced, so the records already written keep their bucket.
            software_stack=capture_software_stack(),
            source_run={"run_name": "bootstrap", "tool": "scripts/runtime_bootstrap.py"},
            timestamp_metadata=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        )

    return BootstrapDependencies(
        collect_hardware=collect_hardware_compatibility_profile,
        collect_environment=collect_execution_environment_profile,
        build_registry=CalibrationRegistry,
        dataset_check=_dataset_check,
        sample_contention=sample_contention_window,
        build_executors=production_probe_executors,
        run_probe=_run_probe,
        build_observations=_build_observations,
        launch_self_test=run_launch_self_test,
        device_vram_gb=probe_device_vram_gb,
    )
