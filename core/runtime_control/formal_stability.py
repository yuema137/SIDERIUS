"""Stop a validation training phase when its GPU peak has stopped moving.

V20 PR C2, operator decision 2026-08-04. **Validation only.** Nothing here
runs unless `SIDERIUS_C2_FORMAL_STABILITY` names a channel, and production
never names one.

WHY THE PREVIOUS ANSWER WAS WRONG. The shortened Case 12 bounded the formal
arm at **2000 training steps and 160 inference batches**, derived from
8.0762 ms/step and 0.705 s/file measured on an RTX 5090. Those integers are
*observations of one machine*, not a definition of the work. On an H100 the
same counts buy a different amount of execution and nothing in the design
would notice.

They were also measuring the wrong thing. Of the 14.45 s inference phase
those numbers came from, **4.25 s (29 %) was filesystem** -- input read
2.27 s, output write 0.72 s, per-file residual 1.27 s -- so a duration
target was partly a storage benchmark. Peak stability is a property of the
GPU, and it must not be inferred from how fast a disk happened to be.

WHAT REPLACES IT. Completion is decided from live execution on the machine
under test:

```text
prepare the bounded input          (outside the measured window)
-> open the measured GPU phase
-> real forward / backward / optimizer step, repeatedly
-> every COMPLETED step is recorded
-> the parent watches the driver-visible cumulative peak
-> peak increases  -> the stable-step counter resets to zero
-> peak unchanged for N completed steps, with enough readings after the
   last increase -> the parent signals stop
-> the trainer stops BETWEEN steps, never mid-update
```

The same rule runs on every card. A 5090 and an H100 reach it after
whatever number of steps each one needs, and **no second, no step count and
no MiB figure travels between them**.

THE PARENT OWNS THE DECISION, for the reason D-C2-13 already established:
it is the only component that can see driver-visible memory at all. The
trainer cannot measure its own process tree, so it emits evidence and obeys
a signal; it never concludes.

A BACKSTOP IS NOT A PASS. Hitting the step ceiling or the wall-clock limit
means stability was never demonstrated, and the honest result is
`INCONCLUSIVE`. Reporting a requirement there would publish a number whose
peak was still moving when the measurement stopped.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: THE environment variable. Its value is a JSON channel, never a bare
#: boolean: a stop rule that cannot say where it reads events, where it
#: writes the signal, or which run it belongs to cannot be audited.
#: Production never sets this.
STABILITY_ENV_VAR = "SIDERIUS_C2_FORMAL_STABILITY"

#: Completed optimizer steps that must pass after the LAST increase in the
#: cumulative driver-visible peak. Operator decision, 2026-08-04.
#:
#: Deliberately NOT converted from a duration. It is an extra stability
#: margin expressed in real work, so a faster card simply reaches it sooner
#: -- which is the whole point of not shipping one card's seconds to
#: another (e.g. an RTX 5090's timings to an H100).
DEFAULT_STABLE_STEPS_AFTER_LAST_PEAK = 500

#: Valid driver-visible samples required AFTER the last peak increase.
#: Steps alone are not enough: 500 steps during which nobody looked proves
#: nothing about the peak. Matches `MINIMUM_AUTHORITATIVE_SAMPLES`.
DEFAULT_MIN_SAMPLES_AFTER_LAST_PEAK = 3

#: Runaway ceiling. Reaching it is `INCONCLUSIVE`, never a pass.
DEFAULT_MAX_COMPLETED_STEPS = 5000

#: Why a phase stopped, or why it has not.
StabilityStatus = Literal[
    "STABLE",
    "NOT_YET_STABLE",
    "INCONCLUSIVE_MAX_STEPS",
    "INCONCLUSIVE_DEADLINE",
    "INCONCLUSIVE_NO_PEAK",
    "INCONCLUSIVE_NO_STEP",
]


class FormalStabilityChannel(BaseModel):
    """Where step evidence is written, where the stop signal appears.

    Pydantic-validated rather than read as a path, because a channel
    missing its run or candidate identity produces events that cannot be
    matched to the phase they came from.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Append-only NDJSON the trainer writes one line to per completed step.
    events_path: str = Field(min_length=1)
    #: The parent touches this once it has decided. The trainer only ever
    #: reads it, and only between completed steps.
    stop_path: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    #: The realized candidate this phase is measuring. Carried on every
    #: event so a stale log from another attempt cannot be counted.
    candidate_id: str = Field(min_length=1)

    stable_steps_after_last_peak: int = Field(default=DEFAULT_STABLE_STEPS_AFTER_LAST_PEAK, gt=0)
    min_samples_after_last_peak: int = Field(default=DEFAULT_MIN_SAMPLES_AFTER_LAST_PEAK, gt=0)
    max_completed_steps: int = Field(default=DEFAULT_MAX_COMPLETED_STEPS, gt=0)
    #: Safety wall-clock cap in seconds. `None` leaves the parent's existing
    #: deadline as the only time bound. It is a SAFETY stop and never a
    #: success criterion, which is why each Gate packet may set its own.
    max_phase_seconds: float | None = Field(default=None, gt=0.0)


