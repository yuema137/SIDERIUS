"""Bounded post-implementation live probe (C6).

The FIRST authoritative runtime measurement of an implemented candidate
(design contract §8.2/§13.1): setup timing, a few real training steps, a
few real inference batches, peak VRAM, and a contention snapshot — all
under explicit caps. Produces `bounded_live_probe` evidence (tier 2) and
immutable `CalibrationObservation` records for the C5 registry (write
eligibility governed by C7 policy).

Architecture (C6 implementation record): the ENGINE is pure
orchestration over three injected executor callables (build/setup,
timed train step, timed inference batch) plus an injected telemetry
function — unit tests drive it deterministically with fakes (repo
standard: heavy subsystems mocked in unit tests); the PRODUCTION
executors (`production_probe_executors`) wire real torch + the plugin
registry + the canonical dataset path lazily and are exercised only in
the operator-gated GPU smoke / C12 campaign.

F-1a: the dataset path resolves through the single source of truth
(`execute_tools.data_paths.TIDMAD_DATA_DIR`) when no explicit
``data_dir`` is supplied — never a second convention.
F-1b: the production builder loads the ACTUAL implemented plugin from
the live registry and recomputes realized properties (§16.7) — the
LLM-authored estimate is never trusted past this point.

Concurrency identity (C6, D3-neutral): classification is by the
PRESENCE of other GPU compute processes (count-based) plus the
launcher-declared peer expectation — no utilization thresholds are
introduced (D3 remains open for C7):

* no foreign process                   → single_candidate_idle
* foreign processes, peer expected     → pairwise_expected_peer
* foreign processes, no peer expected  → foreign_contended
* telemetry unavailable                → unknown_contention
"""

from __future__ import annotations

import time
from collections.abc import Callable
from statistics import median
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.runtime_control.estimate_types import (
    ConcurrencyIdentity,
    RuntimeEstimate,
    make_estimate,
)
from core.runtime_control.registry_schemas import CalibrationObservation

PROBE_PRODUCER_SEMVER = "1.0.0"

ProbeStatus = Literal["ok", "oom", "wall_cap", "load_failure"]


class ProbeCaps(BaseModel):
    """Explicit probe bounds (§8.2). Defaults mirror the proven warmup
    posture (3 warmup + 7 timed steps)."""

    model_config = ConfigDict(frozen=True)

    max_wall_seconds: float = Field(default=90.0, gt=0.0)
    n_warmup_steps: int = Field(default=3, ge=0)
    n_timed_train_steps: int = Field(default=7, ge=1)
    n_timed_inference_batches: int = Field(default=5, ge=1)


class ContentionSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    foreign_compute_processes: int | None = None
    gpu_utilization_pct: float | None = None
    gpu_memory_used_gb: float | None = None
    telemetry_available: bool = False


class RealizedModelProperties(BaseModel):
    """Recomputed from the IMPLEMENTED model (§16.7) — supersedes every
    LLM-authored estimate downstream."""

    model_config = ConfigDict(frozen=True)

    parameter_count: int = Field(gt=0)
    trainable_parameter_count: int = Field(ge=0)
    parameter_memory_gb: float = Field(gt=0.0)
    dtype: str


class ProbeResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: ProbeStatus
    model_identity: str
    realized: RealizedModelProperties | None = None
    setup_seconds: float | None = Field(default=None, ge=0.0)
    train_ms_per_step: float | None = Field(default=None, gt=0.0)
    train_ms_spread: tuple[float, float] | None = None
    inference_ms_per_batch: float | None = Field(default=None, gt=0.0)
    inference_ms_spread: tuple[float, float] | None = None
    peak_vram_gb: float | None = Field(default=None, gt=0.0)
    concurrency_identity: ConcurrencyIdentity
    contention: ContentionSnapshot
    caps: ProbeCaps
    wall_seconds: float = Field(ge=0.0)
    error: str | None = None


