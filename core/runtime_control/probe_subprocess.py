"""Hard-bounded probe execution behind a process boundary (C12 defect fix).

`ProbeCaps.max_wall_seconds` was only ever checked BETWEEN operations, so
a single slow CUDA setup, training step or inference batch ran unbounded.
The C12 campaign hit exactly that: `transformer@8M-ceiling` never
returned, at a 900 s and then a 2400 s external kill.

A Python watchdog thread cannot fix this — a thread blocked inside a CUDA
call is not interruptible from Python. The bound therefore has to come
from outside the process:

```text
parent
  -> launch worker in its OWN PROCESS GROUP (start_new_session)
  -> worker runs setup/training/inference, writes a typed result file
  -> parent enforces the hard deadline
     -> SIGTERM the process group
     -> bounded grace
     -> SIGKILL the process group only if still alive
  -> parent validates the result and classifies the outcome
```

Classification is the operator-approved mapping, and the distinction is
the whole point:

* candidate exceeded the hard cap        -> measured failure -> REJECT
* candidate OOM                          -> measured failure -> REJECT
* candidate signalled while at the device/quota capacity bound
                                         -> measured failure -> REJECT
* launch / IPC / schema / process-control failure
                                         -> infrastructure   -> ABORT

The capacity case exists because a candidate can be reaped from OUTSIDE
this process — by a shared-host VRAM-quota watchdog, a scheduler, or a
container limit — before it can report anything. The parent therefore
samples the worker's OWN device footprint while it runs, so that
"killed while sitting at the ceiling" remains attributable evidence
about the model rather than an unexplained infrastructure abort that
would halt an entire chain.

Nothing is fabricated: an operation that did not complete contributes no
throughput number. A timeout record carries the phase that was active,
the elapsed time, the worker PID and process group, which signals were
sent, and whatever measurements DID complete before the stall.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.runtime_control.probe import descendant_pids

WorkerPhase = Literal["launch", "setup", "training", "inference", "complete"]
WorkerStatus = Literal["ok", "oom", "load_failure", "wall_cap"]

#: How long the worker gets to exit after SIGTERM before SIGKILL.
DEFAULT_GRACE_SECONDS = 10.0
#: Ceiling on the parent's own bookkeeping, so the hard cap stays honest.
PROCESS_CONTROL_OVERHEAD_SECONDS = 5.0

#: Signals that, when they land on a worker that had ALREADY entered
#: candidate work, are evidence ABOUT THE CANDIDATE rather than about our
#: infrastructure:
#:
#: * SIGKILL  — the host OOM killer, i.e. the candidate's host-memory
#:              demand exceeded the machine;
#: * SIGABRT  — a CUDA/library hard abort raised inside candidate code;
#: * SIGSEGV / SIGBUS / SIGILL / SIGFPE — a fault inside candidate code.
#:
#: Signals NOT listed here (SIGINT, SIGHUP, SIGTERM from outside, …) are
#: statements about the environment or the operator, never about the
#: candidate, and stay infrastructure. "Terminated by a signal" alone is
#: deliberately NOT sufficient — the phase evidence must show the worker
#: had reached candidate work.
CANDIDATE_FAILURE_SIGNALS = frozenset(
    {
        signal.SIGKILL,
        signal.SIGABRT,
        signal.SIGSEGV,
        signal.SIGBUS,
        signal.SIGILL,
        signal.SIGFPE,
    }
)
#: Phases in which the worker is executing the CANDIDATE (loading it
#: counts: a model that cannot be constructed within the machine is a
#: fact about the model).
CANDIDATE_WORK_PHASES = frozenset({"setup", "training", "inference"})

#: Optional per-user VRAM quota, in GiB, enforced by something OUTSIDE
#: this process (a shared-host watchdog, a scheduler, a container limit).
#: Read from the environment because it is a property of the DEPLOYMENT,
#: never of the checkout.
VRAM_QUOTA_ENV = "SIDERIUS_GPU_VRAM_QUOTA_GB"
#: Absent an explicit quota, a worker holding this fraction of the device
#: is at the capacity boundary by any reasonable reading.
DEFAULT_VRAM_ATTRIBUTION_FRACTION = 0.90


def vram_attribution_threshold_gb(device_vram_gb: float) -> float:
    """Above this, a worker's own VRAM footprint is capacity evidence.

    An explicitly configured quota wins when it is the tighter bound —
    on a shared host the enforced quota, not the card, is the real
    ceiling.
    """
    fraction_bound = DEFAULT_VRAM_ATTRIBUTION_FRACTION * device_vram_gb
    raw = os.environ.get(VRAM_QUOTA_ENV)
    if not raw:
        return fraction_bound
    try:
        quota = float(raw)
    except ValueError:
        return fraction_bound
    return min(quota, fraction_bound) if quota > 0 else fraction_bound


def sample_worker_vram_gb(pgid: int) -> float | None:
    """GiB of device memory held by the worker's process group, or None
    when telemetry is unavailable. A gap is a gap, never a zero."""
    import subprocess as _sp

    try:
        out = _sp.run(
            [
                "nvidia-smi",
                "--query-compute-apps=pid,used_gpu_memory",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
    except Exception:
        return None
    own = {pgid, *descendant_pids(pgid)}
    total_mib = 0.0
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        if int(parts[0]) in own:
            with contextlib.suppress(ValueError):
                total_mib += float(parts[1])
    return total_mib / 1024.0 if total_mib else None


class ProbeWorkerSpec(BaseModel):
    """Parent -> worker. Bounded, typed, passed as a file (not argv)."""

    model_config = ConfigDict(frozen=True)

    model_type: str
    model_config_payload: dict[str, Any] = Field(default_factory=dict)
    train_config: dict[str, Any] = Field(default_factory=dict)
    loss_config: dict[str, Any] = Field(default_factory=dict)
    data_dir: str | None = None
    device: str = "cuda"
    caps: dict[str, Any] = Field(default_factory=dict)
    device_vram_gb: float = Field(gt=0.0)
    result_path: str
    #: EXPLICITLY registered partner PIDs (C12-C). A peer is never
    #: inferred from a process name — the launcher declares it.
    expected_peer_pids: tuple[int, ...] = ()
    #: >0 turns this worker into a sustained BACKGROUND LOAD: it sets up,
    #: then trains until the deadline. Used as the partner in a pairwise
    #: concurrency cell, where the measured member needs a peer that is
    #: genuinely computing (not merely resident) during its window.
    sustained_seconds: float = Field(default=0.0, ge=0.0)


class ProbeWorkerResult(BaseModel):
    """Worker -> parent. Whatever completed, and nothing that did not."""

    model_config = ConfigDict(frozen=True)

    status: WorkerStatus
    phase: WorkerPhase = "complete"
    model_identity: str
    realized: dict[str, Any] | None = None
    setup_seconds: float | None = Field(default=None, ge=0.0)
    train_ms_per_step: float | None = Field(default=None, gt=0.0)
    train_ms_spread: tuple[float, float] | None = None
    inference_ms_per_batch: float | None = Field(default=None, gt=0.0)
    inference_ms_spread: tuple[float, float] | None = None
    peak_vram_gb: float | None = Field(default=None, gt=0.0)
    concurrency_identity: str | None = None
    contention_telemetry: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ProbeTerminationRecord(BaseModel):
    """Exactly what the parent did, for a run that had to be stopped."""

    model_config = ConfigDict(frozen=True)

    timed_out: bool = False
    phase_at_timeout: WorkerPhase | None = None
    #: The worker's last announced phase at exit, however it exited.
    phase_at_exit: WorkerPhase | None = None
    elapsed_seconds: float = Field(default=0.0, ge=0.0)
    hard_cap_seconds: float = Field(default=0.0, ge=0.0)
    worker_pid: int | None = None
    worker_pgid: int | None = None
    term_sent: bool = False
    kill_sent: bool = False
    grace_seconds: float = DEFAULT_GRACE_SECONDS
    exit_code: int | None = None
    #: Set when the worker was terminated by a signal (POSIX: rc < 0).
    signal_number: int | None = None
    signal_name: str | None = None
    #: Did the worker leave a result record at all?
    result_present: bool = False
    #: Bounded tail of the worker's own output — the only evidence that
    #: survives a SIGKILL.
    worker_log_tail: str = ""
    #: Peak device memory the worker itself held, sampled by the PARENT
    #: while it ran. This is the only VRAM evidence that survives a worker
    #: killed before it could report (C12: an external quota watchdog).
    observed_peak_vram_gb: float | None = Field(default=None, ge=0.0)
    #: The bound that peak was judged against, when one applied.
    vram_attribution_threshold_gb: float | None = Field(default=None, gt=0.0)
    orphans_remaining: bool = False


class ProbeExecutionOutcome(BaseModel):
    """The parent's verdict about one worker run."""

    model_config = ConfigDict(frozen=True)

    classification: Literal["measured_failure", "infrastructure_failure", "ok"]
    result: ProbeWorkerResult | None = None
    termination: ProbeTerminationRecord
    detail: str = ""


