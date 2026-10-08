"""Execute the measured phases, for real, and record what was executed.

V20 PR C2 / C2-2.

This module owns ONE responsibility: given a way to build the candidate,
run `setup` and then exactly one work phase, mark the boundaries, and
report what actually happened. It does not choose a process, spawn
anything, sample the driver, classify an outcome or decide admission --
those are C2-3, C2-5 and C2-7.

**Why it is separate from the worker process.** The realism requirements
-- a real forward, a model-connected loss, a real backward, a real
optimizer step that moves a parameter, inference outside autograd -- are
the things most worth testing and the things a GPU makes hardest to test.
Split this way they run on the CPU in milliseconds against a real
`nn.Module`, so the tests prove real autograd rather than asserting
against a mock.

**What is deliberately NOT simulated.** The known under-read axes stay
under-read here and are recorded rather than papered over:

  * training uses one preloaded batch; inference reads bounded evaluation batches;
  * a handful of steps instead of an epoch;
  * a single worker instead of two concurrent chains.

Every one of them points the same way -- a real phase can peak higher than
this measurement. That is why the parent's `SamplingCoverage` travels with
the number and why `SAFETY`-style margins remain the operator's, not
something invented in here.

**Components come from a builder, not from this module.** `setup` is timed
and measured around `build_components()`, so whatever production
construction costs is inside the setup window. The builder is injected so
a test can supply a two-parameter module and this file needs no CUDA, and
so `gpu_measurement_worker_main` is the single place that knows what
"production-equivalent" means.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from execute_tools.task_probe_batch import InferenceProbeBatches

from core.local_code.failure import raise_if_code_package_failure
from core.runtime_control.gpu_measurement_hold import ObservedReservation, reservation_peak_bytes
from core.runtime_control.gpu_measurement_spec import (
    PhaseCompletion,
    PhaseExecutionReport,
    PhaseStatus,
    RealismEvidence,
    TrainingDataCoverage,
    WorkerStatus,
)
from core.runtime_control.gpu_requirement import MeasuredPhase
from core.runtime_control.inference_checkpoint_reference import InferenceCheckpointReference
from core.target_standardization import TargetStandardizationReceipt

_MIB = 1024 * 1024


class _InferenceDeadlineReached(Exception):
    """Only the worker's own elapsed-budget check may raise this signal."""


@dataclass(frozen=True)
class CandidateComponents:
    """Everything one measured phase needs, already on the target device.

    `model_input` and `loss_target` are separate objects on purpose. The
    trainer holds an input tensor AND a target tensor simultaneously
    (`train_engine_sandbox.py:534-549`), and a probe that reuses one object
    for both is one resident tensor short of the process it claims to
    describe. The builder is responsible for producing two.
    """

    model: Any
    model_input: Any
    loss_target: Any
    optimizer: Any
    loss_fn: Any
    parameter_count: int | None = None
    trainable_parameter_count: int | None = None
    #: What was actually built. Only the builder can state it -- the parent
    #: is forbidden from instantiating the candidate, so this is the only
    #: point at which the realized identity exists (D-C2-7).
    realized_identity: Any = None
    #: How much of the dataset the bounded loader actually read (D-C2-12).
    #: Recorded so "bounded" is auditable rather than asserted.
    bounded_read: Any = None
    #: Inference opens a bounded evaluation loader inside the measured phase.
    #: Training retains its existing preloaded-batch contract.
    inference_batches_factory: (
        Callable[[int], AbstractContextManager[InferenceProbeBatches]] | None
    ) = None
    inference_device: str = "cpu"
    inference_input_dtype: Any = None
    verified_checkpoint: InferenceCheckpointReference | None = None
    training_data: TrainingDataCoverage | None = None
    training_standardization: TargetStandardizationReceipt | None = None