class StepEvent(BaseModel):
    """One COMPLETED optimizer step.

    Emitted only after forward, backward and the optimizer update have all
    finished. A partially failed step must produce nothing: counting it
    would let the stable-step total advance on work that never happened,
    which is the one way this rule could certify a moving peak as settled.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: 1-based, so `step_index == 1` is the first optimizer step.
    step_index: int = Field(gt=0)
    at: float = Field(ge=0.0)
    run_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    forward_ok: bool
    backward_ok: bool
    optimizer_ok: bool
    #: Whether the device was synchronized before this event was written.
    #: Without it the event can precede the work it claims, and the parent
    #: would credit memory readings to steps that had not finished.
    synchronized: bool = False

    @model_validator(mode="after")
    def _only_completed_steps(self) -> StepEvent:
        if not (self.forward_ok and self.backward_ok and self.optimizer_ok):
            raise ValueError(
                "a StepEvent records a COMPLETED step; forward, backward and the "
                "optimizer update must all have finished, or nothing is emitted"
            )
        return self


class StabilityDecision(BaseModel):
    """What the parent concluded, and everything it concluded it from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: StabilityStatus
    #: True only for `STABLE`. A backstop is not a pass.
    should_stop: bool
    completed_steps: int = Field(ge=0)
    #: Peak in MiB, `None` when nothing was ever observed.
    cumulative_peak_mib: int | None = Field(default=None, ge=0)
    #: When the cumulative peak last rose. `None` when never observed.
    last_peak_increase_at: float | None = None
    #: The step index in flight at that moment, for the artifact.
    last_peak_increase_step: int | None = Field(default=None, ge=0)
    stable_steps: int = Field(default=0, ge=0)
    samples_after_last_increase: int = Field(default=0, ge=0)
    required_stable_steps: int = Field(gt=0)
    required_samples: int = Field(gt=0)
    max_completed_steps: int = Field(gt=0)
    elapsed_seconds: float = Field(default=0.0, ge=0.0)
    detail: str = ""


def evaluate_stability(
    *,
    events: Sequence[StepEvent],
    samples: Sequence[Any],
    channel: FormalStabilityChannel,
    elapsed_seconds: float = 0.0,
) -> StabilityDecision:
    """Whether the peak has settled. A VALUE, never an exception.

    `samples` are the parent's driver observations -- anything carrying
    `at`, `telemetry_available` and `own_tree_mib`, which is exactly
    `TreeMemorySample`. Failed samples are skipped rather than read as 0:
    a gap is not a zero, and treating one as a low reading would look like
    the peak had fallen.

    Correlation is by timestamp. Steps completed after the last peak
    increase are the stable ones; when the peak rises again, that moment
    moves forward and the count collapses on its own -- the reset is a
    consequence of the definition rather than a separate rule that could be
    forgotten.
    """
    required_steps = channel.stable_steps_after_last_peak
    required_samples = channel.min_samples_after_last_peak
    base: dict[str, Any] = {
        "completed_steps": len(events),
        "required_stable_steps": required_steps,
        "required_samples": required_samples,
        "max_completed_steps": channel.max_completed_steps,
        "elapsed_seconds": round(elapsed_seconds, 6),
    }

    observed = [
        s
        for s in samples
        if getattr(s, "telemetry_available", False) and getattr(s, "own_tree_mib", None) is not None
    ]

    # Walk the samples in time order, tracking when the running maximum
    # last rose. Ties do not count as increases -- a peak that repeats is
    # the same peak.
    peak: int | None = None
    last_increase_at: float | None = None
    for sample in sorted(observed, key=lambda s: float(s.at)):
        value = int(sample.own_tree_mib)
        if peak is None or value > peak:
            peak, last_increase_at = value, float(sample.at)

    if not events:
        return StabilityDecision(
            status="INCONCLUSIVE_NO_STEP",
            should_stop=False,
            cumulative_peak_mib=peak,
            last_peak_increase_at=last_increase_at,
            detail="no completed optimizer step; the first step is mandatory",
            **base,
        )
    if peak is None or last_increase_at is None:
        return StabilityDecision(
            status="INCONCLUSIVE_NO_PEAK",
            should_stop=False,
            detail="no authoritative driver-visible peak was observed",
            **base,
        )

    after = [e for e in events if e.at > last_increase_at]
    stable_steps = len(after)
    samples_after = sum(1 for s in observed if float(s.at) > last_increase_at)
    increase_step = len(events) - stable_steps

    # Annotated for the same reason `base` above is: without it the inferred
    # value type is the join of an int peak, a float timestamp and `base`'s
    # float elapsed time, so `**common` offers `float` to every `int` field
    # and pyright strict rejects all four construction sites. Type-only --
    # the mapping and every value in it are unchanged.
    common: dict[str, Any] = dict(
        cumulative_peak_mib=peak,
        last_peak_increase_at=last_increase_at,
        last_peak_increase_step=increase_step,
        stable_steps=stable_steps,
        samples_after_last_increase=samples_after,
        **base,
    )

    if stable_steps >= required_steps and samples_after >= required_samples:
        return StabilityDecision(
            status="STABLE",
            should_stop=True,
            detail=(
                f"peak {peak} MiB unchanged for {stable_steps} completed steps "
                f"with {samples_after} readings since the last increase"
            ),
            **common,
        )

    # Backstops are checked only AFTER stability, so a run that settles on
    # its very last allowed step still passes rather than being failed by
    # arriving late.
    if len(events) >= channel.max_completed_steps:
        return StabilityDecision(
            status="INCONCLUSIVE_MAX_STEPS",
            should_stop=True,
            detail=(
                f"{len(events)} completed steps reached the ceiling with only "
                f"{stable_steps}/{required_steps} stable steps and "
                f"{samples_after}/{required_samples} readings; the peak was still "
                "moving, so no requirement is claimed"
            ),
            **common,
        )
    if channel.max_phase_seconds is not None and elapsed_seconds >= channel.max_phase_seconds:
        return StabilityDecision(
            status="INCONCLUSIVE_DEADLINE",
            should_stop=True,
            detail=(
                f"the {channel.max_phase_seconds}s safety cap was reached with "
                f"{stable_steps}/{required_steps} stable steps; a time limit is a "
                "safety stop, never a success criterion"
            ),
            **common,
        )

    return StabilityDecision(
        status="NOT_YET_STABLE",
        should_stop=False,
        detail=f"{stable_steps}/{required_steps} stable steps, {samples_after}/{required_samples} readings",
        **common,
    )