class ProbeExecutors(BaseModel):
    """Injected execution seams. ``setup`` builds the ACTUAL candidate and
    returns realized properties; ``train_step``/``inference_batch`` run
    one real unit and return elapsed milliseconds; ``peak_vram_gb``
    reports the measured peak after execution."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    setup: Callable[[], RealizedModelProperties]
    train_step: Callable[[], float]
    inference_batch: Callable[[], float]
    peak_vram_gb: Callable[[], float | None]


def classify_concurrency(
    snapshot: ContentionSnapshot, *, expected_peer: bool
) -> ConcurrencyIdentity:
    if not snapshot.telemetry_available or snapshot.foreign_compute_processes is None:
        return "unknown_contention"
    if snapshot.foreign_compute_processes == 0:
        return "single_candidate_idle"
    return "pairwise_expected_peer" if expected_peer else "foreign_contended"


def capture_contention_snapshot() -> ContentionSnapshot:
    """Best-effort GPU telemetry via nvidia-smi (production path); a gap
    is recorded as a gap (telemetry_available=False), never guessed."""
    import subprocess

    try:
        util = (
            subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            .stdout.strip()
            .splitlines()[0]
        )
        util_pct, mem_mib = (float(x.strip()) for x in util.split(","))
        procs = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        n_foreign = len([line for line in procs.splitlines() if line.strip()])
        return ContentionSnapshot(
            foreign_compute_processes=n_foreign,
            gpu_utilization_pct=util_pct,
            gpu_memory_used_gb=mem_mib / 1024.0,
            telemetry_available=True,
        )
    except Exception:
        return ContentionSnapshot(telemetry_available=False)


def run_bounded_probe(
    *,
    model_identity: str,
    executors: ProbeExecutors,
    caps: ProbeCaps | None = None,
    expected_peer: bool = False,
    telemetry: Callable[[], ContentionSnapshot] = capture_contention_snapshot,
    clock: Callable[[], float] = time.monotonic,
) -> ProbeResult:
    """Run the bounded probe. Cap breaches and OOM are MEASURED outcomes
    (valid evidence, per §7.4 they may block) — never silent retries."""
    caps = caps or ProbeCaps()
    snapshot = telemetry()
    concurrency = classify_concurrency(snapshot, expected_peer=expected_peer)
    start = clock()

    def _elapsed() -> float:
        return clock() - start

    def _result(status: ProbeStatus, error: str | None = None, **fields: Any) -> ProbeResult:
        return ProbeResult(
            status=status,
            model_identity=model_identity,
            concurrency_identity=concurrency,
            contention=snapshot,
            caps=caps,
            wall_seconds=_elapsed(),
            error=error,
            **fields,
        )

    # ── setup: load the ACTUAL implemented candidate (F-1b) ────────────
    try:
        setup_start = clock()
        realized = executors.setup()
        setup_seconds = clock() - setup_start
    except MemoryError as exc:
        return _result("oom", error=f"setup OOM: {exc}")
    except Exception as exc:
        return _result("load_failure", error=f"candidate load failed: {exc}")
    if _elapsed() > caps.max_wall_seconds:
        return _result(
            "wall_cap",
            realized=realized,
            setup_seconds=setup_seconds,
            error="wall cap hit during setup",
        )

    # ── timed training steps ───────────────────────────────────────────
    train_timings: list[float] = []
    try:
        for i in range(caps.n_warmup_steps + caps.n_timed_train_steps):
            ms = executors.train_step()
            if i >= caps.n_warmup_steps:
                train_timings.append(float(ms))
            if _elapsed() > caps.max_wall_seconds:
                return _result(
                    "wall_cap",
                    realized=realized,
                    setup_seconds=setup_seconds,
                    train_ms_per_step=median(train_timings) if train_timings else None,
                    train_ms_spread=(min(train_timings), max(train_timings))
                    if train_timings
                    else None,
                    peak_vram_gb=executors.peak_vram_gb(),
                    error=f"wall cap hit after {i + 1} training steps",
                )
    except MemoryError as exc:
        return _result(
            "oom",
            realized=realized,
            setup_seconds=setup_seconds,
            peak_vram_gb=executors.peak_vram_gb(),
            error=f"training OOM: {exc}",
        )

    # ── timed inference batches ────────────────────────────────────────
    inf_timings: list[float] = []
    try:
        for i in range(caps.n_timed_inference_batches):
            inf_timings.append(float(executors.inference_batch()))
            if _elapsed() > caps.max_wall_seconds:
                return _result(
                    "wall_cap",
                    realized=realized,
                    setup_seconds=setup_seconds,
                    train_ms_per_step=median(train_timings),
                    train_ms_spread=(min(train_timings), max(train_timings)),
                    inference_ms_per_batch=median(inf_timings),
                    inference_ms_spread=(min(inf_timings), max(inf_timings)),
                    peak_vram_gb=executors.peak_vram_gb(),
                    error=f"wall cap hit after {i + 1} inference batches",
                )
    except MemoryError as exc:
        return _result(
            "oom",
            realized=realized,
            setup_seconds=setup_seconds,
            train_ms_per_step=median(train_timings),
            train_ms_spread=(min(train_timings), max(train_timings)),
            peak_vram_gb=executors.peak_vram_gb(),
            error=f"inference OOM: {exc}",
        )

    return _result(
        "ok",
        realized=realized,
        setup_seconds=setup_seconds,
        train_ms_per_step=median(train_timings),
        train_ms_spread=(min(train_timings), max(train_timings)),
        inference_ms_per_batch=median(inf_timings),
        inference_ms_spread=(min(inf_timings), max(inf_timings)),
        peak_vram_gb=executors.peak_vram_gb(),
    )


# ── §16.6 explicit inference-unit conversions ───────────────────────────────


def total_eval_segments(*, n_files: int, segments_per_file: int, eval_portion: float) -> int:
    """`segments_per_file × n_files × eval_portion` (§16.6), floored at 1
    segment per evaluated file when any evaluation happens at all."""
    if not 0.0 <= eval_portion <= 1.0:
        raise ValueError(f"eval_portion must be in [0,1]; got {eval_portion}")
    if n_files <= 0 or segments_per_file <= 0:
        raise ValueError("n_files and segments_per_file must be positive")
    if eval_portion == 0.0:
        return 0
    per_file = max(1, int(segments_per_file * eval_portion))
    return per_file * n_files


def batches_for_segments(total_segments: int, inference_batch: int) -> int:
    """`ceil(total_segments / inference_batch)` (§16.6)."""
    if inference_batch <= 0:
        raise ValueError(f"inference_batch must be positive; got {inference_batch}")
    if total_segments < 0:
        raise ValueError(f"total_segments must be >= 0; got {total_segments}")
    return -(-total_segments // inference_batch)


# ── extrapolation (§8.2 layer 2) ────────────────────────────────────────────


def extrapolate_probe(
    result: ProbeResult,
    *,
    train_steps: int,
    inference_batches: int,
    producer_identity: str,
) -> RuntimeEstimate:
    """Project the measured rates onto the configured workload. Training
    and inference stay separate (§16.6); bounds come from the probe's own
    timing spread — no invented uncertainty (D-thresholds stay open)."""
    if result.status != "ok" or result.train_ms_per_step is None:
        raise ValueError(f"cannot extrapolate a non-ok probe (status={result.status})")
    train_s = result.train_ms_per_step * train_steps / 1000.0
    inf_s = (
        (result.inference_ms_per_batch or 0.0) * inference_batches / 1000.0
        if result.inference_ms_per_batch is not None
        else None
    )
    setup_s = result.setup_seconds or 0.0
    expected = setup_s + train_s + (inf_s or 0.0)
    lower = upper = None
    if result.train_ms_spread is not None:
        lo_t, hi_t = result.train_ms_spread
        lo_i, hi_i = result.inference_ms_spread or (0.0, 0.0)
        lower = setup_s + lo_t * train_steps / 1000.0 + lo_i * inference_batches / 1000.0
        upper = setup_s + hi_t * train_steps / 1000.0 + hi_i * inference_batches / 1000.0
    return make_estimate(
        provenance="bounded_live_probe",
        confidence="medium",
        expected_seconds=expected if expected > 0 else None,
        lower_seconds=lower if lower and lower > 0 else None,
        upper_seconds=upper if upper and upper > 0 else None,
        setup_seconds=setup_s,
        training_seconds=train_s,
        inference_seconds=inf_s,
        peak_vram_gb=result.peak_vram_gb,
        concurrency_identity=result.concurrency_identity,
        probe_id=None,  # assigned when the observation is registered
        warnings=(),
    )


def probe_observations(
    result: ProbeResult,
    *,
    hardware_compatibility_id: str,
    execution_environment_id: str,
    workload: dict[str, Any],
    software_stack: dict[str, Any],
    source_run: dict[str, Any],
    timestamp_metadata: str | None = None,
) -> list[CalibrationObservation]:
    """Immutable registry records from an ok probe — training and
    inference DISTINCT (§16.6). Written as ``unvalidated``; C7's policy
    owns promotion to ``validated``."""
    if result.status != "ok" or result.realized is None:
        raise ValueError(f"only ok probes produce observations (status={result.status})")
    producer = f"runtime_probe@{PROBE_PRODUCER_SEMVER}"
    realized_payload = result.realized.model_dump(mode="json")
    contention_payload = result.contention.model_dump(mode="json")

    def _record(
        operation: str, unit: str, value_ms: float, spread: tuple[float, float] | None
    ) -> CalibrationObservation:
        return CalibrationObservation(
            operation=operation,  # type: ignore[arg-type]
            measurement_unit=unit,
            measured_value_ms=value_ms,
            workload=workload,
            realized_model=realized_payload,
            hardware_compatibility_id=hardware_compatibility_id,
            execution_environment_id=execution_environment_id,
            concurrency_identity=result.concurrency_identity,
            contention_telemetry=contention_payload,
            software_stack=software_stack,
            producer_identity=producer,
            provenance="bounded_live_probe",
            uncertainty_inputs={"spread_ms": list(spread or ())},
            source_run=source_run,
            validation_status="unvalidated",
            timestamp_metadata=timestamp_metadata,
        )

    records: list[CalibrationObservation] = []
    if result.train_ms_per_step is not None:
        records.append(
            _record(
                "training",
                "optimizer_step",
                result.train_ms_per_step,
                result.train_ms_spread,
            )
        )
    if result.inference_ms_per_batch is not None:
        records.append(
            _record(
                "inference",
                "inference_batch",
                result.inference_ms_per_batch,
                result.inference_ms_spread,
            )
        )
    return records