@dataclass
class PhaseRunOutcome:
    """What the phase runner established. A value, never an exception.

    A measured CUDA OOM and an exhausted budget are *results* of measuring,
    not errors in measuring, so they arrive here as `status` -- see the
    design's control-flow rule.
    """

    status: WorkerStatus
    phases: tuple[PhaseExecutionReport, ...] = ()
    realism: RealismEvidence = field(default_factory=RealismEvidence)
    #: Carried out of setup so the parent can check the result against the
    #: request, even when a later phase failed.
    realized_identity: Any = None
    detail: str = ""
    verified_checkpoint: InferenceCheckpointReference | None = None


class PhaseJournal:
    """Append-only NDJSON boundary log, flushed as each event happens.

    The final report is the authority on phase windows -- but only when
    there IS a final report. A worker killed at the parent's deadline, or
    reaped by the OOM killer, writes no report, and without this the parent
    could not say which phase was in flight when it died. That difference
    decides whether an operator sees "the candidate OOMed during training"
    or "something failed".
    """

    def __init__(self, path: str | None, *, clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self._clock = clock
        #: Retained for tests and for in-process callers; the file is the
        #: cross-process channel.
        self.events: list[dict[str, Any]] = []

    def record(self, event: str, phase: MeasuredPhase, **extra: Any) -> None:
        entry: dict[str, Any] = {"event": event, "phase": phase, "at": self._clock(), **extra}
        self.events.append(entry)
        if self._path is None:
            return
        import json

        try:
            with open(self._path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, default=str) + "\n")
                handle.flush()
        except OSError:
            # A journal that cannot be written must not end the
            # measurement it is only describing.
            pass


def _cuda_active(device: str) -> bool:
    return device.startswith("cuda")


def _reset_peaks(device: str) -> None:
    """Start this phase's allocator accounting from zero.

    `probe_production.py` resets exactly once, in `_setup()`, which is why
    its peak is a running maximum over setup + training + inference and
    cannot answer a per-phase question (audit finding F2). Resetting at
    every boundary is the whole difference.
    """
    if not _cuda_active(device):
        return
    import torch

    torch.cuda.synchronize(device)
    torch.cuda.reset_peak_memory_stats(device)


