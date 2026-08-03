"""Production wiring for the REQUEST_PROBE lifecycle (C9d).

`probe_lifecycle.ProbeResolver` owns the RULES; this module owns the
CONNECTIONS: it builds the real bounded-probe runner (real plugin, real
dataset, real device) and the real registry sink, and exposes the single
entry point production calls.

`resolve_request_probe` is deliberately the same function the launch
self-test exercises. A guard that checked a different path than
production runs would have proved nothing — that is precisely how the
probe came to exist without ever being called.

Everything real is resolved LAZILY inside the functions: importing this
module must not require torch, CUDA or a dataset.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.runtime_control.decision_policy import RuntimeBudget, RuntimeMode
from core.runtime_control.estimator import shared_runtime_components
from core.runtime_control.measurement_capability import (
    ResolvedMeasurementCapability,
)
from core.runtime_control.probe import ProbeResult
from core.runtime_control.probe_lifecycle import (
    ProbeInfrastructureError,
    ProbeRequest,
    ProbeResolution,
    ProbeResolver,
)

#: Caps for a production pre-flight probe. Deliberately small: this runs
#: before every formal candidate, and its job is to measure a rate, not
#: to train.
PRODUCTION_PROBE_WALL_SECONDS = 90.0


def resolve_request_probe(
    *,
    request: ProbeRequest,
    budget: RuntimeBudget,
    mode: RuntimeMode,
    run_probe: Callable[[ProbeRequest], ProbeResult],
    persist: Callable[[ProbeResult, ProbeRequest], tuple[str, ...]] | None,
) -> ProbeResolution:
    """THE production entry point for resolving a REQUEST_PROBE decision.

    One resolver per call — the exactly-once guarantee is per candidate
    attempt, and a fresh resolver is what makes "this attempt has already
    probed" unambiguous.
    """
    _, policy = shared_runtime_components()
    resolver = ProbeResolver(policy=policy, run_probe=run_probe, persist=persist)
    return resolver.resolve(request, budget=budget, mode=mode)


def probe_runner_availability(
    capability: ResolvedMeasurementCapability | None = None,
) -> tuple[bool, str]:
    """Whether this environment can build a REAL bounded-probe runner.

    Returns ``(available, detail)``; the detail names the missing piece so
    a launch refusal explains itself. Never raises: the caller decides
    whether unavailability is fatal (a real formal launch) or expected (a
    CPU/pseudo run).

    V20 PR C1 / C-C3b. This used to import `TIDMAD_DATA_DIR` and refuse
    unless that directory was readable, which made the whole
    measured-evidence path silently unavailable on any other task -- a task
    assumption expressed by omission inside generic infrastructure.

    The capability is now resolved by the caller, which knows its task:
    `execute_tools.data_paths.resolve_tidmad_measurement_capability` is
    TIDMAD's. Passing None means the caller did not resolve one, and that
    is reported as an unavailability with a reason rather than defaulted to
    a task's dataset -- generic code has no basis for choosing which task's
    data to look for.
    """
    if capability is None:
        return False, (
            "no measurement capability was resolved by the caller; generic "
            "runtime-control cannot choose a task's dataset for it"
        )
    return capability.probe_available, capability.detail


def build_production_probe_runner(
    *,
    model_type: str,
    model_config: dict[str, Any],
    train_config: dict[str, Any],
    loss_config: dict[str, Any],
    data_dir: str | None = None,
    device: str = "cuda",
) -> Callable[[ProbeRequest], ProbeResult]:
    """Build the REAL probe runner for one candidate.

    Any failure to assemble it — no CUDA, unknown device VRAM, missing
    plugin, unreadable dataset — is raised as `ProbeInfrastructureError`,
    which the lifecycle turns into ABORT. That is the correct outcome: we
    could not obtain evidence, which says nothing about the candidate.
    """

    def _run(request: ProbeRequest) -> ProbeResult:
        try:
            from core.runtime_control.probe import ProbeCaps, run_bounded_probe
            from core.runtime_control.probe_production import (
                probe_device_vram_gb,
                production_probe_executors,
            )

            executors = production_probe_executors(
                model_type=model_type,
                model_config=model_config,
                train_config=train_config,
                loss_config=loss_config,
                data_dir=data_dir,
                device=device,
            )
            vram_gb = probe_device_vram_gb()
        except Exception as exc:
            raise ProbeInfrastructureError(
                f"could not assemble the bounded probe for {model_type!r}: {exc!r}"
            ) from exc

        return run_bounded_probe(
            model_identity=request.model_identity,
            executors=executors,
            caps=ProbeCaps(max_wall_seconds=PRODUCTION_PROBE_WALL_SECONDS),
            device_vram_gb=vram_gb,
        )

    return _run


def build_registry_persist(
    *,
    workload: dict[str, Any],
    software_stack: dict[str, Any],
    source_run: dict[str, Any],
    registry_root: str | None = None,
) -> Callable[[ProbeResult, ProbeRequest], tuple[str, ...]]:
    """Build the REAL observation sink (C5/C7 registry).

    A persistence failure propagates: the lifecycle converts it to ABORT
    rather than deciding from evidence it could not record.
    """

    def _persist(result: ProbeResult, request: ProbeRequest) -> tuple[str, ...]:
        from pathlib import Path

        from core.runtime_control.calibration_registry import CalibrationRegistry
        from core.runtime_control.probe import probe_observations
        from core.runtime_control.probe_production import (
            collect_execution_environment_profile,
            collect_hardware_compatibility_profile,
        )

        registry = CalibrationRegistry(Path(registry_root) if registry_root else None)
        hardware_id = registry.put_hardware_profile(collect_hardware_compatibility_profile())
        environment_id = registry.put_environment_profile(
            collect_execution_environment_profile(
                installation_id=registry.installation_id(),
                hardware_compatibility_id=hardware_id,
                concurrency_regime=result.concurrency_identity,
            )
        )
        records = probe_observations(
            result,
            hardware_compatibility_id=hardware_id,
            execution_environment_id=environment_id,
            workload=workload,
            software_stack=software_stack,
            source_run=source_run,
            model_family=request.model_family,
        )
        return tuple(registry.record_observation(record) for record in records)

    return _persist
