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

  * one preloaded batch instead of a `DataLoader` pipeline;
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
from dataclasses import dataclass, field
from typing import Any

from core.local_code.failure import raise_if_code_package_failure
from core.runtime_control.gpu_measurement_spec import (
    PhaseCompletion,
    PhaseExecutionReport,
    PhaseStatus,
    RealismEvidence,
    WorkerStatus,
)
from core.runtime_control.gpu_requirement import MeasuredPhase

_MIB = 1024 * 1024


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

    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()


def _read_peaks(device: str) -> tuple[int | None, int | None]:
    """Allocator peaks in MiB, or `(None, None)` off CUDA.

    Diagnostics only: per-process, allocator-visible, blind to the CUDA
    context, to workspaces outside the caching allocator and to any child.
    """
    if not _cuda_active(device):
        return None, None
    try:
        import torch

        torch.cuda.synchronize()
        return (
            int(torch.cuda.max_memory_allocated() // _MIB),
            int(torch.cuda.max_memory_reserved() // _MIB),
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

            torch.cuda.synchronize()
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
        #: Outputs explicitly released before the following forward. Equal
        #: to the batches executed when the lifecycle is correct; a shortfall
        #: means an output survived into the next forward, which is the
        #: two-resident state that inflated the measurement to 4870 MiB.
        "outputs_released": 0,
    }
    #: Kept out of `counters` so it never reaches `RealismEvidence(**counters)`.
    identity_slot: dict[str, Any] = {"realized_identity": None}

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
            detail=detail[:400],
        )

    # ── setup ────────────────────────────────────────────────────────────
    journal.record("phase_start", "setup")
    setup_started = wall_clock()
    _reset_peaks(device)
    try:
        components = build_components()
    except BaseException as exc:  # classified below, never swallowed
        raise_if_code_package_failure(exc)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
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
                detail=f"{type(exc).__name__}: {exc}"[:400],
            )
        )
        journal.record("phase_end", "setup", status="failed")
        return _finish(
            "CUDA_OOM" if kind == "cuda" else "WORKER_FAILURE",
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
        {}
        if is_training
        # Inference observes a held real state instead of repeating the
        # workload, so the parent's completion signal becomes the hold's
        # release condition rather than a repeat-again condition.
        else {"hold_peak_state": phase_observed_enough, "trace": trace}
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
) -> tuple[int, PhaseStatus, str]:
    """Real steps: zero_grad -> forward -> loss -> backward -> step.

    The watched parameter is cloned before the first step and compared
    after the last. A step that moves nothing means the loss was detached
    from the model somewhere and the backward was decorative -- which is
    the precise failure this whole worker exists because PR A's probe
    could not rule out.
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
        if hasattr(components.model, "train"):
            components.model.train()
        for _ in range(units):
            if out_of_time():
                status = "FAILED"
                detail = f"deadline: the worker budget was spent after {executed} step(s)"
                break
            components.optimizer.zero_grad(set_to_none=True)
            output = components.model(components.model_input)
            counters["forward_calls"] += 1
            loss = components.loss_fn(output, components.loss_target)
            loss.backward()
            counters["backward_calls"] += 1
            components.optimizer.step()
            counters["optimizer_steps"] += 1
            executed += 1
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
    trace: Any = None,
) -> tuple[int, PhaseStatus, str]:
    """Forward only, outside autograd -- the shape production actually runs.

    `inference_grad_free` is recorded from the OUTPUT tensor rather than
    from the fact that `no_grad()` was entered. Entering the context proves
    the code meant to; checking `requires_grad` on what came out proves it
    worked. Under `no_grad` no activation graph is retained, and the
    retained graph is most of what a training peak is made of -- so
    measuring inference with one would silently return a training-shaped
    number for an inference requirement.
    """
    import torch

    executed = 0
    status: PhaseStatus = "COMPLETED"
    detail = ""
    grad_free = True
    try:
        if hasattr(components.model, "eval"):
            components.model.eval()
        with torch.no_grad():
            for _ in range(units):
                if out_of_time():
                    status = "FAILED"
                    detail = f"deadline: the worker budget was spent after {executed} batch(es)"
                    break
                output = components.model(components.model_input)
                counters["forward_calls"] += 1
                counters["inference_batches"] += 1
                if getattr(output, "requires_grad", False):
                    grad_free = False
                executed += 1
                # THE OBSERVATION HOLD (D-C2-18). `output` is still bound,
                # so the full inference result is still resident: this is
                # the real peak state, held long enough to be seen rather
                # than re-created.
                #
                # Repeating the forward instead grew the caching
                # allocator's pool -- 14 repetitions x 3 batches reserved
                # 4266 MiB against 2588 MiB allocated, and the driver
                # figure counts reserved. That inflated inference to
                # 4870 MiB against a real 3642 MiB and opened a
                # false-refusal band. Holding allocates nothing.
                if hold_peak_state is not None:
                    _synchronize_device(output)
                    # V20 PR C2, validation only. Recorded BEFORE the hold
                    # releases and before anything touches `output`, which
                    # is the same lifecycle point formal inference records
                    # (`inference_single.py`, after the forward and before
                    # the argmax/`.cpu()`). Recording it after the hold
                    # would compare a released state with a held one.
                    if trace is not None:
                        trace.record(
                            "after_forward_output_resident",
                            batch_index=executed - 1,
                            synchronize=True,
                            model=components.model,
                            model_input=components.model_input,
                            output=output,
                        )
                    counters["peak_state_holds"] += 1
                    if hold_peak_state():
                        counters["peak_state_observed"] = True
                # RELEASE BEFORE THE NEXT FORWARD.
                #
                # Without this, `output = model(input)` on the next
                # iteration computes the new output while the previous one
                # is STILL BOUND to this name, so two full inference
                # outputs are resident at once. At the production batch of
                # 25 each is 976 MiB, and the measured effect was the
                # allocator pool growing 2830 -> 4266 MiB and the
                # driver-visible figure reaching 4870 MiB against a real
                # phase of 3434.
                #
                # That peak was previously invisible only because the
                # parent stops sampling once the hold satisfies its sample
                # target -- batches after the first ran unobserved. An
                # authoritative measurement must not depend on observation
                # stopping early, so the two-output state is removed rather
                # than left to be missed.
                #
                # Formal inference has no such state: `process_batch`
                # returns between batches and its locals die with the
                # frame. Releasing here makes the probe's loop match that
                # lifecycle instead of inventing a heavier one.
                del output
                counters["outputs_released"] += 1
    except BaseException as exc:  # classified below, never swallowed
        raise_if_code_package_failure(exc)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        kind = _classify_exception(exc)
        status = "CUDA_OOM" if kind == "cuda" else "FAILED"
        detail = f"{type(exc).__name__}: {exc}"[:400]

    counters["inference_grad_free"] = grad_free if executed else None
    return executed, status, detail