def _read_peaks(device: str) -> tuple[int | None, int | None]:
    """Allocator peaks in MiB, or `(None, None)` off CUDA.

    Diagnostics only: per-process, allocator-visible, blind to the CUDA
    context, to workspaces outside the caching allocator and to any child.
    """
    if not _cuda_active(device):
        return None, None
    try:
        import torch

        torch.cuda.synchronize(device)
        return (
            int(torch.cuda.max_memory_allocated(device) // _MIB),
            int(torch.cuda.max_memory_reserved(device) // _MIB),
        )
    except Exception:
        # A peak that cannot be read is unknown, not zero.
        return None, None


def _classify_exception(exc: BaseException) -> str | None:
    """`"cuda"`, `"host"` or `None`, using PR A's classifier.

    Reused rather than rewritten: PyTorch reports a host allocation failure
    as a plain `RuntimeError`, which a bare `except MemoryError` misses --
    two candidates were filed as infrastructure failures on 2026-07-31 for
    exactly that reason.
    """
    try:
        from agent.skills.evaluate_vram_skill.probe_budgets import (
            classify_host_memory_exception,
        )

        return classify_host_memory_exception(exc)
    except Exception:  # pragma: no cover - classifier import guard
        return None


def _synchronize_device(tensor: Any) -> None:
    """Make sure the forward has actually completed before the hold.

    CUDA is asynchronous: without this the hold could begin while the
    kernels are still queued, and the parent would sample a state the
    device has not reached.
    """
    try:
        if getattr(tensor, "is_cuda", False):
            import torch

            torch.cuda.synchronize(tensor.device)
    except Exception:  # pragma: no cover - driver-shape guard
        pass


def _watched_parameter(model: Any) -> Any | None:
    """The trainable parameter whose movement proves the step was real."""
    try:
        for param in model.parameters():
            if getattr(param, "requires_grad", False) and param.numel() > 0:
                return param
    except Exception:  # pragma: no cover - non-module input guard
        return None
    return None


def _count_parameters(model: Any) -> tuple[int | None, int | None]:
    try:
        total = sum(p.numel() for p in model.parameters())
        trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    except Exception:  # pragma: no cover - non-module input guard
        return None, None
    return int(total), int(trainable)


def run_measured_phases(
    *,
    build_components: Callable[[], CandidateComponents],
    phase: MeasuredPhase,
    device: str,
    training_steps: int = 4,
    inference_batches: int = 3,
    journal: PhaseJournal | None = None,
    soft_deadline_seconds: float | None = None,
    min_authoritative_samples: int = 3,
    max_phase_seconds: float = 60.0,
    await_sampler_ready: Callable[[], bool] | None = None,
    await_setup_sampler_ready: Callable[[], bool] | None = None,
    setup_reservation_observer: Callable[[], ObservedReservation] | None = None,
    inference_reservation_observer: Callable[[], ObservedReservation] | None = None,
    training_reservation_observer: Callable[[], ObservedReservation] | None = None,
    phase_observed_enough: Callable[[], bool] | None = None,
    trace: Any = None,
    wall_clock: Callable[[], float] = time.time,
    elapsed_clock: Callable[[], float] = time.monotonic,
) -> PhaseRunOutcome:
    """Run `setup` then `phase`, and report what was executed.

    Args:
        build_components: constructs the candidate on `device`. Called
            inside the setup window, so construction cost is measured.
        phase: `"training"` or `"inference"` -- the one work phase this
            process measures. Running both here would describe a process
            production never launches (see `gpu_measurement_spec`).
        device: the torch device string, used exactly as given. There is
            no fallback: a caller that asked for CUDA and cannot have it
            gets a failure, not a CPU number.
        soft_deadline_seconds: checked between steps so the worker can stop
            cleanly. The hard deadline is the parent's.
        trace: an optional `MilestoneTracer` (V20 PR C2, validation only).
            `None` in production, in which case nothing here calls it. When
            present, the inference phase records the synchronized
            post-forward state at the same lifecycle point formal inference
            records it, so the two can be compared milestone by milestone.

    Returns:
        A `PhaseRunOutcome`. This function does not raise for anything it
        can measure.
    """
    journal = journal or PhaseJournal(None, clock=wall_clock)
    started_elapsed = elapsed_clock()
    reports: list[PhaseExecutionReport] = []
    setup_reservations: list[ObservedReservation] = []
    inference_reservations: list[ObservedReservation] = []
    training_reservations: list[ObservedReservation] = []
    counters: dict[str, Any] = {
        "forward_calls": 0,
        "backward_calls": 0,
        "optimizer_steps": 0,
        "inference_batches": 0,
        "parameter_update_max_abs_delta": None,
        "parameter_update_verified": False,
        "inference_grad_free": None,
        "parameter_count": None,
        "trainable_parameter_count": None,
        "peak_state_holds": 0,
        "peak_state_observed": False,
        #: Kept for reading historical reports; the shared prediction stream
        #: now owns output lifetimes and does not release them early.
        "outputs_released": 0,
    }
    #: Kept out of `counters` so it never reaches `RealismEvidence(**counters)`.
    identity_slot: dict[str, Any] = {"realized_identity": None, "verified_checkpoint": None}

    def _evidence() -> RealismEvidence:
        return RealismEvidence(**counters)

    def _out_of_time() -> bool:
        return (
            soft_deadline_seconds is not None
            and (elapsed_clock() - started_elapsed) >= soft_deadline_seconds
        )

    def _finish(
        status: WorkerStatus, detail: str, *, pending: Sequence[MeasuredPhase] = ()
    ) -> PhaseRunOutcome:
        """Close out, marking phases that never ran as NOT_REACHED.

        A phase that was never reached is a different fact from a phase
        that ran and produced nothing, and collapsing them would let an
        aborted run read as a complete one with an empty result.
        """
        now = wall_clock()
        for missing in pending:
            reports.append(
                PhaseExecutionReport(
                    phase=missing,
                    status="NOT_REACHED",
                    started_at=now,
                    ended_at=now,
                    elapsed_seconds=0.0,
                    detail=f"not reached: {detail}"[:400],
                )
            )
        return PhaseRunOutcome(
            status=status,
            phases=tuple(reports),
            realism=_evidence(),
            realized_identity=identity_slot["realized_identity"],
            verified_checkpoint=identity_slot["verified_checkpoint"],
            detail=detail[:400],
        )

    # ── setup ────────────────────────────────────────────────────────────
    if await_setup_sampler_ready is not None and not await_setup_sampler_ready():
        return _finish(
            "WORKER_FAILURE",
            "driver sampler was unavailable before setup",
            pending=("setup", phase),
        )
    journal.record("phase_start", "setup")
    setup_started = wall_clock()
    _reset_peaks(device)
    try:
        components = build_components()
        identity_slot["verified_checkpoint"] = components.verified_checkpoint
        if components.training_data is not None:
            counters["training_data"] = components.training_data
        if components.training_standardization is not None:
            counters["training_standardization"] = components.training_standardization
        if setup_reservation_observer is not None:
            setup_reservations.append(setup_reservation_observer())
            if not setup_reservations[-1].acknowledged:
                raise RuntimeError("driver sampling did not acknowledge the setup reservation")
    except BaseException as exc:  # classified below, never swallowed
        raise_if_code_package_failure(exc)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        from core.runtime_control.gpu_training_components import TrainingPreparationDeadline

        preparation_expired = isinstance(exc, TrainingPreparationDeadline)
        allocated, reserved = _read_peaks(device)
        setup_ended = wall_clock()
        kind = _classify_exception(exc)
        reports.append(
            PhaseExecutionReport(
                phase="setup",
                status="CUDA_OOM" if kind == "cuda" else "FAILED",
                started_at=setup_started,
                ended_at=setup_ended,
                elapsed_seconds=round(setup_ended - setup_started, 6),
                allocator_peak_mib=allocated,
                allocator_reserved_peak_mib=reserved,
                observed_reservations=tuple(setup_reservations),
                detail=f"{type(exc).__name__}: {exc}"[:400],
            )
        )
        journal.record("phase_end", "setup", status="failed")
        return _finish(
            "DEADLINE_EXCEEDED"
            if preparation_expired
            else "CUDA_OOM"
            if kind == "cuda"
            else "WORKER_FAILURE",
            f"setup failed: {type(exc).__name__}: {exc}",
            pending=(phase,),
        )

    counters["parameter_count"], counters["trainable_parameter_count"] = _count_parameters(
        components.model
    )
    if components.parameter_count is not None:
        counters["parameter_count"] = components.parameter_count
    if components.trainable_parameter_count is not None:
        counters["trainable_parameter_count"] = components.trainable_parameter_count
    identity_slot["realized_identity"] = components.realized_identity

    setup_allocated, setup_reserved = _read_peaks(device)
    setup_reserved_bytes = (
        reservation_peak_bytes(device) if setup_reservation_observer is not None else None
    )
    setup_ended = wall_clock()
    reports.append(
        PhaseExecutionReport(
            phase="setup",
            status="COMPLETED",
            started_at=setup_started,
            ended_at=setup_ended,
            elapsed_seconds=round(setup_ended - setup_started, 6),
            allocator_peak_mib=setup_allocated,
            allocator_reserved_peak_mib=setup_reserved,
            allocator_reserved_peak_bytes=setup_reserved_bytes,
            observed_reservations=tuple(setup_reservations),
            units_executed=1,
            units_requested=1,
        )
    )
    journal.record("phase_end", "setup", status="completed")

    if _out_of_time():
        return _finish(
            "DEADLINE_EXCEEDED",
            f"the {soft_deadline_seconds}s worker budget was spent during setup",
            pending=(phase,),
        )

    # ── the one work phase ───────────────────────────────────────────────
    #
    # D-C2-13. Two things have to be true before a phase peak means
    # anything: somebody must be watching when it opens, and it must stay
    # open long enough for readings to land. Gate 2 Lite-A c7 satisfied
    # neither -- inference ran in 0.138 s against a 0.25 s cadence and the
    # parent took ZERO in-phase samples.
    sampler_ready = True
    sampler_ready_at: float | None = None
    if await_sampler_ready is not None:
        journal.record("awaiting_sampler", phase)
        sampler_ready = bool(await_sampler_ready())
        sampler_ready_at = wall_clock()
        journal.record("sampler_ready", phase, ready=sampler_ready)

    journal.record("phase_start", phase)
    _reset_peaks(device)
    work_started = wall_clock()
    phase_opened = elapsed_clock()
    is_training = phase == "training"
    runner = _run_training if is_training else _run_inference
    requested = training_steps if is_training else inference_batches
    extra: dict[str, Any] = (
        {
            "reservation_observer": training_reservation_observer,
            "observed_reservations": training_reservations,
        }
        if is_training
        # Inference observes a held real state instead of repeating the
        # workload, so the parent's completion signal becomes the hold's
        # release condition rather than a repeat-again condition.
        else {
            "hold_peak_state": phase_observed_enough,
            "reservation_observer": inference_reservation_observer,
            "observed_reservations": inference_reservations,
            "trace": trace,
        }
    )
    executed, status, detail = runner(
        components=components,
        units=requested,
        counters=counters,
        out_of_time=_out_of_time,
        **extra,
    )
    repetitions = 1
    bound_reached = False
    completion: PhaseCompletion = "single_pass" if status == "COMPLETED" else "failed"
    if not is_training and counters.get("peak_state_observed"):
        completion = "sample_target_reached"
    # Repeat the EXACT workload -- same model, same batch, same dtype, same
    # semantics -- until the PARENT says it has seen enough. The parent is
    # the only component that knows how many samples actually landed, so it
    # owns the stop condition. A repetition COUNT cannot express a duration
    # target without knowing the per-repetition cost: attempt 3's c7 hit a
    # 40-repetition ceiling after 0.344 s holding one sample, and a larger
    # guess would only move the number at which the same thing happens.
    # Training still repeats to become observable; inference does not --
    # it holds one real post-forward state instead, because repeating it
    # grew the allocator pool and inflated the measurement (D-C2-18).
    if status == "COMPLETED" and phase_observed_enough is not None and is_training:
        while not phase_observed_enough():
            if (elapsed_clock() - phase_opened) >= max_phase_seconds:
                bound_reached, completion = True, "duration_bound"
                break
            if _out_of_time():
                bound_reached, completion = True, "deadline"
                break
            more, status, detail = runner(
                components=components,
                units=requested,
                counters=counters,
                out_of_time=_out_of_time,
                **extra,
            )
            executed += more
            repetitions += 1
            if status != "COMPLETED":
                # A budget that trips INSIDE a step is still a deadline
                # stop, not a candidate failure. Collapsing the two would
                # report a slow phase as a broken one.
                completion = "deadline" if detail.startswith("deadline:") else "failed"
                break
        else:
            completion = "sample_target_reached"
    allocated, reserved = _read_peaks(device)
    reserved_bytes = (
        reservation_peak_bytes(device)
        if inference_reservation_observer is not None or training_reservation_observer is not None
        else None
    )
    work_ended = wall_clock()
    reports.append(
        PhaseExecutionReport(
            phase=phase,
            status=status,
            started_at=work_started,
            ended_at=work_ended,
            elapsed_seconds=round(work_ended - work_started, 6),
            allocator_peak_mib=allocated,
            allocator_reserved_peak_mib=reserved,
            allocator_reserved_peak_bytes=reserved_bytes,
            observed_reservations=tuple(
                training_reservations if is_training else inference_reservations
            ),
            units_executed=executed,
            units_requested=requested,
            repetitions=repetitions,
            required_samples=min_authoritative_samples,
            completion_reason=completion,
            max_phase_seconds=max_phase_seconds,
            observation_bound_reached=bound_reached,
            sampler_ready=sampler_ready,
            sampler_ready_at=sampler_ready_at,
            detail=detail,
        )
    )
    journal.record(
        "phase_end",
        phase,
        status=status.lower(),
        units_executed=executed,
        repetitions=repetitions,
    )

    if status == "CUDA_OOM":
        return _finish("CUDA_OOM", detail or f"the candidate OOMed during {phase}")
    if status == "FAILED":
        if detail.startswith("deadline:"):
            return _finish("DEADLINE_EXCEEDED", detail)
        return _finish("WORKER_FAILURE", detail or f"{phase} failed")
    return _finish("COMPLETED", "")


def _run_training(
    *,
    components: CandidateComponents,
    units: int,
    counters: dict[str, Any],
    out_of_time: Callable[[], bool],
    reservation_observer: Callable[[], ObservedReservation] | None = None,
    observed_reservations: list[ObservedReservation] | None = None,
) -> tuple[int, PhaseStatus, str]:
    """Real steps: zero_grad -> forward -> loss -> backward -> step.

    The watched parameter is cloned before the first step and compared
    after the last as a diagnostic. Stationary or unused parameters may not
    move. Bound measurements additionally observe optimizer ownership and fresh
    gradient connectivity, without imposing a nonzero-gradient requirement.
    """
    watched = _watched_parameter(components.model)
    before = None
    if watched is not None:
        try:
            before = watched.detach().clone()
        except Exception:  # pragma: no cover - exotic parameter guard
            before = None

    executed = 0
    status: PhaseStatus = "COMPLETED"
    detail = ""
    try:
        bound = components.training_data is not None
        if bound:
            from core.runtime_control.training_measurement_steps import verify_optimizer_ownership

            verify_optimizer_ownership(components, counters)
        if hasattr(components.model, "train"):
            components.model.train()
        for _ in range(units):
            if out_of_time():
                status = "FAILED"
                detail = f"deadline: the worker budget was spent after {executed} step(s)"
                break
            components.optimizer.zero_grad(set_to_none=True)
            if bound and any(p.grad is not None for p in components.model.parameters()):
                raise ValueError("bound training optimizer did not clear model gradients")
            output = components.model(components.model_input)
            counters["forward_calls"] += 1
            if bound:
                counters["training_data"] = counters["training_data"].model_copy(
                    update={"observed_output_shape": tuple(output.shape)}
                )
            loss = components.loss_fn(output, components.loss_target)
            loss.backward()
            counters["backward_calls"] += 1
            if bound:
                if not any(
                    p.requires_grad and p.grad is not None for p in components.model.parameters()
                ):
                    raise ValueError("bound training backward did not connect to model parameters")
                evidence = counters["training_steps"]
                counters["training_steps"] = evidence.model_copy(
                    update={"connected_backward_calls": evidence.connected_backward_calls + 1}
                )
            components.optimizer.step()
            counters["optimizer_steps"] += 1
            executed += 1
            if reservation_observer is not None:
                hold = reservation_observer()
                assert observed_reservations is not None
                observed_reservations.append(hold)
                if not hold.acknowledged:
                    raise RuntimeError(
                        "driver sampling did not acknowledge the training reservation"
                    )
    except BaseException as exc:  # classified below, never swallowed
        raise_if_code_package_failure(exc)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        kind = _classify_exception(exc)
        status = "CUDA_OOM" if kind == "cuda" else "FAILED"
        detail = f"{type(exc).__name__}: {exc}"[:400]

    if watched is not None and before is not None:
        try:
            delta = float((watched.detach() - before).abs().max().item())
            counters["parameter_update_max_abs_delta"] = delta
            counters["parameter_update_verified"] = delta > 0.0
        except Exception:  # pragma: no cover - exotic parameter guard
            pass
    return executed, status, detail


def _run_inference(
    *,
    components: CandidateComponents,
    units: int,
    counters: dict[str, Any],
    out_of_time: Callable[[], bool],
    hold_peak_state: Callable[[], bool] | None = None,
    reservation_observer: Callable[[], ObservedReservation] | None = None,
    observed_reservations: list[ObservedReservation] | None = None,
    trace: Any = None,
) -> tuple[int, PhaseStatus, str]:
    """Consume bounded evaluation predictions through the production stream."""
    import torch

    from core.runtime_control.gpu_measurement_spec import (
        InferenceBatchObservation,
        InferenceDataCoverage,
    )
    from execute_tools.inference_stream import InferenceProgress, prediction_stream

    progress = InferenceProgress()
    observations: list[InferenceBatchObservation] = []
    grad_free = True
    status: PhaseStatus = "COMPLETED"
    detail = ""

    def observe(inputs: Any, output: Any) -> None:
        nonlocal grad_free
        counters["forward_calls"] += 1
        counters["inference_batches"] += 1
        grad_free = grad_free and not output.requires_grad
        observations.append(
            InferenceBatchObservation(
                shape=tuple(inputs.shape),
                storage_dtype=str(inputs.dtype),
                input_dtype=str(components.inference_input_dtype or inputs.dtype),
                output_shape=tuple(output.shape),
            )
        )
        if hold_peak_state is not None or reservation_observer is not None:
            _synchronize_device(output)
            if trace is not None:
                trace.record(
                    "after_forward_output_resident",
                    batch_index=progress.batches - 1,
                    synchronize=True,
                    model=components.model,
                    model_input=inputs,
                    output=output,
                    detail="model_input is the storage batch; conversion is owned by the forward boundary",
                )
            counters["peak_state_holds"] += 1
            if reservation_observer is not None:
                observation = reservation_observer()
                if observed_reservations is not None:
                    observed_reservations.append(observation)
                if not observation.acknowledged:
                    raise RuntimeError(
                        "driver sampling did not acknowledge an inference reservation"
                    )
                counters["peak_state_observed"] = True
            elif hold_peak_state is not None and hold_peak_state():
                counters["peak_state_observed"] = True

    try:
        if components.inference_batches_factory is None:
            raise ValueError("Inference measurement requires an evaluation batch source")
        components.model.eval()
        with components.inference_batches_factory(units) as workload:

            def bounded_batches():
                iterator = iter(workload.loader)
                for _ in range(workload.selected_batches):
                    if out_of_time():
                        raise _InferenceDeadlineReached(
                            "the worker budget was spent before the next evaluation batch"
                        )
                    yield next(iterator)

            predictions = prediction_stream(
                bounded_batches(),
                model=components.model,
                device=torch.device(components.inference_device),
                input_dtype=components.inference_input_dtype,
                progress=progress,
                stage="inference measurement",
                observe_forward=observe,
            )
            try:
                for _prediction in predictions:
                    pass
            finally:
                predictions.close()
                counters["inference_data"] = InferenceDataCoverage(
                    dataset_samples=workload.dataset_samples,
                    selected_samples=workload.selected_samples,
                    selected_batches=workload.selected_batches,
                    consumed_samples=progress.samples,
                    batches=tuple(observations),
                )
            if progress.samples != workload.selected_samples:
                raise ValueError(
                    "Inference output count does not match the selected evaluation scope"
                )
    except BaseException as exc:
        raise_if_code_package_failure(exc)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        kind = _classify_exception(exc)
        status = "CUDA_OOM" if kind == "cuda" else "FAILED"
        detail = (
            f"deadline: {exc}"
            if isinstance(exc, _InferenceDeadlineReached)
            else f"{type(exc).__name__}: {exc}"
        )[:400]

    counters["inference_grad_free"] = grad_free if progress.batches else None
    return progress.batches, status, detail
