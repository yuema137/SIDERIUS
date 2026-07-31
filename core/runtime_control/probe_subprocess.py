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
* launch / IPC / schema / process-control failure
                                         -> infrastructure   -> ABORT

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

WorkerPhase = Literal["launch", "setup", "training", "inference", "complete"]
WorkerStatus = Literal["ok", "oom", "load_failure", "wall_cap"]

#: How long the worker gets to exit after SIGTERM before SIGKILL.
DEFAULT_GRACE_SECONDS = 10.0
#: Ceiling on the parent's own bookkeeping, so the hard cap stays honest.
PROCESS_CONTROL_OVERHEAD_SECONDS = 5.0


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
    elapsed_seconds: float = Field(default=0.0, ge=0.0)
    hard_cap_seconds: float = Field(default=0.0, ge=0.0)
    worker_pid: int | None = None
    worker_pgid: int | None = None
    term_sent: bool = False
    kill_sent: bool = False
    grace_seconds: float = DEFAULT_GRACE_SECONDS
    exit_code: int | None = None
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


def run_worker(
    spec: ProbeWorkerSpec,
    *,
    hard_cap_seconds: float,
    grace_seconds: float = DEFAULT_GRACE_SECONDS,
    command: list[str] | None = None,
    poll_seconds: float = 0.1,
    clock: Any = time.monotonic,
) -> ProbeExecutionOutcome:
    """Run one probe worker under a HARD wall deadline.

    ``command`` is injectable so unit tests can drive deterministic fake
    workers (stuck in setup, stuck in a step, malformed output, …)
    without a GPU.
    """
    result_path = Path(spec.result_path)
    spec_path = result_path.with_suffix(".spec.json")
    progress_path = result_path.with_suffix(".phase")
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

    pgid = process.pid  # session leader: pgid == pid
    started = clock()
    term_sent = kill_sent = False
    timed_out = False

    while True:
        if process.poll() is not None:
            break
        elapsed = clock() - started
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
    termination = ProbeTerminationRecord(
        timed_out=timed_out,
        phase_at_timeout=_read_phase(progress_path) if timed_out else None,
        elapsed_seconds=round(elapsed, 3),
        hard_cap_seconds=hard_cap_seconds,
        worker_pid=process.pid,
        worker_pgid=pgid,
        term_sent=term_sent,
        kill_sent=kill_sent,
        grace_seconds=grace_seconds,
        exit_code=process.returncode,
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
