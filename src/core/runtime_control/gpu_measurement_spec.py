"""The parent<->worker contract for one isolated pre-phase measurement.

V20 PR C2 / C2-2.

Two processes have to agree about what is being measured and what came
back, and they can only exchange JSON. This module is that agreement. It
holds no execution logic: `gpu_measurement_phases` runs the phases and
`gpu_measurement_worker_main` is the process that hosts them.

WHY ONE WORKER MEASURES ONE PHASE. Production runs training and inference
in **separate subprocesses**, each of which constructs the model and then
does its own work. So the memory a training subprocess needs is the peak
over *its* whole life, and the same for inference -- and the two are not
the same number: B-G0 measured one PUNet candidate at 1,476 MiB training
against 2,716 MiB inference, 1.8x apart on one card in one run.

Measuring both inside one process would mean running inference with the
gradients and the optimizer's two Adam moments still resident, which
describes no process production ever launches. So `GpuMeasurementSpec`
carries exactly ONE target phase, taken from `CandidateMeasurementRequest`,
and the parent launches one worker per phase it needs. Phase separation is
then a property of the process topology rather than of bookkeeping that
could be got wrong.

`setup` is always measured alongside the target phase, because the target
phase's process also had to build the model. It is reported separately and
is deliberately not admissible on its own (`ADMISSIBLE_PHASES`).

TIMESTAMPS ARE `time.time()`, NOT `time.monotonic()`. The parent samples
the driver while the worker runs and attributes each sample to a phase by
its window. Monotonic clocks share no epoch across processes, so they
cannot be compared; wall clock can.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.schemas.model_io_contract import ModelIOContract
from core.runtime_control.gpu_measurement_identity import RealizedCandidateIdentity
from core.runtime_control.gpu_requirement import (
    CandidateMeasurementRequest,
    MeasuredPhase,
)
from execute_tools.dataset_config import DatasetProfile
from execute_tools.task_data_path import TaskProbeDataSpec

#: How the worker as a whole ended. Distinct from a *phase* status: a
#: worker can complete while the phase inside it OOMed, and the parent
#: needs both facts.
WorkerStatus = Literal[
    "COMPLETED",
    "CUDA_OOM",
    "DEADLINE_EXCEEDED",
    "DEVICE_UNAVAILABLE",
    "DEVICE_MISMATCH",
    "CONFIG_REJECTED",
    "WORKER_FAILURE",
]

#: How one phase ended. `NOT_REACHED` is not a failure of that phase -- it
#: says an earlier phase ended the run, which is a different fact from
#: "ran and produced nothing".
PhaseStatus = Literal["COMPLETED", "CUDA_OOM", "FAILED", "NOT_REACHED"]

#: Why a phase stopped repeating its workload. Recorded rather than
#: inferred: "we saw enough" and "we ran out of time" produce the same
#: elapsed figure and mean opposite things.
PhaseCompletion = Literal[
    "single_pass",
    "sample_target_reached",
    "duration_bound",
    "deadline",
    "failed",
]


class GpuMeasurementSpec(BaseModel):
    """Parent -> worker. Written to a transient JSON file, never argv.

    Embeds `CandidateMeasurementRequest` rather than restating its fields:
    the identity the worker measures under and the identity the authority
    contract checks against must be the *same object*, or the two can
    drift and the drift looks like a measurement.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str = Field(min_length=1)
    request: CandidateMeasurementRequest

    #: The candidate exactly as production would construct it. These are
    #: the same three payloads the trainer receives.
    model_config_payload: dict[str, Any] = Field(default_factory=dict)
    train_config: dict[str, Any] = Field(default_factory=dict)
    loss_config: dict[str, Any] = Field(default_factory=dict)

    #: The torch device string. Whatever the caller asked for is what runs;
    #: there is no negotiation and no fallback. A CUDA request on a host
    #: without CUDA is `DEVICE_UNAVAILABLE`, never a CPU measurement
    #: wearing a GPU requirement's provenance.
    device: str = Field(default="cuda", min_length=1)

    #: Resolved dataset root. Required: the worker must not reach for a
    #: task-specific default, and a synthetic batch would measure a
    #: candidate nobody is going to run (F-1a).
    data_dir: str | None = None

    #: The resolved dataset declaration the probe batch is built from
    #: (Step 07 / PR 07c C2).
    #:
    #: The worker is a CLEAN subprocess, so the parent's `_ACTIVE_PROFILE`
    #: context variable does not cross the boundary and
    #: `resolve_dataset_profile()` inside the worker would ALWAYS answer the
    #: shipped TIDMAD profile — a task assumption expressed by omission,
    #: which is precisely the defect class 07c removes. `resolve_dataset_
    #: profile`'s own contract says subprocess entry points load the profile
    #: explicitly and pass it down; this field is that transport, and the
    #: tuner already holds the object (`RunBindings.run_profile`).
    #:
    #: Optional so a spec serialized before the transport existed still
    #: validates and still runs; `None` means Regime-A at the call site.
    dataset_profile: DatasetProfile | None = None

    #: A composed task's exact training scope and sampling request. When
    #: present, the worker materializes its batch through TaskDataPath instead
    #: of the legacy physical-array loader. This is the same typed projection
    #: used by the isolated VRAM preflight.
    task_probe_data: TaskProbeDataSpec | None = None

    #: The task's Model-I/O contract, which decides the dtype the model is
    #: handed at the measurement boundary (Step 07 / PR 07c C3).
    #:
    #: Same reason as `dataset_profile`: `resolve_input_dtype` needs the
    #: contract as an ARGUMENT, and the worker has no other way to see the one
    #: this run is bound to. Without it the worker resolves Regime-A — the
    #: model's own declaration, else the site preference — which is exactly
    #: today's behaviour, so `None` is parity rather than a degradation.
    #:
    #: The tuner already holds the object (`RunBindings.run_model_io`); a task
    #: declaring no `model_io` legitimately supplies `None`.
    model_io_contract: ModelIOContract | None = None

    #: Run-scoped plugin directories, transported to the worker's process.
    #:
    #: V20 attempt 2 died here. The worker is a CLEAN subprocess: the
    #: parent's `MODEL_REGISTRY` does not cross the boundary, so without
    #: these it cannot resolve an agent-generated model and returns
    #: `CONFIG_REJECTED` — which fail-closes every formal promotion. The
    #: training and inference sandboxes were already receiving them; only
    #: this hop was missing.
    #:
    #: `None` keeps the legacy global-directory fallback, so built-in
    #: models and callers outside the sandbox flow are unaffected.
    plugin_dir: str | None = None
    loss_dir: str | None = None

    #: Enough steps for the allocator to reach steady state. The optimizer
    #: allocates its moments on the FIRST step, so a single step under-reads
    #: every Adam-family candidate; from step 2 the footprint is stable.
    #: Four is two steady steps, which is what makes the peak observable
    #: rather than inferred.
    training_steps: int = Field(default=4, gt=0)
    inference_batches: int = Field(default=3, gt=0)
    #: The batch the INFERENCE phase runs at, resolved by the PARENT via
    #: `resolve_inference_batch` — the probe-derived hint when one exists,
    #: else the `inference_batch_for` table, exactly as
    #: `execute_inference` resolves it (V21 PR G G3). Required for an
    #: inference measurement.
    #:
    #: Formal inference runs punet at 25 while training runs at 1. Measuring
    #: the inference phase at the TRAINING batch reported 1050 MiB for a
    #: phase that really held 3642 MiB -- a 3.47x under-read that would have
    #: reached admission (Gate attempt 6).
    inference_batch_size: int | None = Field(default=None, gt=0)

    # ── short-phase observability (D-C2-13) ──────────────────────────────
    #: A phase shorter than the sampling cadence yields ZERO in-phase
    #: samples and is unmeasurable -- Gate 2 Lite-A c7 ran inference in
    #: 0.138 s against a 0.25 s cadence. So a phase repeats its EXACT
    #: workload until the observation window is long enough for the
    #: required samples to land.
    #:
    #: Repetition is measurement protocol, not candidate identity: the
    #: model, batch shape, dtype, data and semantics are unchanged, and it
    #: happens only inside the disposable measurement worker.
    min_authoritative_samples: int = Field(default=3, gt=0)
    #: The ONLY normal bound on that repetition, besides the global
    #: deadline. There is deliberately no `max_phase_repetitions`:
    #: Gate 2 Lite-A attempt 3 hit a 40-repetition ceiling after 120
    #: inference batches in 0.344 s and still had one sample, because a
    #: repetition COUNT cannot express a duration target when the
    #: per-repetition cost is unknown. Replacing 40 with a larger guess
    #: would repeat the mistake; the phase now ends when the parent has
    #: actually SEEN enough, bounded by time.
    max_phase_seconds: float = Field(default=60.0, gt=0.0)
    #: The parent touches this once it has counted
    #: `min_authoritative_samples` valid in-phase samples. The worker
    #: leaves the phase when it appears.
    phase_complete_path: str | None = None
    #: The parent touches this once it has taken a real sample. The worker
    #: waits for it before opening a timed phase, so a phase can never be
    #: measured before anything is watching.
    sampler_ready_path: str | None = None
    #: Bound on that wait. Exceeding it is reported, never ignored.
    sampler_ready_timeout_seconds: float = Field(default=30.0, gt=0.0)

    result_path: str = Field(min_length=1)
    #: Append-only NDJSON phase journal, flushed as each boundary is
    #: crossed. It survives a crash or a kill, so the parent can say WHICH
    #: phase was in flight when the worker died. The final report is the
    #: authority on windows when it exists; the journal is what remains
    #: when it does not.
    journal_path: str = Field(min_length=1)

    #: Host-memory ceiling for this worker's tree, enforced by the parent.
    #: Same instrument as PR A: address space is not resident memory.
    worker_memory_limit_bytes: int = Field(gt=0)

    #: A budget the worker checks BETWEEN steps, so it can stop cleanly and
    #: report the partial evidence it did gather.
    #:
    #: It is not the timeout. The hard deadline belongs to the parent,
    #: because a worker wedged inside a CUDA call runs no Python and can
    #: enforce nothing on itself -- which is the case a deadline exists
    #: for. This budget is set BELOW the parent's so the clean stop
    #: usually wins the race; when it does not, the parent kills the
    #: process group and classifies the timeout from its own elapsed time.
    #: `None` means the parent's hard deadline is the only bound.
    soft_deadline_seconds: float | None = Field(default=None, gt=0.0)

    @property
    def phase(self) -> MeasuredPhase:
        return self.request.phase

    @model_validator(mode="after")
    def _the_target_phase_must_be_work(self) -> GpuMeasurementSpec:
        """`setup` is measured alongside every phase and is never the
        target on its own -- a spec asking only for setup would produce a
        report that can never be admitted, hours after it was launched."""
        if self.request.phase == "setup":
            raise ValueError(
                "the target phase may not be 'setup': setup is measured "
                "alongside training or inference, never requested alone"
            )
        return self

    @model_validator(mode="after")
    def _an_inference_measurement_needs_its_batch(self) -> GpuMeasurementSpec:
        """Required, not defaulted. Falling back to the training batch is
        precisely the substitution that produced the 3.47x under-read."""
        if self.request.phase == "inference" and self.inference_batch_size is None:
            raise ValueError(
                "an inference-phase measurement requires inference_batch_size, "
                "resolved via resolve_inference_batch (probed hint when "
                "available, else the registry table); the training batch is "
                "not the inference workload"
            )
        return self

    @model_validator(mode="after")
    def _the_soft_budget_must_sit_below_the_hard_one(self) -> GpuMeasurementSpec:
        """Enforced, not merely documented. A soft budget at or above the
        parent's deadline never fires, so the worker would always be killed
        instead of reporting -- the partial evidence would be lost every
        time, and nothing would say so."""
        soft = self.soft_deadline_seconds
        if soft is not None and soft >= self.request.deadline_seconds:
            raise ValueError(
                f"soft_deadline_seconds={soft} is not below the parent's hard "
                f"deadline of {self.request.deadline_seconds}s; it would never "
                "fire and the worker could never stop cleanly"
            )
        return self

    @model_validator(mode="after")
    def _probe_and_identity_must_agree(self) -> GpuMeasurementSpec:
        """Do not let the worker measure one shape under another identity."""
        expected = (
            self.task_probe_data.segmentation_applicability
            if self.task_probe_data is not None
            else "temporal"
        )
        actual = self.request.planned_identity.segmentation_applicability
        if actual != expected:
            raise ValueError(
                "task_probe_data and planned measurement identity disagree: "
                f"task probe implies {expected!r}, identity says {actual!r}"
            )
        return self