class StepEventLog:
    """The trainer's side: emit completed steps, read the stop signal.

    Holds no policy. It cannot decide to stop, because it cannot see the
    process tree's driver-visible memory -- only the parent can.
    """

    def __init__(self, channel: FormalStabilityChannel, *, clock: Any = None) -> None:
        self.channel = channel
        self._clock = clock or time.time
        self._events_path = Path(channel.events_path)
        self._stop_path = Path(channel.stop_path)
        self._events_path.parent.mkdir(parents=True, exist_ok=True)
        self.completed_steps = 0

    def record_completed_step(self, *, synchronized: bool = False) -> StepEvent:
        """Append one event. Call ONLY after the optimizer update returns."""
        self.completed_steps += 1
        event = StepEvent(
            step_index=self.completed_steps,
            at=float(self._clock()),
            run_id=self.channel.run_id,
            candidate_id=self.channel.candidate_id,
            forward_ok=True,
            backward_ok=True,
            optimizer_ok=True,
            synchronized=synchronized,
        )
        with open(self._events_path, "a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json() + "\n")
            handle.flush()
        return event

    def should_stop(self) -> bool:
        """Whether the parent has signalled. Cheap and non-blocking."""
        return self._stop_path.exists()

    def observe_completed_step(self, *, synchronized: bool = False) -> bool:
        """Record one completed step and report whether to stop.

        The training engines call THIS rather than the two methods
        separately. Both loops are already long, and an extension point that
        needs four lines at a call site tends to arrive at one of them and
        not the other -- which is exactly what happened: the first wiring
        landed in `run_experiment` (the legacy single-file path) while every
        Gate arm runs `run_experiment_streaming`, so no event was ever
        emitted.

        The order is fixed and load-bearing. The step is recorded BEFORE the
        signal is read, so the step that was in flight when the parent
        decided is still counted; reading first would lose it.
        """
        self.record_completed_step(synchronized=synchronized)
        return self.should_stop()


def read_step_events(
    path: str | Path,
    *,
    run_id: str | None = None,
    candidate_id: str | None = None,
) -> list[StepEvent]:
    """Parse the trainer's log, dropping anything unreadable or foreign.

    A malformed trailing line is expected -- the file is appended to live
    and may be read mid-write -- so it is skipped rather than raised on. A
    line from a DIFFERENT run is dropped too: counting another attempt's
    steps would advance this phase's stability on work it never did.

    Both identities are checked when supplied. `run_id` alone would admit a
    line written by a different candidate inside the same run -- Case 12
    runs six formal arms under one Gate, and an arm that counted its
    neighbour's steps would reach 500 "stable" steps without having
    executed them.
    """
    events: list[StepEvent] = []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return events
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            event = StepEvent(**json.loads(line))
        except Exception:
            continue
        if run_id is not None and event.run_id != run_id:
            continue
        if candidate_id is not None and event.candidate_id != candidate_id:
            continue
        events.append(event)
    return events


def channel_from_environment(
    *, environ: dict[str, str] | None = None
) -> FormalStabilityChannel | None:
    """The channel, or `None` when validation did not request one.

    `None` is the production path: no file is opened, no event is written,
    no stop signal is read, and the trainer holds nothing to call. The
    absence of the channel IS the disabled state, so there is no flag to
    leave switched on by accident.
    """
    env = environ if environ is not None else os.environ
    raw = env.get(STABILITY_ENV_VAR)
    if not raw or not raw.strip():
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{STABILITY_ENV_VAR} is set but is not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{STABILITY_ENV_VAR} must be a JSON object describing the channel")
    return FormalStabilityChannel(**payload)
