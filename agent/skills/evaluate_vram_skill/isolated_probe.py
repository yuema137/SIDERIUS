"""Run a candidate VRAM pre-flight inside an isolated, memory-bounded worker.

Why this exists, precisely. On 2026-07-31 a Transformer candidate's
pre-flight grew to **60.5 GB of anonymous RSS** on a 61 GB host and the
kernel OOM-killer reaped the whole validation process. The GPU sat at
273 MiB throughout — VRAM was never the constraint. Nothing was measured
about that candidate; the process that was supposed to measure it died.

The protection that used to prevent this was accidental. A single
60-second alarm bounded the pre-flight, and its own comment recorded the
real reason: *"A Python time-loop inside forward() at long T will burn
host RAM linearly under autograd… SIGALRM trips long before that point."*
Wall time was standing in for a memory bound. Removing the timeout to fix
a separate defect removed the memory protection with it.

Wall time is the wrong instrument for memory. This module bounds memory
directly, and does it where it can be bounded at all — in a child
process:

```text
parent validates a LIGHTWEIGHT config      (never builds the model)
  -> launches ONE worker per candidate, own process group
     -> worker applies its own RLIMIT_AS BEFORE constructing anything
     -> worker builds, inspects, probes, writes a bounded JSON result
  -> parent samples worker-tree RSS and the deadline
     -> TERM process group -> bounded grace -> KILL
  -> parent reaps descendants and classifies a TYPED disposition
```

Two rules the parent must never break, because breaking either puts the
limit on the wrong side of the boundary:

* the parent must not instantiate the candidate model — once the model
  is in the parent, a child limit is already too late;
* nothing large may cross back — only bounded structured metadata.
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
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

#: Terminal dispositions. Each names WHAT was established, so that
#: authority to reject a candidate — or to tell an agent to shrink it —
#: can be derived rather than guessed.
PreflightOutcome = Literal[
    "COMPLETED_MEASUREMENT",
    "MEASURED_CUDA_OOM",
    "MEASURED_PEAK_ABOVE_VRAM_CAP",
    "MEASURED_HARD_TIMEOUT",
    "MEASURED_HOST_MEMORY_EXCEEDED",
    "HOST_MEMORY_ALLOCATION_FAILURE",
    "SCHEMA_REJECTED",
    "PROBE_INFRASTRUCTURE_FAILURE",
]

#: Only these establish that the model does not fit the GPU.
VRAM_CAPACITY_OUTCOMES = frozenset({"MEASURED_CUDA_OOM", "MEASURED_PEAK_ABOVE_VRAM_CAP"})
#: This establishes a HOST-memory problem — a different constraint, and
#: not evidence that GPU parameters must shrink.
#: Both are candidate-level HOST-memory facts. The first is the parent
#: stopping a worker whose measured RSS crossed the ceiling; the second is
#: the allocator refusing the candidate outright. Neither says anything
#: about VRAM.
HOST_MEMORY_OUTCOMES = frozenset(
    {"MEASURED_HOST_MEMORY_EXCEEDED", "HOST_MEMORY_ALLOCATION_FAILURE"}
)
#: These establish nothing about the candidate's size.
NO_DOWNSIZING_AUTHORITY = frozenset(
    {
        "MEASURED_HARD_TIMEOUT",
        "SCHEMA_REJECTED",
        "PROBE_INFRASTRUCTURE_FAILURE",
    }
)


def default_worker_memory_limit_bytes() -> int:
    """Host-memory ceiling for ONE candidate worker.

    Derived from this deployment rather than chosen round: the host has
    ~61.8 GiB total with ~3.6 GiB resident in OS services. Production
    runs TWO chains concurrently and each may hold a pre-flight worker,
    so the binding arithmetic is 2 x limit + OS + both parents:

        2 x 24 GiB = 48.0     workers
        + ~4 GiB              OS and services
        + ~1 GiB              the two parent processes
        = ~53 GiB of 61.8     leaving ~8.8 GiB headroom

    24 GiB also sits far above any legitimate candidate: the 323M FCNet
    pre-flight completed in 6.79 s well inside it. A worker that reaches
    24 GiB is pathological, which is exactly what this is for.

    Overridable per deployment; never inferred silently from free memory,
    because a transient reading would make the bound irreproducible.
    """
    raw = os.environ.get("SIDERIUS_PREFLIGHT_WORKER_MEM_GIB")
    gib = 24.0
    if raw:
        try:
            candidate = float(raw)
            if candidate > 0:
                gib = candidate
        except ValueError:
            pass
    return int(gib * 1024**3)


class IsolatedProbeSpec(BaseModel):
    """Everything the worker needs. Deliberately small and JSON-only."""

    model_config = ConfigDict(frozen=True)

    label: str = Field(min_length=1)
    model_type: str = Field(min_length=1)
    model_config_payload: dict[str, Any] = Field(default_factory=dict)
    train_config: dict[str, Any] = Field(default_factory=dict)
    loss_config: dict[str, Any] = Field(default_factory=dict)
    vram_budget_gb: float = Field(gt=0.0)
    result_path: str
    worker_memory_limit_bytes: int = Field(gt=0)


class HostMemoryEvidence(BaseModel):
    """What the host-memory bound observed. Present on every outcome, so
    "it was fine" is recorded as explicitly as "it was not"."""

    model_config = ConfigDict(frozen=True)

    limit_bytes: int = Field(gt=0)
    limit_gib: float = Field(gt=0.0)
    peak_worker_rss_bytes: int = Field(default=0, ge=0)
    peak_worker_rss_gib: float = Field(default=0.0, ge=0.0)
    enforcement: Literal["parent_rss_monitor", "allocator_refusal", "none"] = "none"
    exceeded: bool = False


class IsolatedProbeResult(BaseModel):
    """One candidate's typed outcome. Never prose the caller must parse."""

    model_config = ConfigDict(frozen=True)

    label: str
    outcome: PreflightOutcome
    detail: str = ""
    realized_parameter_count: int | None = Field(default=None, ge=0)
    trainable_parameter_count: int | None = Field(default=None, ge=0)
    dtype: str | None = None
    device: str | None = None
    estimated_gb: float | None = Field(default=None, ge=0.0)
    vram_cap_gb: float | None = Field(default=None, gt=0.0)
    cuda_peak_allocated_gb: float | None = Field(default=None, ge=0.0)
    cuda_peak_reserved_gb: float | None = Field(default=None, ge=0.0)
    inference_batch: int | None = Field(default=None, gt=0)
    host_memory: HostMemoryEvidence | None = None
    elapsed_seconds: float = Field(default=0.0, ge=0.0)
    phase: str | None = None
    worker_pid: int | None = None
    worker_pgid: int | None = None
    exit_code: int | None = None
    signal_number: int | None = None
    orphans_remaining: bool = False
    schema_field: str | None = None
    schema_message: str | None = None

    @property
    def may_recommend_vram_downsizing(self) -> bool:
        """Only a measured GPU-capacity result may ask for less GPU use."""
        return self.outcome in VRAM_CAPACITY_OUTCOMES

    @property
    def may_recommend_host_memory_reduction(self) -> bool:
        return self.outcome in HOST_MEMORY_OUTCOMES

    @property
    def has_capacity_authority(self) -> bool:
        return self.outcome in (VRAM_CAPACITY_OUTCOMES | HOST_MEMORY_OUTCOMES)

    def agent_facing_message(self) -> str:
        """What an agent may act on — and, as importantly, what it may not.

        A host-memory excess must never be phrased as a VRAM verdict: the
        candidate may fit the GPU perfectly and still have blown up CPU
        tracing.
        """
        if self.outcome == "COMPLETED_MEASUREMENT":
            return (
                f"Pre-flight completed: {self.realized_parameter_count:,} parameters, "
                f"estimated {self.estimated_gb} GB against a {self.vram_cap_gb} GB cap."
            )
        if self.outcome == "MEASURED_CUDA_OOM":
            return (
                "The candidate ran out of GPU memory during a measured probe. "
                "Reduce GPU memory use (batch size, sequence length, or capacity)."
            )
        if self.outcome == "MEASURED_PEAK_ABOVE_VRAM_CAP":
            return (
                f"Measured peak VRAM exceeded the {self.vram_cap_gb} GB cap. "
                "Reduce GPU memory use (batch size, sequence length, or capacity)."
            )
        if self.outcome == "MEASURED_HOST_MEMORY_EXCEEDED":
            allowance = f"{self.host_memory.limit_gib} GiB" if self.host_memory else "its allowance"
            return (
                f"The candidate exceeded the bounded host-memory allowance during "
                f"preflight ({allowance}). This is a HOST (CPU) memory limit, NOT "
                f"a GPU VRAM verdict — the model's VRAM footprint was not shown to "
                f"exceed {self.vram_cap_gb} GB. Reduce host-memory-heavy preflight "
                f"behaviour: sequence handling, tracing cost, or construction "
                f"footprint. Do not reduce GPU parameter count on this basis alone."
            )
        if self.outcome == "HOST_MEMORY_ALLOCATION_FAILURE":
            return (
                "The candidate could not be allocated in host (CPU) memory during "
                "preflight. This is a HOST memory result, NOT a GPU VRAM verdict — "
                f"the model's VRAM footprint was not shown to exceed {self.vram_cap_gb} GB. "
                "Reduce host-memory-heavy preflight behaviour (sequence handling, "
                "tracing cost, construction footprint). Do not reduce GPU parameter "
                "count on this basis alone."
            )
        if self.outcome == "MEASURED_HARD_TIMEOUT":
            return (
                f"A bounded pre-flight operation ({self.phase or 'unknown phase'}) "
                "exceeded its time budget. This is an INCONCLUSIVE inspection "
                "result, not a measurement of this model, and not a reason to "
                "reduce model capacity or batch size."
            )
        if self.outcome == "SCHEMA_REJECTED":
            return (
                f"Configuration rejected by the model schema: "
                f"{self.schema_message or 'invalid configuration'}. Correct only "
                f"the invalid field ({self.schema_field or 'see message'}); this "
                f"says nothing about model capacity."
            )
        return (
            "The pre-flight measurement system failed before producing a result. "
            "This is an infrastructure fault, not a property of the candidate."
        )


