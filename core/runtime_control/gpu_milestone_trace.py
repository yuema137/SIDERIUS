"""Validation-only lifecycle milestones for one GPU process.

V20 PR C2. **Not production behaviour.** Nothing here runs unless
`SIDERIUS_C2_INFERENCE_MILESTONE_TRACE` is set, and normal production
never sets it.

WHY THIS EXISTS -- and what it already answered. The corrected pre-phase
inference measurement reported **3434 MiB** where formal inference really
held **3642 MiB**: a fixed **208 MiB (5.7 %)** under-read, reproduced with
zero spread across three alternating runs. An under-read is on the wrong
side, because it opens a deterministic false-admission band.

**That investigation is CLOSED. Cause verified**, by comparing the two
processes at the same points in their lifecycles rather than at their final
peaks -- see `docs/design/v20_priorities/pr_c_measured_evidence_admission.md`
"Lifecycle audit of the 208 MiB gap -- RESOLVED, cause verified". The two
sides are identical through `after_model_to_device` and diverge only in
*reserved* at `after_checkpoint_load`: `load_state_dict(torch.load(...))`
materialises a second full parameter set on the device, `allocated` returns
to its previous value, and the caching allocator retains the freed segments
as reserved -- which is what driver-visible memory counts. The arithmetic
closes with no residual. The same instrument separately found that the
probe's loop binds two output tensors at once, so its reported figure was
right only by accident.

This module is therefore no longer an open investigation. It remains as a
standing, opt-in instrument for the next question of the same shape, and
the tests that guard it are scoped accordingly: they assert that it stays
inert, that it never perturbs what it measures, and that its production
call sites keep their place -- not the details of its own record schema,
which Pydantic declares.

**No correction factor is authorised, and this module computes none.** It
observes; it does not adjust. A systematic difference that survives
lifecycle equivalence is a finding to report, not a number to subtract.

ONE MEMORY POLICY, NOT TWO. Every figure here comes from
`gpu_accounting.sample`, the same primitive the parent-side production
sampler (`gpu_measurement_sampler`) polls, with the same ownership rule
(process *ancestry* from a root PID) and the same refusal to read a failed
query as zero. A second definition of "driver-visible" is exactly how a
measurement and the gate that consumes it come to disagree invisibly, so
this module defines nothing of its own.

WHAT A MILESTONE IS. A named point in a process's lifecycle at which the
driver's view, the allocator's view, and the live-object state are all
recorded together. Two kinds:

* **once-per-process** -- start, imports, CUDA init, model construction,
  model transfer, exit. Recorded at most once; a second attempt is a
  misuse error, because two records under one name make the comparison
  ambiguous about which one to align.
* **per-batch** -- input transfer, post-forward hold, CPU transfer,
  cleanup. These genuinely recur, so they carry `batch_index` and cycle.
  Bounded by `max_traced_batches` so a full-file inference cannot emit
  thousands of driver queries, and the bound is *recorded* rather than
  applied silently.

MILESTONE 7 IS THE LOAD-BEARING ONE. It must be taken after the forward
has completed **and synchronized**, while the output is still resident on
the GPU, and **before** any CPU transfer, argmax, deletion or cleanup. A
record taken after `.cpu()` describes a different state and would compare
two different things while looking identical. CUDA is asynchronous: without
the synchronize, the sample can land while kernels are still queued.

WHAT IT MUST NOT DO. It must not extend any object's lifetime to inflate a
reading, run an extra forward, change batch count, alter model loading, or
change output handling or cleanup. It observes the lifecycle; it does not
redesign it.

FAILURE IS INFRASTRUCTURE, NOT SCIENCE. An unwritable trace path raises
`MilestoneTraceUnavailable` at construction -- before any measurement -- so
it can never be mistaken for a property of the candidate. Raising is
reserved for that and for misuse; an ordinary unavailable driver query is a
*value* (`telemetry_available=False`), consistent with this PR's rule that
expected outcomes are values and never exceptions.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.layout import checkout_root, require_checkout
from core.runtime_control.gpu_accounting import (
    DeviceIdentity,
    ProcessOccupancy,
    device_identity_from_hardware,
)
from core.runtime_control.gpu_accounting import sample as sample_device

#: THE environment variable. Its value is a JSON channel description, not a
#: boolean and not a bare flag -- a trace has to say where it writes, which
#: device it is about and which run it belongs to, or the artifact cannot be
#: compared with anything. Production never sets this.
TRACE_ENV_VAR = "SIDERIUS_C2_INFERENCE_MILESTONE_TRACE"

#: Recorded at most once each, in this order.
#:
#: `after_checkpoint_load` is an ADDITION to the ten milestones the audit
#: plan named, and it is deliberate. The plan's milestone 4 reads "after
#: model construction **or** checkpoint loading" -- but formal inference
#: does BOTH, in the order construct -> transfer -> `load_state_dict`
#: (`inference_single.py:281,289`), while the pre-phase worker constructs
#: from the live registry and loads no checkpoint at all. Folding the two
#: into one name would hide the single step the two paths do not share,
#: which is a prime suspect for the 208 MiB. The probe simply never records
#: it, and that absence is itself evidence rather than a gap.
ONCE_MILESTONES: tuple[str, ...] = (
    "process_start",
    "after_imports",
    "after_cuda_init",
    "after_model_construction",
    "after_model_to_device",
    "after_checkpoint_load",
    "before_exit",
)

#: Recorded once per traced batch, in this order, cycling.
PER_BATCH_MILESTONES: tuple[str, ...] = (
    "after_input_to_device",
    "after_forward_output_resident",
    "after_output_to_cpu",
    "after_output_cleanup",
)

#: The full lifecycle, in the order a process passes through it. The
#: per-batch group sits between model transfer and exit.
MILESTONE_SEQUENCE: tuple[str, ...] = (
    "process_start",
    "after_imports",
    "after_cuda_init",
    "after_model_construction",
    "after_model_to_device",
    "after_checkpoint_load",
    *PER_BATCH_MILESTONES,
    "before_exit",
)

#: The one milestone whose *placement* is the whole point. Named so a test
#: can assert against the constant rather than a repeated string literal.
POST_FORWARD_MILESTONE = "after_forward_output_resident"

#: Which process a record came from. Both sides write the same schema into
#: the same file; this is what tells them apart.
TraceSide = Literal["prephase_inference", "formal_inference"]

_MIB = 1024 * 1024

#: Bounds the `git rev-parse` used to stamp the SHA. Validation-only path,
#: but an unresponsive git must not stall an inference process.
_GIT_TIMEOUT_S = 5.0


class MilestoneTraceUnavailable(RuntimeError):
    """The trace channel itself is broken.

    Deliberately distinct from every measurement outcome. It means the
    validation infrastructure could not be set up -- an unwritable path, an
    unparsable channel -- and it must never be read as evidence about the
    candidate or the GPU.
    """


class MilestoneTraceMisuse(RuntimeError):
    """A milestone was recorded twice, or out of order.

    A fail-closed guard, not a control-flow channel. Two records under one
    name leave the comparison unable to say which one to align, and a
    milestone taken out of order describes a state other than the one its
    name claims -- which is precisely the defect that would make milestone 7
    meaningless.
    """


class MilestoneTraceChannel(BaseModel):
    """Where a trace writes and what it is about.

    Parsed from `TRACE_ENV_VAR` through Pydantic rather than read as a bare
    path: a trace missing its device UUID or run id produces records that
    cannot be compared, and finding that out after the GPU run is finding
    out too late.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Explicit artifact path. Appended to as NDJSON, one record per line.
    path: str = Field(min_length=1)
    #: The card every record is about. Supplied by validation
    #: infrastructure, so milestones taken before CUDA initialization can
    #: still be attributed to a device.
    device_uuid: str = Field(min_length=1)
    #: Ties both sides' records to one audit.
    run_id: str = Field(min_length=1)
    #: The driver index, when the validation infrastructure knows it.
    physical_index: int = Field(default=0, ge=0)
    #: How many batches emit the per-batch group. Bounded so a full-file
    #: inference cannot emit thousands of driver queries; the bound is
    #: recorded on every per-batch record rather than applied silently.
    max_traced_batches: int = Field(default=2, gt=0)

    def device_identity(self) -> DeviceIdentity:
        """The channel's device, translated by THE adapter.

        Deliberately routed through `device_identity_from_hardware` rather
        than calling `DeviceIdentity(...)` here. A second construction site
        is a second identity schema, and a guardrail
        (`test_hardware_device_identity.py::test_it_is_the_only_translation_point`)
        enforces that there is exactly one -- it has already caught one
        rival constructor during this PR, and it caught this one too.

        The channel IS a discovered hardware record: validation
        infrastructure supplies the UUID and the driver index explicitly,
        which is precisely what the adapter refuses to guess.
        """
        record = SimpleNamespace(
            active_device_uuid=self.device_uuid,
            devices=(
                SimpleNamespace(
                    uuid=self.device_uuid,
                    physical_index=self.physical_index,
                    logical_index=None,
                ),
            ),
            cuda_visible_devices=os.environ.get("CUDA_VISIBLE_DEVICES"),
        )
        identity = device_identity_from_hardware(record)
        if identity is None:  # pragma: no cover - the channel requires a UUID
            raise MilestoneTraceUnavailable(
                f"the channel's device_uuid {self.device_uuid!r} did not translate "
                "into a device identity"
            )
        return identity