class ProbeInfrastructureFailure(Exception):
    """Launch, IPC, schema or process-control failure — never a verdict
    about the candidate."""


def _process_group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _signal_group(pgid: int, sig: int) -> bool:
    """Signal the whole group; False when it is already gone."""
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _read_phase(progress_path: Path) -> WorkerPhase | None:
    """The worker's last announced phase — what it was doing when it
    stalled. Best-effort: a missing file is a gap, not a guess."""
    try:
        phase = progress_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return phase if phase in ("launch", "setup", "training", "inference", "complete") else None


def spawn_worker(
    spec: ProbeWorkerSpec, *, command: list[str] | None = None
) -> tuple[subprocess.Popen, Any, Path]:
    """Launch one worker in its OWN process group and return immediately.

    Returns ``(process, log_handle, log_path)``. The caller owns the
    deadline, the log handle and the eventual termination — see
    `run_worker` for the blocking, deadline-enforcing use, and the C12-C
    pairwise driver for the concurrent one.
    """
    result_path = Path(spec.result_path)
    spec_path = result_path.with_suffix(".spec.json")
    try:
        result_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(spec.model_dump_json(indent=1), encoding="utf-8")
    except OSError as exc:
        raise ProbeInfrastructureFailure(f"could not write the worker spec: {exc}") from exc

    argv = command or [
        sys.executable,
        "-m",
        "core.runtime_control.probe_worker_main",
        str(spec_path),
    ]
    # File-backed stdio rather than PIPE: a PIPE nobody drains can deadlock
    # a chatty child, and its contents are lost when the child is killed.
    # On disk, the worker's diagnostics survive even a SIGKILL.
    log_path = result_path.with_suffix(".worker.log")
    try:
        log_handle = log_path.open("w", encoding="utf-8")
    except OSError as exc:
        raise ProbeInfrastructureFailure(f"could not open the worker log: {exc}") from exc
    try:
        # start_new_session -> the child leads its own process group, so a
        # kill reaches every dataloader worker it spawned, not just itself.
        process = subprocess.Popen(
            argv,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except Exception as exc:
        log_handle.close()
        raise ProbeInfrastructureFailure(f"could not launch the probe worker: {exc!r}") from exc
    return process, log_handle, log_path


def stop_worker(process: subprocess.Popen, *, grace_seconds: float = DEFAULT_GRACE_SECONDS) -> None:
    """Terminate a worker's whole process group, escalating if needed."""
    pgid = process.pid
    if process.poll() is not None:
        return
    _signal_group(pgid, signal.SIGTERM)
    deadline = time.monotonic() + grace_seconds
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.1)
    if process.poll() is None:
        _signal_group(pgid, signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=PROCESS_CONTROL_OVERHEAD_SECONDS)


