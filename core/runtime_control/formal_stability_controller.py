"""The parent's half of the live-stability rule: watch, decide, signal, report.

V20 PR C2, operator decision 2026-08-04. `formal_stability` states the RULE
and gives the trainer its event log. This module is what actually closes the
loop, and it lives here rather than inline in the harness for the reason the
repository already made binding: `HyperparamTuningAgent.run()` reached 2,487
lines by absorbing one more responsibility at a time. Correlating step
progress with driver samples, deciding, signalling and reporting is a
responsibility, so it gets a boundary.

WHY THE PARENT. D-C2-13, restated: the trainer cannot see its own process
tree's driver-visible memory. `torch.cuda.max_memory_allocated()` is
per-process and allocator-visible -- blind to a child, to the CUDA context,
to cuDNN workspaces outside the caching allocator and to
reserved-but-unallocated blocks. The quantity the stop rule is about is
therefore only observable from outside the tree. The trainer emits evidence
and obeys a signal; it never concludes.

THE LOOP.

```text
trainer                              parent (this module)
-------                              --------------------
completed optimizer step
  -> append StepEvent          --->  read_step_events(run_id, candidate_id)
                                     read the driver sample series
                                     -> evaluate_stability
                                     -> peak rose?  counters reset
                                     -> settled?    touch stop_path
  <- read stop_path (between steps)
break out of the loop, save
                                     -> completion() -- the typed result
```

FOUR SEPARATIONS THIS MODULE REFUSES TO COLLAPSE.

1. **Stopping the work is not certifying the evidence.** The stop signal
   ends the phase; `FormalPhaseCompletion.succeeded` decides whether the
   phase may be quoted. A backstop stops and does not certify.
2. **A gap is not a zero, and incomplete sampling is not stability.** If the
   watch missed readings, the peak may have moved inside the gap. Stability
   arithmetic can still say STABLE; the completion refuses it anyway, and
   the honest outcome is a rerun of that arm.
3. **Steps come from steps.** Completed-step progress advances only from
   `StepEvent`s. It is never inferred from elapsed time or from the number
   of samples taken -- a stalled trainer produces samples at full cadence
   and no steps at all, and a rule that counted samples would call that
   stability.
4. **Identity before arithmetic.** Events are matched on BOTH `run_id` and
   `candidate_id`. Case 12 runs six formal arms under one Gate; an arm that
   counted a sibling's steps would reach the threshold without executing it.

WHAT A PRE-EXISTING SIGNAL MEANS. A `stop_path` that already exists before
the phase opens would stop the trainer at its first step, and the arm would
report a peak from a single step as though it had settled. That is a misuse
of the channel rather than an outcome of it, so it raises. Same for a
pre-existing events file: its lines carry this run's identity by
construction, so they would be counted as this phase's work.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.runtime_control.formal_stability import (
    FormalStabilityChannel,
    StabilityDecision,
    StabilityStatus,
    evaluate_stability,
    read_step_events,
)
from core.runtime_control.gpu_requirement import MINIMUM_AUTHORITATIVE_SAMPLES


class FormalStabilityMisuse(RuntimeError):
    """The channel cannot answer the question it was opened to answer.

    Deliberately an exception and not a status. An unusable environment or
    an unsettled peak are expected OUTCOMES and are values; a stop signal
    left over from a previous attempt is a mistake in how the phase was set
    up, and continuing would produce a number that looks measured.
    """


class FormalPhaseCompletion(BaseModel):
    """What one measured training phase concluded, and from what.

    Carries the evidence rather than only the verdict: an acceptance reader
    must be able to see the step at which the peak last rose, how many steps
    and readings followed it, and whether the watch was continuous -- without
    re-deriving any of it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: StabilityStatus
    #: True only for a demonstrated peak plateau under a complete watch.
    #: A backstop is not a pass, and neither is a gappy watch.
    succeeded: bool
    #: Whether the parent actually wrote the stop signal.
    stop_signalled: bool
    #: `time.time()` at which it was written; `None` when it never was.
    signalled_at: float | None = None
    #: Plain-language reason the phase ended. Never empty.
    stop_reason: str = Field(min_length=1)

    completed_steps: int = Field(ge=0)
    cumulative_peak_mib: int | None = Field(default=None, ge=0)
    last_peak_increase_step: int | None = Field(default=None, ge=0)
    last_peak_increase_at: float | None = None
    stable_steps: int = Field(default=0, ge=0)
    samples_after_last_increase: int = Field(default=0, ge=0)
    required_stable_steps: int = Field(gt=0)
    required_samples: int = Field(gt=0)

    #: The watch itself. `sampling_complete` gates `succeeded` because a
    #: peak that rose inside an unwatched stretch is invisible to the rule.
    samples_observed: int = Field(default=0, ge=0)
    samples_missed: int = Field(default=0, ge=0)
    sampling_complete: bool = False

    polls: int = Field(default=0, ge=0)
    poll_errors: int = Field(default=0, ge=0)
    elapsed_seconds: float = Field(default=0.0, ge=0.0)
    #: The last full decision, retained verbatim for the artifact.
    decision: StabilityDecision | None = None