class MilestoneRecord(BaseModel):
    """One lifecycle point, fully described.

    Everything needed to align this record with the other side's, and to
    tell a real reading from an absent one, travels in the record itself. A
    figure whose context lives somewhere else stops being auditable the
    moment the two are separated.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # ── when and where in the sequence ────────────────────────────────
    at: float = Field(ge=0.0)
    monotonic_at: float
    sequence: int = Field(ge=0)
    side: TraceSide
    phase: str = Field(min_length=1)
    milestone: str = Field(min_length=1)
    #: `None` for a once-per-process milestone.
    batch_index: int | None = Field(default=None, ge=0)
    max_traced_batches: int | None = Field(default=None, gt=0)

    # ── the driver's view, via the production sampler ─────────────────
    telemetry_available: bool
    #: Candidate-owned process-tree total. `None` when the query failed --
    #: never 0. A gap is not a zero.
    tree_total_mib: int | None = Field(default=None, ge=0)
    own_processes: tuple[ProcessOccupancy, ...] = ()
    device_used_mib: int | None = Field(default=None, ge=0)
    other_mib: int | None = Field(default=None, ge=0)

    # ── the allocator's view (diagnostic only, never authority) ────────
    allocator_allocated_mib: int | None = Field(default=None, ge=0)
    allocator_reserved_mib: int | None = Field(default=None, ge=0)
    cuda_initialized: bool = False
    cuda_synchronized: bool = False

    # ── what was live at this instant ─────────────────────────────────
    input_shape: tuple[int, ...] | None = None
    input_dtype: str | None = None
    model_dtype: str | None = None
    #: `"train"`, `"eval"`, or `None` when it could not be read.
    model_mode: str | None = None
    output_gpu_resident: bool | None = None
    output_shape: tuple[int, ...] | None = None
    output_dtype: str | None = None

    # ── identity ──────────────────────────────────────────────────────
    gpu_uuid: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    git_sha: str = Field(min_length=1)
    process_pid: int = Field(gt=0)
    candidate: dict[str, Any] = Field(default_factory=dict)
    inference_batch_size: int | None = Field(default=None, gt=0)
    detail: str = ""

    @model_validator(mode="after")
    def _a_gap_is_not_a_zero(self) -> MilestoneRecord:
        """Unavailable telemetry may not carry driver figures.

        The same invariant `gpu_accounting` and `gpu_measurement_sampler`
        enforce, restated here because this record is written to a file and
        read back by a comparison that would otherwise happily average a
        failed query in as 0 MiB.
        """
        if self.telemetry_available:
            return self
        populated = [
            name
            for name in ("tree_total_mib", "device_used_mib", "other_mib")
            if getattr(self, name) is not None
        ]
        if populated or self.own_processes:
            raise ValueError(
                f"telemetry_available=False but {sorted(populated)} are populated; "
                "an unmeasured milestone must stay None, because a comparison "
                "reading a failed query as zero would invent a divergence"
            )
        return self

    @property
    def own_pids(self) -> tuple[int, ...]:
        return tuple(p.pid for p in self.own_processes)


def _repo_root() -> Path:
    """This checkout, from this file's location. Never a fixed path."""
    return require_checkout(checkout_root())


