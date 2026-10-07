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

F-1a: the dataset path is the ``data_dir`` the caller supplies, resolved
from its task's measurement capability. Step 07 / PR 07c C4 removed the
fallback that used to fill one in from generic code — an absent root is an
explicit refusal, never a second convention and never another task's data.
F-1b: the production builder loads the ACTUAL implemented plugin from
the live registry and recomputes realized properties (§16.7) — the
LLM-authored estimate is never trusted past this point.

Concurrency identity (C8e): the probe classifies contention through the
D3 windowed, PID-aware policy
(``calibration_policy.sample_contention_window``) — a bounded 10-second
window of samples taken before any candidate CUDA work, classified from
external process identity, external memory and sustained utilization,
with self + descendant PIDs excluded and an intended peer identified by
registered PID. The C6 count-based single-sample classifier has been
REMOVED: there is no second authoritative path (operator decision,
2026-07-30). Every raw sample the verdict rests on is persisted on the
observation.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterable
from statistics import median
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.runtime_control.estimate_types import (
    ConcurrencyIdentity,
    RuntimeEstimate,
    make_estimate,
)
from core.runtime_control.measurement_validity import MeasurementValidity
from core.runtime_control.process_visibility import ProcessVisibility, declared_visibility
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
    """One raw telemetry sample. D3 (C7) requires the sample to carry the
    PID-level evidence it was classified from — never just a count — and
    to name the PIDs it excluded (self + descendants), so a stored
    observation can be re-classified and audited after the fact."""

    model_config = ConfigDict(frozen=True)

    process_visibility: ProcessVisibility | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    foreign_compute_processes: int | None = None
    gpu_utilization_pct: float | None = None
    gpu_memory_used_gb: float | None = None
    telemetry_available: bool = False
    compute_process_pids: tuple[int, ...] = Field(
        default=(), description="Every compute PID reported by telemetry (raw)."
    )
    foreign_compute_pids: tuple[int, ...] = Field(
        default=(), description="Reported PIDs minus the excluded set."
    )
    compute_process_memory_gb: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "pid (as a string key, for JSON) -> GB that process holds on the "
            "device. Empty on producers that predate byte-level attribution, "
            "which the classifier treats as UNATTRIBUTABLE rather than as "
            "candidate-owned. A NaN value means the driver reported the "
            "process but not its memory."
        ),
    )
    excluded_pids: tuple[int, ...] = Field(
        default=(),
        description="Self + descendant (+ explicitly excluded) PIDs — D3: "
        "the probing process's own contexts are never foreign.",
    )
    throttle_reasons_hex: int | None = Field(
        default=None,
        description="nvidia-smi clocks_throttle_reasons.active bitmask, or "
        "None when the field is unavailable (an OPTIONAL signal: its "
        "absence is not evidence of throttling — core telemetry "
        "availability is what governs `unknown_contention`).",
    )


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
    #: V20 PR C. The occupancy-window verdict, when the caller named the
    #: device so accounting could be sampled. `None` means no window was
    #: observed — NOT that the measurement was judged invalid.
    measurement_validity: MeasurementValidity | None = None
    contention: ContentionSnapshot = Field(
        description="Last sample of the pre-probe window (compact view)."
    )
    contention_telemetry: dict[str, Any] = Field(
        default_factory=dict,
        description="The FULL D3 window: every raw sample, the verdict, its "
        "reasons, the registered peer PIDs and the policy identity — what "
        "gets persisted on the observation (D3: record all raw telemetry "
        "used for classification).",
    )
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


def descendant_pids(root_pid: int) -> frozenset[int]:
    """Transitive children of ``root_pid`` from /proc (Linux). D3: a
    probe's own worker/dataloader subprocesses are NOT foreign. Any
    failure (non-Linux, race on process exit) yields the empty set —
    a gap, never a guess."""
    children: dict[int, list[int]] = {}
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/status", encoding="utf-8") as fh:
                    status = fh.read()
            except OSError:
                continue  # process exited mid-scan
            for line in status.splitlines():
                if line.startswith("PPid:"):
                    children.setdefault(int(line.split()[1]), []).append(int(entry))
                    break
    except OSError:
        return frozenset()
    found: set[int] = set()
    queue = list(children.get(root_pid, ()))
    while queue:
        pid = queue.pop()
        if pid in found:
            continue
        found.add(pid)
        queue.extend(children.get(pid, ()))
    return frozenset(found)