class RealismEvidence(BaseModel):
    """Proof that the measurement ran the real thing.

    A measurement of a forward pass alone would be smaller than the truth
    in the OOM direction -- no gradients, no optimizer moments, no cuDNN
    backward workspaces. PR A's structural probe is explicit that it never
    calls `backward()` (`structural_probe.py:177`, and `:201` raises if it
    does), which is exactly why C2 could not reuse it.

    So the worker COUNTS what it did and reports it, and the parent can
    refuse a "measurement" that never trained. `parameter_update_verified`
    is the strongest of these: an optimizer step that changes no parameter
    means the graph was detached somewhere and the backward was decorative.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    forward_calls: int = Field(default=0, ge=0)
    backward_calls: int = Field(default=0, ge=0)
    optimizer_steps: int = Field(default=0, ge=0)
    inference_batches: int = Field(default=0, ge=0)

    #: Largest absolute change in the watched trainable parameter across
    #: the training phase. `None` when training did not run.
    parameter_update_max_abs_delta: float | None = Field(default=None, ge=0.0)
    #: True only when a watched parameter actually moved.
    parameter_update_verified: bool = False
    #: True when every inference output was built outside autograd. `None`
    #: when inference did not run.
    inference_grad_free: bool | None = None

    trainable_parameter_count: int | None = Field(default=None, ge=0)
    #: How many times the phase held a real post-forward peak state open so
    #: the parent could sample it (D-C2-18). Holding allocates nothing;
    #: repeating the forward grew the allocator pool and inflated the
    #: inference figure by 34%.
    peak_state_holds: int = Field(default=0, ge=0)
    #: True when the parent confirmed it had seen enough during a hold.
    peak_state_observed: bool = False
    #: Inference outputs explicitly released before the following forward.
    #: Equal to `inference_batches` when the lifecycle is correct. A
    #: shortfall means an output survived into the next forward, leaving two
    #: full outputs resident -- the state that grew the allocator pool to
    #: 4266 MiB and the driver figure to 4870 MiB against a real 3434, and
    #: which went unseen only because the parent stops sampling once its
    #: hold is satisfied.
    outputs_released: int = Field(default=0, ge=0)
    #: Realized parameter count from the instantiated module -- never the
    #: LLM's estimate (F-1b).
    parameter_count: int | None = Field(default=None, ge=0)


class PhaseExecutionReport(BaseModel):
    """One phase's window and what the in-process allocator saw.

    The allocator figures here are **diagnostics**. They are per-process
    and allocator-visible: they exclude the CUDA context, workspaces
    outside the caching allocator, reserved-but-unallocated blocks, and
    anything held by a child process. The authority comes from the
    parent's driver-visible tree sampling over this window.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    phase: MeasuredPhase
    status: PhaseStatus
    #: Wall-clock window, `time.time()`. The parent partitions its samples
    #: with these, so they must be comparable across processes.
    started_at: float = Field(ge=0.0)
    ended_at: float = Field(ge=0.0)
    elapsed_seconds: float = Field(ge=0.0)

    allocator_peak_mib: int | None = Field(default=None, ge=0)
    allocator_reserved_peak_mib: int | None = Field(default=None, ge=0)

    #: What the phase actually completed, so a short phase is visible as
    #: short rather than being read as a full one.
    units_executed: int = Field(default=0, ge=0)
    units_requested: int = Field(default=0, ge=0)

    #: How many times the exact workload was repeated to make the phase
    #: observable (D-C2-13). 1 means it was long enough as-is.
    repetitions: int = Field(default=1, ge=0)
    #: How many valid in-phase samples the parent required.
    required_samples: int = Field(default=0, ge=0)
    #: Why the phase stopped repeating. `sample_target_reached` is the
    #: healthy path; the rest are bounds, and a bound with too few samples
    #: is INCONCLUSIVE rather than a smaller requirement.
    completion_reason: PhaseCompletion = "single_pass"
    #: The ceiling that applied.
    max_phase_seconds: float | None = Field(default=None, gt=0.0)
    #: True when a duration or deadline bound stopped the extension.
    observation_bound_reached: bool = False
    #: Whether the parent's sampler was confirmed active before the phase
    #: opened. False means the wait timed out -- reported, never ignored.
    sampler_ready: bool = True
    #: When that confirmation arrived, so the handshake is auditable.
    sampler_ready_at: float | None = Field(default=None, ge=0.0)
    detail: str = ""

    @model_validator(mode="after")
    def _a_window_may_not_run_backwards(self) -> PhaseExecutionReport:
        if self.ended_at < self.started_at:
            raise ValueError(
                f"phase {self.phase!r} ended at {self.ended_at} before it "
                f"started at {self.started_at}; the parent partitions driver "
                "samples with this window and an inverted one would silently "
                "attribute nothing"
            )
        return self