def run_worker(
    spec: ProbeWorkerSpec,
    *,
    hard_cap_seconds: float,
    grace_seconds: float = DEFAULT_GRACE_SECONDS,
    command: list[str] | None = None,
    poll_seconds: float = 0.1,
    clock: Any = time.monotonic,
    usage_sampler: Any = sample_worker_vram_gb,
    usage_sample_seconds: float = 2.0,
) -> ProbeExecutionOutcome:
    """Run one probe worker under a HARD wall deadline.

    ``command`` is injectable so unit tests can drive deterministic fake
    workers (stuck in setup, stuck in a step, malformed output, …)
    without a GPU.
    """
    result_path = Path(spec.result_path)
    progress_path = result_path.with_suffix(".phase")
    process, log_handle, log_path = spawn_worker(spec, command=command)

    pgid = process.pid  # session leader: pgid == pid
    started = clock()
    term_sent = kill_sent = False
    timed_out = False
    observed_peak_vram_gb: float | None = None
    next_usage_sample = started

    while True:
        if process.poll() is not None:
            break
        elapsed = clock() - started
        # The parent watches the worker's OWN footprint, because a worker
        # killed from outside never gets to report its peak.
        if usage_sampler is not None and clock() >= next_usage_sample:
            next_usage_sample = clock() + usage_sample_seconds
            sampled = usage_sampler(pgid)
            if sampled is not None:
                observed_peak_vram_gb = max(observed_peak_vram_gb or 0.0, sampled)
        if elapsed >= hard_cap_seconds and not term_sent:
            timed_out = True
            term_sent = _signal_group(pgid, signal.SIGTERM)
            grace_deadline = clock() + grace_seconds
            while process.poll() is None and clock() < grace_deadline:
                time.sleep(poll_seconds)
            if process.poll() is None:
                kill_sent = _signal_group(pgid, signal.SIGKILL)
                try:
                    process.wait(timeout=PROCESS_CONTROL_OVERHEAD_SECONDS)
                except subprocess.TimeoutExpired as exc:
                    raise ProbeInfrastructureFailure(
                        f"probe worker {process.pid} survived SIGKILL"
                    ) from exc
            break
        time.sleep(poll_seconds)

    elapsed = clock() - started
    log_handle.close()
    worker_log_tail = _log_tail(log_path)
    phase_at_exit = _read_phase(progress_path)
    returncode = process.returncode
    exit_signal = -returncode if returncode is not None and returncode < 0 else None
    result_present = result_path.is_file()
    vram_threshold = vram_attribution_threshold_gb(spec.device_vram_gb)
    termination = ProbeTerminationRecord(
        timed_out=timed_out,
        phase_at_timeout=phase_at_exit if timed_out else None,
        phase_at_exit=phase_at_exit,
        elapsed_seconds=round(elapsed, 3),
        hard_cap_seconds=hard_cap_seconds,
        worker_pid=process.pid,
        worker_pgid=pgid,
        term_sent=term_sent,
        kill_sent=kill_sent,
        grace_seconds=grace_seconds,
        exit_code=returncode,
        signal_number=exit_signal,
        signal_name=signal.Signals(exit_signal).name if exit_signal else None,
        result_present=result_present,
        worker_log_tail=worker_log_tail,
        observed_peak_vram_gb=observed_peak_vram_gb,
        vram_attribution_threshold_gb=vram_threshold,
        orphans_remaining=_process_group_alive(pgid),
    )

    if timed_out:
        # A candidate that cannot finish one operation inside the cap is a
        # MEASURED statement about the candidate. Whatever completed before
        # the stall is preserved; nothing is extrapolated from an operation
        # that never returned.
        partial = _load_result(result_path, required=False)
        return ProbeExecutionOutcome(
            classification="measured_failure",
            result=partial,
            termination=termination,
            detail=(
                f"probe exceeded the hard cap of {hard_cap_seconds:.0f}s during "
                f"{termination.phase_at_timeout or 'an unreported phase'} "
                f"(elapsed {elapsed:.1f}s). Worker output: {worker_log_tail or '<empty>'}"
            ),
        )

    if exit_signal is not None and not result_present:
        # The worker died before it could say anything. Whether that is a
        # statement about the CANDIDATE or about our infrastructure is
        # decided from evidence — the signal AND the phase it had reached
        # — never from the bare fact that a signal arrived.
        at_capacity = observed_peak_vram_gb is not None and observed_peak_vram_gb >= vram_threshold
        # Either the signal itself implicates the candidate, or the
        # candidate was measured sitting at the device/quota ceiling when
        # it was reaped — an external quota watchdog SIGTERMs, and SIGTERM
        # alone must never be read as a candidate verdict (an operator
        # stop looks identical).
        attributable = phase_at_exit in CANDIDATE_WORK_PHASES and (
            exit_signal in CANDIDATE_FAILURE_SIGNALS or at_capacity
        )
        detail = (
            f"probe worker was terminated by {termination.signal_name} "
            f"({exit_signal}) during {phase_at_exit or 'an unreported phase'} "
            f"after {elapsed:.1f}s, leaving no result. "
            f"Peak VRAM held by the worker: "
            f"{observed_peak_vram_gb if observed_peak_vram_gb is not None else 'unknown'} GiB "
            f"(attribution threshold {vram_threshold:.2f} GiB). "
            f"Worker output: {worker_log_tail or '<empty>'}"
        )
        if attributable:
            # e.g. the host OOM killer reaping a candidate whose host-memory
            # demand exceeded the machine: a REJECT-worthy measured fact
            # about that candidate, not a broken evidence channel.
            return ProbeExecutionOutcome(
                classification="measured_failure",
                result=None,
                termination=termination,
                detail=detail
                + (
                    "Attributed to the candidate: it was holding "
                    f"{observed_peak_vram_gb:.2f} GiB, at or above the "
                    f"{vram_threshold:.2f} GiB capacity bound, when it was reaped."
                    if at_capacity
                    else "Attributed to the candidate: this signal, raised while "
                    "the candidate itself was executing, is a resource/candidate "
                    "failure."
                ),
            )
        raise ProbeInfrastructureFailure(detail)

    result = _load_result(result_path, required=True, log_tail=worker_log_tail)
    assert result is not None
    if result.status in ("oom", "wall_cap"):
        return ProbeExecutionOutcome(
            classification="measured_failure",
            result=result,
            termination=termination,
            detail=f"probe reported {result.status}: {result.error}",
        )
    if result.status == "load_failure":
        return ProbeExecutionOutcome(
            classification="infrastructure_failure",
            result=result,
            termination=termination,
            detail=f"candidate could not be built: {result.error}",
        )
    return ProbeExecutionOutcome(classification="ok", result=result, termination=termination)