def _query_throttle_reasons() -> int | None:
    """Optional supplementary signal; any failure → None (unavailable),
    which is NOT the same as 'no throttling' and never fabricated."""
    import subprocess

    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=clocks_throttle_reasons.active",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        first = out.splitlines()[0].strip()
        # nvidia-smi renders this field as `0x<16 hex>`. Anything else is an
        # output shape we do not recognize: report UNAVAILABLE rather than
        # coerce it — a bare decimal string would parse as hex and fabricate
        # a throttle mask out of unrelated output.
        if not first.lower().startswith("0x"):
            return None
        return int(first, 16)
    except Exception:
        return None


def capture_contention_snapshot(*, exclude_pids: Iterable[int] | None = None) -> ContentionSnapshot:
    """Best-effort GPU telemetry via nvidia-smi (production path); a gap
    is recorded as a gap (telemetry_available=False), never guessed.

    D3: the calling process AND its descendants are excluded from the
    foreign set; ``exclude_pids`` adds further known-own PIDs. The raw
    PID list, the excluded set and the throttle bitmask are all recorded
    on the snapshot for after-the-fact audit."""
    import subprocess

    visibility = declared_visibility()
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
        # `used_memory` as well as `pid`: without per-process bytes the
        # classifier cannot ATTRIBUTE memory, and a device total gets
        # labelled "external" even when every process on the device is
        # candidate-owned. That misclassification aborted a real chain
        # (Gate 2 attempt 1: 5.98 GB, zero foreign PIDs, 0% utilisation,
        # reported as foreign_contended).
        procs = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        # FOREIGN means processes other than ourselves: the probing
        # process's own CUDA context must not count (C6 GPU-smoke
        # finding 2026-07-30 — self-counting misclassified probe B as
        # foreign_contended after probe A initialized CUDA in-process).
        # D3 extends this to the probe's descendants.
        own = os.getpid()
        excluded = {own} | set(descendant_pids(own)) | set(exclude_pids or ())
        per_process: dict[int, float] = {}
        for line in procs.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if not parts or not parts[0].isdigit():
                continue
            pid = int(parts[0])
            if len(parts) < 2:
                # Single-column output: an older driver, or a producer that
                # reports pids without sizes. The PID is still evidence and
                # MUST keep counting toward foreign detection — dropping the
                # row would silently disable that. Its memory is
                # unattributable, which the classifier resolves through the
                # residual rather than by assuming zero.
                per_process[pid] = float("nan")
                continue
            try:
                per_process[pid] = float(parts[1]) / 1024.0
            except ValueError:
                per_process[pid] = float("nan")
        # Reported ORDER preserved (dicts keep insertion order); sorting
        # here would silently change an observable field.
        reported = tuple(per_process)
        foreign = tuple(pid for pid in reported if pid not in excluded)
        return ContentionSnapshot(
            process_visibility=visibility,
            compute_process_memory_gb={str(k): v for k, v in per_process.items()},
            foreign_compute_processes=len(foreign),
            gpu_utilization_pct=util_pct,
            gpu_memory_used_gb=mem_mib / 1024.0,
            telemetry_available=True,
            compute_process_pids=reported,
            foreign_compute_pids=foreign,
            excluded_pids=tuple(sorted(excluded)),
            throttle_reasons_hex=_query_throttle_reasons(),
        )
    except Exception:
        return ContentionSnapshot(telemetry_available=False, process_visibility=visibility)


def is_out_of_memory(exc: BaseException) -> bool:
    """Is this exception an out-of-memory condition?

    CRITICAL (C12 finding, 2026-07-31): ``torch.cuda.OutOfMemoryError``
    subclasses **RuntimeError, not MemoryError**. Every handler here used
    to catch `MemoryError`, so a REAL CUDA OOM was never classified as a
    measured failure — it escaped as an unclassified exception, which the
    C9b resolver then turned into ABORT, halting the whole chain for a
    candidate that merely did not fit. The unit tests never caught this
    because they all raised `MemoryError`, a shape production cannot
    produce.

    Detection stays torch-free (this module must import no torch): the
    exception TYPE NAME and message are checked instead, which also
    covers accelerator backends this repo does not import.
    """
    if isinstance(exc, MemoryError):
        return True
    if type(exc).__name__ in ("OutOfMemoryError", "CudaOutOfMemoryError"):
        return True
    return isinstance(exc, RuntimeError) and "out of memory" in str(exc).lower()