class WorkerMeasurementReport(BaseModel):
    """Worker -> parent. Bounded metadata only; nothing large crosses back.

    The request is echoed verbatim so the parent can check that the report
    answers the question it asked. A report about a different candidate is
    not a weaker measurement, it is a different one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str = Field(min_length=1)
    request: CandidateMeasurementRequest
    status: WorkerStatus

    device: str = Field(min_length=1)
    #: The device the worker actually ran on, as the driver named it.
    #: `None` on a non-CUDA device or when it could not be read -- and a
    #: `None` here can never satisfy the authority contract's UUID match,
    #: so a CPU run cannot become a GPU requirement.
    observed_device_uuid: str | None = None
    device_name: str | None = None
    worker_pid: int | None = Field(default=None, gt=0)

    phases: tuple[PhaseExecutionReport, ...] = ()
    realism: RealismEvidence = Field(default_factory=RealismEvidence)
    #: What the worker ACTUALLY constructed, recomputed from the module and
    #: hashed by C1's canonical builder. `None` when construction never got
    #: far enough -- which the parent reads as an unverified subject, not as
    #: a smaller requirement (D-C2-7).
    realized_identity: RealizedCandidateIdentity | None = None
    #: The request nonce, echoed. A stale or misrouted result cannot then be
    #: read as this request's answer.
    request_id: str = ""
    detail: str = ""

    def phase_report(self, phase: MeasuredPhase) -> PhaseExecutionReport | None:
        return next((p for p in self.phases if p.phase == phase), None)

    @model_validator(mode="after")
    def _a_completed_worker_must_have_run_its_target_phase(
        self,
    ) -> WorkerMeasurementReport:
        """`COMPLETED` with the target phase missing or unreached is the
        silent-success shape: it reads as a finished measurement and
        contains no measurement of the thing that was asked for."""
        if self.status != "COMPLETED":
            return self
        target = self.phase_report(self.request.phase)
        if target is None or target.status != "COMPLETED":
            raise ValueError(
                f"worker status COMPLETED but the target phase "
                f"{self.request.phase!r} is "
                f"{'absent' if target is None else target.status}; a completed "
                "worker that did not complete its phase is not a measurement"
            )
        return self