def resolve_git_sha() -> str:
    """The exact commit this trace was produced at.

    Resolved here rather than accepted from the caller: a SHA the
    validation harness passes in is a claim, and a SHA read from the
    checkout that is actually executing is evidence. `"unknown"` when git
    cannot answer -- honest, and visibly not a commit.
    """
    try:
        completed = subprocess.run(
            ["git", "-C", str(_repo_root()), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=True,
        )
    except Exception:
        return "unknown"
    sha = (completed.stdout or "").strip()
    return sha or "unknown"


def _torch_or_none() -> Any:
    """torch if this process has already imported it, else `None`.

    Deliberately checks `sys.modules` instead of importing: a milestone
    taken before the heavy imports must record that torch was absent, and
    importing it here to find out would make the record false the moment it
    was taken.
    """
    import sys

    return sys.modules.get("torch")


def _tensor_shape(tensor: Any) -> tuple[int, ...] | None:
    try:
        return tuple(int(d) for d in tensor.shape)
    except Exception:
        return None


def _dtype_name(obj: Any) -> str | None:
    try:
        return str(obj.dtype).replace("torch.", "")
    except Exception:
        return None


def _model_dtype(model: Any) -> str | None:
    try:
        for param in model.parameters():
            return str(param.dtype).replace("torch.", "")
    except Exception:
        return None
    return None


def _model_mode(model: Any) -> str | None:
    training = getattr(model, "training", None)
    if training is None:
        return None
    return "train" if training else "eval"


class MilestoneTracer:
    """Records lifecycle milestones for one process, to one NDJSON file.

    Constructed only by `tracer_from_environment`, which returns `None`
    when the environment variable is absent -- so a production process
    holds no tracer at all rather than holding a disabled one. There is no
    "enabled" flag to get wrong.
    """

    def __init__(
        self,
        channel: MilestoneTraceChannel,
        *,
        side: TraceSide,
        phase: str = "inference",
        git_sha: str | None = None,
        device_sampler: Any = None,
        clock: Any = None,
        elapsed_clock: Any = None,
    ) -> None:
        self.channel = channel
        self.side: TraceSide = side
        self.phase = phase
        self.git_sha = git_sha or resolve_git_sha()
        self._sampler = device_sampler or sample_device
        self._clock = clock or time.time
        self._elapsed = elapsed_clock or time.monotonic
        self._device = channel.device_identity()
        self._records: list[MilestoneRecord] = []
        self._once_seen: set[str] = set()
        self._batch_progress: dict[int, int] = {}
        self.candidate: dict[str, Any] = {}
        self.inference_batch_size: int | None = None

        self._path = Path(channel.path)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8"):
                pass
        except OSError as exc:
            raise MilestoneTraceUnavailable(
                f"the milestone trace channel is unwritable: {channel.path!r} ({exc}). "
                "This is a validation-infrastructure failure and says nothing about "
                "the candidate or the device."
            ) from exc

    # ── configuration the call site supplies once ──────────────────────

    def set_candidate(
        self, candidate: dict[str, Any], *, inference_batch_size: int | None = None
    ) -> None:
        """Attach the candidate identity every later record carries."""
        self.candidate = dict(candidate)
        if inference_batch_size is not None:
            self.inference_batch_size = int(inference_batch_size)

    def traces_batch(self, batch_index: int) -> bool:
        """Whether this batch is inside the recorded bound.

        Exposed so a call site can skip building trace arguments for
        batches that will not be recorded, without duplicating the rule.
        """
        return 0 <= batch_index < self.channel.max_traced_batches

    # ── the one recording entry point ──────────────────────────────────

    def record(
        self,
        milestone: str,
        *,
        batch_index: int | None = None,
        synchronize: bool = False,
        model: Any = None,
        model_input: Any = None,
        output: Any = None,
        detail: str = "",
    ) -> MilestoneRecord | None:
        """Sample the driver and the allocator, and append one record.

        Returns `None` when the milestone is a per-batch one outside
        `max_traced_batches` -- a bounded skip, visible in the artifact
        because the bound travels on every per-batch record that IS written.

        `synchronize=True` completes outstanding CUDA work before sampling.
        Required at `POST_FORWARD_MILESTONE`: CUDA is asynchronous, and a
        sample taken with kernels still queued describes a state the device
        has not reached.
        """
        self._check_order(milestone, batch_index)
        if batch_index is not None and not self.traces_batch(batch_index):
            return None

        torch = _torch_or_none()
        synchronized = False
        if synchronize and torch is not None:
            try:
                if torch.cuda.is_available() and torch.cuda.is_initialized():
                    torch.cuda.synchronize()
                    synchronized = True
            except Exception:
                synchronized = False

        allocated, reserved, initialized = self._allocator_view(torch)
        snapshot = self._sample_driver()

        record = MilestoneRecord(
            at=float(self._clock()),
            monotonic_at=float(self._elapsed()),
            sequence=len(self._records),
            side=self.side,
            phase=self.phase,
            milestone=milestone,
            batch_index=batch_index,
            max_traced_batches=(
                self.channel.max_traced_batches if batch_index is not None else None
            ),
            telemetry_available=snapshot.telemetry_available,
            tree_total_mib=snapshot.own_tree_mib,
            own_processes=snapshot.own_processes,
            device_used_mib=snapshot.device_used_mib,
            other_mib=snapshot.other_mib,
            allocator_allocated_mib=allocated,
            allocator_reserved_mib=reserved,
            cuda_initialized=initialized,
            cuda_synchronized=synchronized,
            input_shape=_tensor_shape(model_input) if model_input is not None else None,
            input_dtype=_dtype_name(model_input) if model_input is not None else None,
            model_dtype=_model_dtype(model) if model is not None else None,
            model_mode=_model_mode(model) if model is not None else None,
            output_gpu_resident=(
                bool(getattr(output, "is_cuda", False)) if output is not None else None
            ),
            output_shape=_tensor_shape(output) if output is not None else None,
            output_dtype=_dtype_name(output) if output is not None else None,
            gpu_uuid=self.channel.device_uuid,
            run_id=self.channel.run_id,
            git_sha=self.git_sha,
            process_pid=os.getpid(),
            candidate=dict(self.candidate),
            inference_batch_size=self.inference_batch_size,
            detail=detail[:400],
        )
        self._records.append(record)
        self._append(record)
        return record

    # ── internals ──────────────────────────────────────────────────────

    def _check_order(self, milestone: str, batch_index: int | None) -> None:
        """Reject a duplicate or an out-of-order milestone, loudly."""
        if milestone not in MILESTONE_SEQUENCE:
            raise MilestoneTraceMisuse(
                f"{milestone!r} is not a lifecycle milestone; expected one of "
                f"{list(MILESTONE_SEQUENCE)}"
            )
        if milestone in ONCE_MILESTONES:
            if batch_index is not None:
                raise MilestoneTraceMisuse(
                    f"{milestone!r} is once-per-process and cannot carry a batch_index"
                )
            if milestone in self._once_seen:
                raise MilestoneTraceMisuse(
                    f"{milestone!r} was already recorded; two records under one name "
                    "leave the lifecycle comparison unable to say which to align"
                )
            self._once_seen.add(milestone)
            return

        if batch_index is None:
            raise MilestoneTraceMisuse(f"{milestone!r} is per-batch and requires a batch_index")
        expected = PER_BATCH_MILESTONES.index(milestone)
        seen = self._batch_progress.get(batch_index, 0)
        if expected < seen:
            raise MilestoneTraceMisuse(
                f"{milestone!r} came after {PER_BATCH_MILESTONES[seen - 1]!r} in batch "
                f"{batch_index}; a milestone recorded out of order describes a state "
                "other than the one its name claims"
            )
        self._batch_progress[batch_index] = expected + 1

    def _allocator_view(self, torch: Any) -> tuple[int | None, int | None, bool]:
        """Current allocator occupancy in MiB, and whether CUDA is up.

        Current, not peak: a milestone is a point, and a running maximum
        would answer a question about the whole run instead.
        """
        if torch is None:
            return None, None, False
        try:
            if not torch.cuda.is_available() or not torch.cuda.is_initialized():
                return None, None, False
            return (
                int(torch.cuda.memory_allocated() // _MIB),
                int(torch.cuda.memory_reserved() // _MIB),
                True,
            )
        except Exception:
            # Unreadable is unknown, not zero.
            return None, None, False

    def _sample_driver(self) -> Any:
        """One sample from the PRODUCTION primitive, self-rooted.

        `root_pid` is this process, so ownership is exactly the production
        rule -- descendants by ancestry -- applied to the tree this process
        heads. A sampler failure is a value: `telemetry_available=False`
        with every figure `None`.
        """
        try:
            return self._sampler(os.getpid(), self._device)
        except Exception:
            from core.runtime_control.gpu_accounting import GpuAccountingSnapshot

            return GpuAccountingSnapshot(device=self._device, telemetry_available=False)

    def _append(self, record: MilestoneRecord) -> None:
        """Append-only, flushed per record.

        Flushed because the process being traced may be killed at a
        deadline or by the OOM killer, and the milestones it did reach are
        the evidence about where it got to.
        """
        try:
            with open(self._path, "a", encoding="utf-8") as handle:
                handle.write(record.model_dump_json() + "\n")
                handle.flush()
        except OSError as exc:
            raise MilestoneTraceUnavailable(
                f"the milestone trace became unwritable mid-run: {self._path!r} ({exc}). "
                "Validation infrastructure, not a candidate property."
            ) from exc

    @property
    def records(self) -> tuple[MilestoneRecord, ...]:
        return tuple(self._records)


def tracer_from_environment(
    *,
    side: TraceSide,
    phase: str = "inference",
    environ: dict[str, str] | None = None,
    **kwargs: Any,
) -> MilestoneTracer | None:
    """A tracer, or `None` when tracing was not explicitly requested.

    `None` is the production path and the default: with the variable
    absent, no channel is parsed, no file is created, no driver query is
    made, and the call sites hold nothing to call. That is why there is no
    boolean "enabled" flag anywhere -- the absence of the tracer IS the
    disabled state, and it cannot be half-configured.

    Raises `MilestoneTraceUnavailable` when the variable IS set but does
    not describe a usable channel. Silently ignoring a malformed channel
    would produce a GPU run with no artifact and no warning, which costs
    exactly as much as the run and answers nothing.
    """
    env = environ if environ is not None else os.environ
    raw = env.get(TRACE_ENV_VAR)
    if not raw or not raw.strip():
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MilestoneTraceUnavailable(
            f"{TRACE_ENV_VAR} is set but is not JSON: {exc}. Expected a channel "
            'like {"path": "...", "device_uuid": "GPU-...", "run_id": "..."}'
        ) from exc
    if not isinstance(payload, dict):
        raise MilestoneTraceUnavailable(
            f"{TRACE_ENV_VAR} must be a JSON object describing the channel, "
            f"not {type(payload).__name__}"
        )

    try:
        channel = MilestoneTraceChannel(**payload)
    except Exception as exc:
        raise MilestoneTraceUnavailable(
            f"{TRACE_ENV_VAR} does not describe a usable channel: {exc}"
        ) from exc

    return MilestoneTracer(channel, side=side, phase=phase, **kwargs)