def _log_tail(path: Path, *, limit: int = 1500) -> str:
    """The worker's last words. Without this a hard failure is silent."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    return text[-limit:]


def _load_result(path: Path, *, required: bool, log_tail: str = "") -> ProbeWorkerResult | None:
    """Read the worker's typed result. A malformed or missing result when
    one was expected is an INFRASTRUCTURE failure — the candidate said
    nothing, our channel did."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        if not required:
            return None
        raise ProbeInfrastructureFailure(
            f"probe worker exited without writing a result to {path}: {exc}. "
            f"Worker output: {log_tail or '<empty>'}"
        ) from exc
    try:
        return ProbeWorkerResult.model_validate_json(raw)
    except Exception as exc:
        if not required:
            return None
        raise ProbeInfrastructureFailure(
            f"probe worker wrote a result that does not validate: {exc}. "
            f"Worker output: {log_tail or '<empty>'}"
        ) from exc


def write_progress(progress_path: str | Path, phase: WorkerPhase) -> None:
    """Worker-side: announce the current phase so a timeout can name it."""
    # A progress gap must never break the probe itself.
    with contextlib.suppress(OSError):
        Path(progress_path).write_text(phase, encoding="utf-8")


def worker_result_paths(result_path: str | Path) -> dict[str, Path]:
    base = Path(result_path)
    return {
        "result": base,
        "spec": base.with_suffix(".spec.json"),
        "progress": base.with_suffix(".phase"),
    }


def dump_result(result: ProbeWorkerResult, path: str | Path) -> None:
    """Worker-side: atomic write, so the parent never reads a torn file."""
    target = Path(path)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(result.model_dump(mode="json"), indent=1), encoding="utf-8")
    os.replace(tmp, target)