class FormalStabilityController:
    """Correlate step events with driver samples, and end the phase.

    Holds no thread and no sleep. The caller drives `poll()`, which keeps the
    whole rule deterministic under test: a fake clock, a hand-built sample
    series and a hand-written events file exercise the real correlation
    logic rather than a timing approximation of it. `FormalStabilityWatcher`
    supplies a thread when the caller is blocked in a subprocess boundary.
    """

    def __init__(
        self,
        channel: FormalStabilityChannel,
        *,
        samples: Callable[[], Sequence[Any]],
        clock: Callable[[], float] = time.time,
        started_at: float | None = None,
    ) -> None:
        self.channel = channel
        self._samples = samples
        self._clock = clock
        self.started_at = started_at if started_at is not None else clock()

        self._events_path = Path(channel.events_path)
        self._stop_path = Path(channel.stop_path)
        if self._stop_path.exists():
            raise FormalStabilityMisuse(
                f"the stop signal {self._stop_path} already exists before the phase "
                "opened; the trainer would stop at its first step and the arm would "
                "report a single step's peak as a settled one"
            )
        if self._events_path.exists():
            raise FormalStabilityMisuse(
                f"the step-event log {self._events_path} already exists; its lines "
                f"carry run_id={channel.run_id!r} by construction, so they would be "
                "counted as this phase's completed steps"
            )
        self._stop_path.parent.mkdir(parents=True, exist_ok=True)

        self.polls = 0
        self.poll_errors = 0
        self.signalled_at: float | None = None
        self._decision: StabilityDecision | None = None

    @property
    def signalled(self) -> bool:
        return self.signalled_at is not None

    @property
    def last_decision(self) -> StabilityDecision | None:
        return self._decision

    def poll(self) -> StabilityDecision:
        """Read both streams, decide, and signal if the phase should end.

        Idempotent on the signal: once written, it is not rewritten, so
        `signalled_at` records when the parent actually decided rather than
        when it last looked.
        """
        self.polls += 1
        now = self._clock()
        events = read_step_events(
            self._events_path,
            run_id=self.channel.run_id,
            candidate_id=self.channel.candidate_id,
        )
        decision = evaluate_stability(
            events=events,
            samples=list(self._samples()),
            channel=self.channel,
            elapsed_seconds=max(now - self.started_at, 0.0),
        )
        self._decision = decision
        if decision.should_stop and not self.signalled:
            # Touch, not write: the trainer only ever asks whether the path
            # exists, so there is no content to parse, no partial read and
            # no encoding to agree on.
            self._stop_path.touch()
            self.signalled_at = now
        return decision

    def completion(self) -> FormalPhaseCompletion:
        """The typed result. Call once the training boundary has returned.

        `succeeded` is deliberately stricter than `decision.should_stop`.
        Stopping is an action; certifying is a claim, and the claim also
        needs a watch continuous enough for the peak it quotes.
        """
        decision = self._decision
        observed, missed = self._sample_counts()
        complete = missed == 0 and observed >= MINIMUM_AUTHORITATIVE_SAMPLES

        if decision is None:
            return FormalPhaseCompletion(
                status="INCONCLUSIVE_NO_STEP",
                succeeded=False,
                stop_signalled=False,
                stop_reason=(
                    "the phase ended without a single evaluation; stability was "
                    "never computed, so nothing about the peak is claimed"
                ),
                completed_steps=0,
                required_stable_steps=self.channel.stable_steps_after_last_peak,
                required_samples=self.channel.min_samples_after_last_peak,
                samples_observed=observed,
                samples_missed=missed,
                sampling_complete=complete,
                polls=self.polls,
                poll_errors=self.poll_errors,
            )

        if decision.status == "STABLE" and not complete:
            reason = (
                f"the peak plateaued, but the watch was incomplete "
                f"({observed} readings, {missed} missed); a peak that rose inside "
                "an unwatched stretch is invisible, so this arm is rerun rather "
                "than quoted"
            )
        elif self.signalled:
            reason = decision.detail
        else:
            reason = (
                "the training boundary returned before the peak settled "
                f"({decision.stable_steps}/{decision.required_stable_steps} stable "
                f"steps, {decision.samples_after_last_increase}/"
                f"{decision.required_samples} readings); the workload ran out "
                "before stability did"
            )

        return FormalPhaseCompletion(
            status=decision.status,
            succeeded=decision.status == "STABLE" and complete,
            stop_signalled=self.signalled,
            signalled_at=self.signalled_at,
            stop_reason=reason,
            completed_steps=decision.completed_steps,
            cumulative_peak_mib=decision.cumulative_peak_mib,
            last_peak_increase_step=decision.last_peak_increase_step,
            last_peak_increase_at=decision.last_peak_increase_at,
            stable_steps=decision.stable_steps,
            samples_after_last_increase=decision.samples_after_last_increase,
            required_stable_steps=decision.required_stable_steps,
            required_samples=decision.required_samples,
            samples_observed=observed,
            samples_missed=missed,
            sampling_complete=complete,
            polls=self.polls,
            poll_errors=self.poll_errors,
            elapsed_seconds=decision.elapsed_seconds,
            decision=decision,
        )

    def _sample_counts(self) -> tuple[int, int]:
        """Successful readings and missed ones. A failed query is MISSED,
        never read as an idle device."""
        try:
            series = list(self._samples())
        except Exception:
            return 0, 0
        observed = sum(1 for s in series if getattr(s, "telemetry_available", False))
        return observed, len(series) - observed