def run_bounded_probe(
    *,
    model_identity: str,
    executors: ProbeExecutors,
    caps: ProbeCaps | None = None,
    device_vram_gb: float,
    expected_peer_pids: Iterable[int] = (),
    contention_window: Callable[..., Any] | None = None,
    clock: Callable[[], float] = time.monotonic,
    device_identity: Any | None = None,
) -> ProbeResult:
    """Run the bounded probe. Cap breaches and OOM are MEASURED outcomes
    (valid evidence, per §7.4 they may block) — never silent retries.

    Concurrency identity comes from the D3 WINDOWED, PID-aware classifier
    (C8e, operator decision 2026-07-30): a bounded 10-second window of
    samples taken BEFORE any candidate CUDA work begins, classified from
    external process identity, memory and sustained utilization. The
    count-based single-sample classifier is gone — there is no second
    authoritative path.

    Ordering (C8e implementation decision): the window runs to completion
    BEFORE setup, serially. The operator permits overlapping it with
    CPU-only setup as a non-semantic optimization; that is deliberately
    not taken here, because running the window first is both simpler and
    strictly more correct — the probe's own CUDA context does not exist
    yet, so nothing of ours can contaminate the external-state reading.
    The ~10 s cost is the accepted price.

    ``device_vram_gb`` is REQUIRED: the D3 memory threshold is
    ``max(1 GiB, 10 % of device VRAM)`` and there is no safe default for
    an unknown device.
    """
    from core.runtime_control.calibration_policy import sample_contention_window

    caps = caps or ProbeCaps()
    sampler = contention_window or sample_contention_window
    # V20 PR C: the identity is passed DOWN from the orchestration boundary,
    # never discovered here. `None` means the caller had none (CPU host,
    # legacy manifest), and the window then carries no validity verdict —
    # a gap, not a guessed device.
    window_kwargs: dict[str, Any] = {
        "device_vram_gb": device_vram_gb,
        "expected_peer_pids": tuple(expected_peer_pids),
    }
    if device_identity is not None:
        window_kwargs["device"] = device_identity
    window = sampler(**window_kwargs)
    concurrency = window.classification
    snapshot = window.samples[-1] if window.samples else ContentionSnapshot()
    start = clock()

    def _elapsed() -> float:
        return clock() - start

    def _result(status: ProbeStatus, error: str | None = None, **fields: Any) -> ProbeResult:
        return ProbeResult(
            status=status,
            model_identity=model_identity,
            concurrency_identity=concurrency,
            measurement_validity=window.measurement_validity,
            contention=snapshot,
            contention_telemetry=window.raw_telemetry(),
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
    except Exception as exc:
        if is_out_of_memory(exc):
            return _result("oom", error=f"setup OOM: {exc}")
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
    except Exception as exc:
        if not is_out_of_memory(exc):
            raise
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
    except Exception as exc:
        if not is_out_of_memory(exc):
            raise
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
        measurement_validity=result.measurement_validity,
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
    model_family: str = "unknown",
) -> list[CalibrationObservation]:
    """Immutable registry records from an ok probe — training and
    inference DISTINCT (§16.6). Written as ``unvalidated``; C7's policy
    owns promotion to ``validated``.

    ``model_family`` (D5) must come from explicit implementation
    metadata / deterministic structural features
    (``calibration_policy.classify_model_family``); the default
    ``"unknown"`` is a first-class bucket, never the nearest known
    family."""
    if result.status != "ok" or result.realized is None:
        raise ValueError(f"only ok probes produce observations (status={result.status})")
    producer = f"runtime_probe@{PROBE_PRODUCER_SEMVER}"
    realized_payload = result.realized.model_dump(mode="json")
    # D3: the FULL window is the evidence; the single snapshot is only a
    # fallback for results produced before the windowed classifier (C8e).
    contention_payload = result.contention_telemetry or result.contention.model_dump(mode="json")

    def _record(
        operation: str, unit: str, value_ms: float, spread: tuple[float, float] | None
    ) -> CalibrationObservation:
        return CalibrationObservation(
            operation=operation,  # type: ignore[arg-type]
            measurement_unit=unit,
            measured_value_ms=value_ms,
            workload=workload,
            realized_model=realized_payload,
            model_family=model_family,
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