def _worker_tree_rss_bytes(pgid: int) -> int:
    """Resident memory of the worker and its descendants.

    Read from /proc rather than a library so the monitor has no import
    cost and cannot itself become the memory problem.
    """
    total = 0
    try:
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                if os.getpgid(int(entry)) != pgid:
                    continue
                with open(f"/proc/{entry}/statm") as handle:
                    total += int(handle.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
            except (OSError, ProcessLookupError, PermissionError, IndexError, ValueError):
                continue
    except OSError:
        return total
    return total


def _process_group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _signal_group(pgid: int, sig: int) -> bool:
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def run_isolated_preflight(
    spec: IsolatedProbeSpec,
    *,
    deadline_seconds: float = 900.0,
    poll_seconds: float = 0.25,
    grace_seconds: float = 10.0,
    command: list[str] | None = None,
) -> IsolatedProbeResult:
    """Run one candidate's pre-flight in a bounded worker and classify it.

    The parent never imports torch on this path and never constructs the
    candidate: a limit applied after the model is already resident would
    protect nothing.
    """
    result_path = Path(spec.result_path)
    spec_path = result_path.with_suffix(".spec.json")
    log_path = result_path.with_suffix(".worker.log")
    result_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(spec.model_dump_json(indent=1), encoding="utf-8")

    argv = command or [
        sys.executable,
        "-m",
        "agent.skills.evaluate_vram_skill.preflight_worker_main",
        str(spec_path),
    ]
    limit_gib = spec.worker_memory_limit_bytes / 1024**3
    started = time.monotonic()
    log_handle = log_path.open("w", encoding="utf-8")
    try:
        process = subprocess.Popen(
            argv,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # own process group: a kill reaches descendants
        )
    except Exception as exc:
        log_handle.close()
        return IsolatedProbeResult(
            label=spec.label,
            outcome="PROBE_INFRASTRUCTURE_FAILURE",
            detail=f"could not launch the pre-flight worker: {exc!r}",
        )

    pgid = process.pid
    peak_rss = 0
    host_exceeded = False
    timed_out = False
    term_sent = kill_sent = False

    while process.poll() is None:
        elapsed = time.monotonic() - started
        rss = _worker_tree_rss_bytes(pgid)
        peak_rss = max(peak_rss, rss)

        # Belt and braces: RLIMIT_AS bounds the ADDRESS SPACE inside the
        # worker, but a tree of descendants can still grow resident memory
        # past the intended ceiling, so the parent watches the tree too.
        if rss >= spec.worker_memory_limit_bytes:
            host_exceeded = True
        if host_exceeded or elapsed >= deadline_seconds:
            timed_out = not host_exceeded
            term_sent = _signal_group(pgid, signal.SIGTERM)
            deadline = time.monotonic() + grace_seconds
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(poll_seconds)
            if process.poll() is None:
                kill_sent = _signal_group(pgid, signal.SIGKILL)
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=grace_seconds)
            break
        time.sleep(poll_seconds)

    elapsed = round(time.monotonic() - started, 3)
    log_handle.close()
    returncode = process.returncode
    exit_signal = -returncode if returncode is not None and returncode < 0 else None
    orphans = _process_group_alive(pgid)

    host_evidence = HostMemoryEvidence(
        limit_bytes=spec.worker_memory_limit_bytes,
        limit_gib=round(limit_gib, 2),
        peak_worker_rss_bytes=peak_rss,
        peak_worker_rss_gib=round(peak_rss / 1024**3, 3),
        enforcement="parent_rss_monitor" if host_exceeded else "none",
        exceeded=host_exceeded,
    )

    def _result(
        outcome: PreflightOutcome,
        detail: str,
        phase: str,
        *,
        realized_parameter_count: int | None = None,
        estimated_gb: float | None = None,
        inference_batch: int | None = None,
        schema_field: str | None = None,
        schema_message: str | None = None,
    ) -> IsolatedProbeResult:
        """Explicit keywords rather than `**dict` expansion: strict pyright
        cannot match a heterogeneous dict against these parameter types,
        and silencing that would hide real mismatches."""
        return IsolatedProbeResult(
            label=spec.label,
            outcome=outcome,
            detail=detail,
            phase=phase,
            elapsed_seconds=elapsed,
            worker_pid=process.pid,
            worker_pgid=pgid,
            exit_code=returncode,
            signal_number=exit_signal,
            orphans_remaining=orphans,
            host_memory=host_evidence,
            vram_cap_gb=spec.vram_budget_gb,
            realized_parameter_count=realized_parameter_count,
            estimated_gb=estimated_gb,
            inference_batch=inference_batch,
            schema_field=schema_field,
            schema_message=schema_message,
        )

    if host_exceeded:
        return _result(
            "MEASURED_HOST_MEMORY_EXCEEDED",
            (
                f"worker tree reached {host_evidence.peak_worker_rss_gib} GiB against "
                f"a {host_evidence.limit_gib} GiB allowance; terminated by the parent "
                f"(TERM sent={term_sent}, KILL sent={kill_sent})"
            ),
            "host_memory_monitor",
        )
    if timed_out:
        return _result(
            "MEASURED_HARD_TIMEOUT",
            (
                f"worker exceeded the {deadline_seconds:.0f}s deadline "
                f"(TERM sent={term_sent}, KILL sent={kill_sent})"
            ),
            "worker_deadline",
        )

    payload = _load_worker_result(result_path)
    if payload is None:
        # No structured result. An exit by a memory-ish signal with the
        # worker near its ceiling is host memory; anything else is our
        # machinery failing, and must not be dressed up as a measurement.
        near_limit = peak_rss >= 0.9 * spec.worker_memory_limit_bytes
        if exit_signal == signal.SIGKILL and near_limit:
            return _result(
                "MEASURED_HOST_MEMORY_EXCEEDED",
                (
                    f"worker was SIGKILLed at {host_evidence.peak_worker_rss_gib} GiB, "
                    f"within 10% of the {host_evidence.limit_gib} GiB allowance"
                ),
                "worker_exit",
            )
        return _result(
            "PROBE_INFRASTRUCTURE_FAILURE",
            (
                f"worker exited without a structured result "
                f"(exit={returncode}, signal={exit_signal}); "
                f"log tail: {_log_tail(log_path)}"
            ),
            "worker_exit",
        )

    def _int_or_none(value: object) -> int | None:
        return value if isinstance(value, int) else None

    def _float_or_none(value: object) -> float | None:
        return float(value) if isinstance(value, (int, float)) else None

    def _str_or_none(value: object) -> str | None:
        return value if isinstance(value, str) else None

    outcome = _str_or_none(payload.get("outcome")) or "PROBE_INFRASTRUCTURE_FAILURE"
    if outcome not in get_args(PreflightOutcome):
        outcome = "PROBE_INFRASTRUCTURE_FAILURE"
    return _result(
        outcome,  # type: ignore[arg-type]  - narrowed against the Literal above
        _str_or_none(payload.get("detail")) or "",
        _str_or_none(payload.get("phase")) or "complete",
        realized_parameter_count=_int_or_none(payload.get("realized_parameter_count")),
        estimated_gb=_float_or_none(payload.get("estimated_gb")),
        inference_batch=_int_or_none(payload.get("inference_batch")),
        schema_field=_str_or_none(payload.get("schema_field")),
        schema_message=_str_or_none(payload.get("schema_message")),
    )


def _load_worker_result(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _log_tail(path: Path, limit: int = 800) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()[-limit:]
    except OSError:
        return "<no log>"