class FormalStabilityWatcher:
    """Drive a controller from a thread, for a blocking training boundary.

    `TidmadSandbox.execute_training` does not return until the subprocess is
    done, so the parent has no loop of its own to poll from -- the same
    problem `BackgroundTreeSampler` solves for driver sampling, and solved
    the same way. It adds a clock and nothing else: every decision is the
    controller's.

    A failing poll increments `poll_errors` and the loop continues. Letting
    the thread die would leave the trainer running with nobody watching, and
    the phase would end at the workload's length with no stop and no
    explanation.
    """

    def __init__(
        self,
        controller: FormalStabilityController,
        *,
        interval_seconds: float = 0.5,
    ) -> None:
        if interval_seconds <= 0.0:
            raise ValueError("interval_seconds must be positive")
        self.controller = controller
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._tick()
            self._stop.wait(self.interval_seconds)

    def _tick(self) -> None:
        try:
            self.controller.poll()
        except Exception:  # pragma: no cover - defensive; counted, not raised
            self.controller.poll_errors += 1

    def __enter__(self) -> FormalStabilityWatcher:
        self._thread.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self._stop.set()
        self._thread.join(timeout=30.0)
        # One last evaluation after the boundary returned. The steps
        # completed since the previous tick are real work, and a phase whose
        # final decision predates its final steps would under-report both
        # the step count and the peak.
        self._tick()
