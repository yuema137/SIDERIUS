"""Run a candidate VRAM pre-flight inside an isolated, memory-bounded worker.

Why this exists, precisely. On 2026-07-31 a quadratic-attention
candidate's pre-flight grew to **60.5 GB of anonymous RSS** on a 61 GB
host and the
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
     -> worker builds, inspects, probes, writes a bounded JSON result
  -> parent samples worker-tree RSS and enforces the host-RSS budget + deadline
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

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.schemas.model_io_contract import ModelIOContract
from agent.skills.evaluate_vram_skill.probe_budgets import ProbeBudgets
from core.runtime_control.process_group import (
    process_group_alive,
    signal_group,
    tree_rss_bytes,
)
from core.subprocess_env import subprocess_env
from execute_tools.task_data_path import TaskProbeDataSpec

#: Terminal dispositions. Each names WHAT was established, so that
#: authority to reject a candidate — or to tell an agent to shrink it —
#: can be derived rather than guessed.
PreflightOutcome = Literal[
    "COMPLETED_MEASUREMENT",
    "MEASURED_CUDA_OOM",
    "MEASURED_PEAK_ABOVE_VRAM_CAP",
    "MEASURED_HARD_TIMEOUT",
    "INCONCLUSIVE_MEASUREMENT",
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
        "INCONCLUSIVE_MEASUREMENT",
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

    This remains the compatibility default, not a universal statement about
    valid task workloads. A workflow can declare a different explicit limit
    when task-valid decoded batches or model inspection have a different host
    memory footprint. The value is never inferred silently from free memory,
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


class HardwareSnapshot(BaseModel):
    """The hardware facts the worker needs, frozen by the parent.

    The parent resolves ``HardwareContext`` once and sends these values;
    the worker never discovers hardware for itself. A parent and a worker
    that discover independently can disagree about the budget, the device
    or the fingerprint, and a disagreement there is invisible — it looks
    like a measurement, not a configuration error (PR A, D-A3/D-A4).

    ``device_index`` and ``cuda_visible_devices`` are carried because
    device selection is otherwise implicit: neither the skill nor the
    worker calls ``torch.cuda.set_device``, so both rely on whichever
    device the inherited environment exposes. Inheriting is not
    asserting, and on a multi-GPU host the difference is silent.
    """

    model_config = ConfigDict(frozen=True)

    usable_cap_bytes: int = Field(gt=0)
    usable_cap_gb: float = Field(gt=0.0)
    total_memory_bytes: int = Field(gt=0)
    total_memory_gb: float = Field(gt=0.0)
    device_name: str = Field(min_length=1)
    device_available: bool
    hardware_fingerprint: str = Field(min_length=1)
    device_index: int = Field(default=0, ge=0)
    cuda_visible_devices: str | None = None


class IsolatedProbeSpec(BaseModel):
    """Everything the worker needs. Deliberately small and JSON-only.

    Serialized to a transient ``<result>.spec.json`` for the worker it
    launches. It is an IPC contract, not a persisted artifact: it appears
    in no manifest and has no reader beyond that worker.
    """

    model_config = ConfigDict(frozen=True)

    label: str = Field(min_length=1)
    model_type: str = Field(min_length=1)
    model_config_payload: dict[str, Any] = Field(default_factory=dict)
    train_config: dict[str, Any] = Field(default_factory=dict)
    loss_config: dict[str, Any] = Field(default_factory=dict)
    #: ``None`` means "no operator ceiling" — the defensive-cap mode the
    #: in-process path has always had. It does NOT mean "unset", and the
    #: worker must not invent a number for it: with ``None`` the cap comes
    #: from ``hardware.usable_cap_gb``, already resolved by the parent.
    vram_budget_gb: float | None = Field(default=None, gt=0.0)
    result_path: str
    worker_memory_limit_bytes: int = Field(gt=0)
    #: Absent only for standalone tooling that opts into discovery. In
    #: production its absence is a configuration error, never a fallback.
    hardware: HardwareSnapshot | None = None
    #: Step 05b — the run's normalized Model-I/O declaration, carried BY
    #: VALUE so the child probes the same declaration the parent bound.
    #:
    #: ``None`` is the legacy no-contract path and reproduces today's
    #: behaviour exactly; a spec written before this field existed still
    #: validates, because absence and refusal are deliberately different
    #: (the same omit-vs-broken rule the ``--model_io_json`` transport uses,
    #: ``sandbox_executor.py:1309-1314``).
    #:
    #: Inline rather than a path: this spec is already a transient JSON IPC
    #: document with no manifest and no reader beyond its worker, so an
    #: extra file would add a second lifetime to manage for no gain.
    model_io_contract: ModelIOContract | None = None
    #: Step 11 C1 (F-11-2) — the RUN-SCOPED plugin directories, carried so
    #: the worker is spawned with the same environment every other SIDERIUS
    #: worker gets. Without them the child inherited the tuner's own
    #: environ, which carries no ``SIDERIUS_PLUGIN_DIRS`` (that variable is
    #: built per-sandbox for its children), and fell back to the legacy
    #: global ``agent_generated/models/`` — the PR #184 failure shape one
    #: directory along.
    #:
    #: ``None`` is the standalone-tooling path documented on
    #: :func:`core.subprocess_env.subprocess_env`, and mirrors
    #: ``GpuMeasurementSpec.plugin_dir`` / ``.loss_dir`` exactly. It is
    #: NOT available to production: ``run_production_preflight`` requires
    #: both keyword arguments, so a production caller cannot omit them
    #: silently. A spec written before this field existed still validates.
    plugin_dir: str | None = None
    loss_dir: str | None = None
    #: A composed run's existing task-data contract, carried into the isolated
    #: worker so the loss sees one task-valid training batch. ``None`` keeps
    #: the legacy shape-and-dtype synthetic probe unchanged.
    task_probe_data: TaskProbeDataSpec | None = None
    #: Per-operation watchdog budgets selected by the workflow. The complete
    #: typed object crosses IPC so the worker never reads mutable module state.
    probe_budgets: ProbeBudgets = Field(default_factory=ProbeBudgets)

    def effective_cap_gb(self) -> float | None:
        """The cap the worker must apply: the LOWER of the operator ceiling
        and the parent's frozen defensive cap; either alone if only one is
        known; nothing to enforce if neither is.

        **V21 PR B3 Stage B — corrected from `operator else defensive`.**
        The two were treated as alternatives with operator priority, so an
        operator budget ABOVE the card silently raised the worker's ceiling
        past the physical one:

        ```text
        physical usable 25 GB, operator budget 40 GB, measured peak 30 GB
          parent  evaluate_vram_skill  cap = min(25, 40) = 25  -> VIOLATION
          worker  effective_cap_gb     cap = 40                -> allowed
        ```

        The parent names that regime `PHYSICAL VETO` (`wrapper.py:540`)
        precisely because an operator budget may only *lower* the 80%
        safety ceiling, never raise it. Under the frozen S3 semantics the
        admission threshold is the **effective** one, and the tuner already
        records it as such (`final_record["memory"]["vram_budget_gb"] =
        resource_check["limit_gb"]`). Taking the minimum makes the worker,
        the parent gate and the shared decision policy agree on one number.

        Reachable on any legal configuration where the budget exceeds
        0.80 x VRAM; not exercised by V20, which ran 12 GiB on a larger
        card. Direction of the correction is conservative — the worker can
        now only refuse *more*, never less. Recorded in the PR B design doc
        §B3.B.1 rather than changed silently.
        """
        caps = [c for c in (self.vram_budget_gb, self._defensive_cap_gb()) if c is not None]
        return min(caps) if caps else None

    def _defensive_cap_gb(self) -> float | None:
        return self.hardware.usable_cap_gb if self.hardware is not None else None

    def effective_limit_source(self) -> str:
        """Which bound actually set ``effective_cap_gb`` — named, not guessed.

        Now that the cap is a minimum, the source is whichever bound won;
        ``physical_veto_defensive_cap`` is the case the old code could not
        express, and is the one an operator most needs to see.
        """
        operator = self.vram_budget_gb
        defensive = self._defensive_cap_gb()
        if operator is None and defensive is None:
            return "unbounded_no_snapshot"
        if operator is None:
            return "hardware_snapshot_defensive_cap"
        if defensive is None:
            return "operator_vram_budget"
        if defensive < operator:
            return "physical_veto_defensive_cap"
        return "operator_vram_budget"


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

    # ── fields carried from the worker for the legacy contract ──────────
    #
    # A5 (2026-08-01) found these silently dropped. The worker emitted
    # them, the adapter forwarded them, and this model in between did
    # not declare them — so Pydantic discarded them before the adapter
    # ever ran. ``memory.vram_budget_gb`` landed as null where every
    # pre-PR-A record held 12.0.
    #
    # The near-neighbour ``vram_cap_gb`` above is the cap the PARENT
    # resolved and sent; ``limit_gb`` is the limit the WORKER actually
    # applied. They normally agree, and the similar name is the likely
    # reason the omission went unnoticed. Keep both: a divergence is a
    # real signal, and collapsing them would hide it.
    limit_gb: float | None = Field(default=None, gt=0.0)
    dominant_phase: str | None = None
    #: Agent-facing text, FORWARDED from the skill, never regenerated
    #: here — a second generator would drift where nobody reads it.
    verdict: str = ""
    suggestion: str = ""
    #: D-A2 bounded diagnostics. Without these the whole bounded-rich-
    #: field mechanism was inert: it was built and tested in the worker,
    #: then discarded one layer later.
    #:
    #: ``str`` is a real member of each union, not sloppiness: when a
    #: field will not fit the 8 KiB budget the worker replaces it with
    #: ``"[dropped: exceeded the rich-field budget]"`` so its absence is
    #: explicit rather than silent. Narrowing these to list/dict would
    #: turn that deliberate marker back into a silent ``None``.
    violations: list[Any] | str | None = None
    offending_config: dict[str, Any] | str | None = None
    memory_killer: dict[str, Any] | str | None = None
    #: Set by the worker when the rich fields did not fit the byte
    #: budget. ``truncated`` without the count tells a reader that
    #: something was dropped but not how much, so both travel together:
    #: the worker emits the count for every truncation mode.
    truncated: bool = False
    violations_omitted_count: int | None = Field(default=None, ge=0)

    #: Provenance for a timeout claim: which operation, which budget, and
    #: how long it actually ran. Present so "this timed out" is checkable
    #: rather than asserted.
    timeout_operation: str | None = None
    timeout_budget_seconds: float | None = Field(default=None, gt=0.0)
    timeout_elapsed_seconds: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def _a_timeout_must_have_reached_its_deadline(self) -> IsolatedProbeResult:
        """A result faster than its own budget is not a timeout.

        On 2026-07-31 a 65.6 s inspection was filed as MEASURED_HARD_TIMEOUT
        against a 600 s deadline, because every "inconclusive" status was
        mapped to the timeout outcome. The schema now refuses that claim.
        """
        if self.outcome != "MEASURED_HARD_TIMEOUT":
            return self
        budget = self.timeout_budget_seconds
        elapsed = self.timeout_elapsed_seconds
        if budget is not None and elapsed is not None and elapsed < budget:
            raise ValueError(
                f"MEASURED_HARD_TIMEOUT claims a deadline was reached, but the "
                f"operation ran {elapsed}s against a {budget}s budget"
            )
        return self

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
        if self.outcome == "INCONCLUSIVE_MEASUREMENT":
            return (
                "The preflight inspection was inconclusive and produced no measured "
                "capacity result. Do not infer that the candidate is too large, too "
                "slow, or infeasible from this event. No configured deadline elapsed "
                "and no resource limit was reached; the inspection simply did not "
                "establish an authoritative measurement."
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


# Supervision primitives moved to `core.runtime_control.process_group`
# (V20 PR C2): this module and `probe_subprocess.py` had grown identical
# copies, and C2's measurement runner needed the same three. Four places to
# fix one kill-path bug in is worse than one import. Behaviour unchanged --
# the bodies moved verbatim. The local names are kept because they are what
# this module's own tests and readers refer to.
_worker_tree_rss_bytes = tree_rss_bytes
_process_group_alive = process_group_alive
_signal_group = signal_group


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
        from core.local_code.child import prepare_child

        invocation = prepare_child(
            argv, subprocess_env(plugin_dir=spec.plugin_dir, loss_dir=spec.loss_dir)
        )
        process = subprocess.Popen(
            invocation.argv,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # own process group: a kill reaches descendants
            # Step 11 C1 (F-11-2). Spawning with no `env=` is what made
            # every agent-generated candidate CONFIG_REJECTED in V20
            # attempt 2 for the measurement worker; this spawner had the
            # same omission. `subprocess_env` never mutates `os.environ`,
            # and it also supplies the PYTHONPATH extension the child was
            # losing regardless of whether the plugin dirs are known.
            env=invocation.env,
        )
    except Exception as exc:
        log_handle.close()
        from core.local_code.failure import raise_if_code_package_failure

        raise_if_code_package_failure(exc)
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

        # The worker may create descendants, so enforce the host-memory budget
        # against the complete process tree from the parent.
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
    invocation.check(returncode)
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
        timeout_operation: str | None = None,
        timeout_budget_seconds: float | None = None,
        timeout_elapsed_seconds: float | None = None,
        limit_gb: float | None = None,
        dominant_phase: str | None = None,
        verdict: str = "",
        suggestion: str = "",
        violations: list[Any] | str | None = None,
        offending_config: dict[str, Any] | str | None = None,
        memory_killer: dict[str, Any] | str | None = None,
        truncated: bool = False,
        violations_omitted_count: int | None = None,
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
            vram_cap_gb=spec.effective_cap_gb(),
            realized_parameter_count=realized_parameter_count,
            estimated_gb=estimated_gb,
            inference_batch=inference_batch,
            schema_field=schema_field,
            schema_message=schema_message,
            timeout_operation=timeout_operation,
            timeout_budget_seconds=timeout_budget_seconds,
            timeout_elapsed_seconds=timeout_elapsed_seconds,
            limit_gb=limit_gb,
            dominant_phase=dominant_phase,
            verdict=verdict,
            suggestion=suggestion,
            violations=violations,
            offending_config=offending_config,
            memory_killer=memory_killer,
            truncated=truncated,
            violations_omitted_count=violations_omitted_count,
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
            timeout_operation="worker_deadline",
            timeout_budget_seconds=deadline_seconds,
            timeout_elapsed_seconds=elapsed,
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

    def _list_or_none(value: object) -> list[Any] | str | None:
        """A dropped list arrives as the worker's marker string; keep it."""
        return value if isinstance(value, (list, str)) else None

    def _dict_or_none(value: object) -> dict[str, Any] | str | None:
        return value if isinstance(value, (dict, str)) else None

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
        timeout_operation=_str_or_none(payload.get("timeout_operation")),
        timeout_budget_seconds=_float_or_none(payload.get("timeout_budget_seconds")),
        timeout_elapsed_seconds=_float_or_none(payload.get("timeout_elapsed_seconds")),
        # A5 repair — carried explicitly, in the same style as the fields
        # above. The schema-diff guardrail fails if a worker field is
        # added without appearing here.
        limit_gb=_float_or_none(payload.get("limit_gb")),
        dominant_phase=_str_or_none(payload.get("dominant_phase")),
        verdict=_str_or_none(payload.get("verdict")) or "",
        suggestion=_str_or_none(payload.get("suggestion")) or "",
        violations=_list_or_none(payload.get("violations")),
        offending_config=_dict_or_none(payload.get("offending_config")),
        memory_killer=_dict_or_none(payload.get("memory_killer")),
        truncated=payload.get("truncated") is True,
        violations_omitted_count=_int_or_none(payload.get("violations_omitted_count")),
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
