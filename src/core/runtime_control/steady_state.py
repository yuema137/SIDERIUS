"""
core/runtime_control/steady_state.py

Adaptive steady-state detection for runtime verification (RT2a; moved
into the generic runtime-control framework in RT2-A).

Design: docs/design/runtime_estimation_and_watchdog.md §2b (rev 4 +
RT2 kickoff). The first training steps are NOT representative of
steady-state execution (CUDA context init, cuBLAS/cuDNN autotune,
kernel compilation, memory-pool init, cache warming, DataLoader
startup, GPU clock ramp-up), so the verification loop must DETECT when
the execution has stabilised rather than assume it after a fixed number
of iterations. There are deliberately no "N untimed steps" constants.

Criterion (an implementation choice serving the §2a prediction-accuracy
contract; swappable without changing the contract): **rolling-median
stability** — a rolling median of the last ``window`` step times is
recomputed after every step, and steady state is declared when the last
``stable_windows`` consecutive rolling medians agree within
``rel_spread_tol`` relative spread. The median is robust to single-step
jitter spikes; the consecutive-agreement requirement rejects monotonic
ramps (their medians keep drifting, so the spread stays open).

The module is pure and torch-free: it consumes step durations in
milliseconds and is unit-testable with synthetic traces. The
verification skill (RT2c) feeds it real per-step timings.
"""

from __future__ import annotations

import statistics

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SteadyStateConfig(BaseModel):
    """Tunable parameters of the rolling-median stability criterion.

    Defaults are starting points serving the §2a accuracy contract, not
    physical constants — they bound HOW stability is judged, never how
    long warm-up takes (that is adaptive).
    """

    model_config = ConfigDict(frozen=True)

    window: int = Field(
        default=8,
        ge=2,
        description="Rolling-median window length in steps.",
    )
    stable_windows: int = Field(
        default=4,
        ge=2,
        description=(
            "Number of consecutive rolling medians that must agree "
            "within rel_spread_tol for steady state to be declared."
        ),
    )
    rel_spread_tol: float = Field(
        default=0.10,
        gt=0.0,
        lt=1.0,
        description=(
            "Maximum relative spread (max-min)/min of the last stable_windows rolling medians."
        ),
    )
    max_steps: int = Field(
        default=200,
        ge=4,
        description=(
            "Warm-up budget: give up on detection after this many "
            "observed steps (lightweight contract — the caller then "
            "treats the run as not-steady and decides per policy)."
        ),
    )

    @property
    def min_steps_to_detect(self) -> int:
        """Earliest step count at which detection is possible."""
        return self.window + self.stable_windows - 1

    @model_validator(mode="after")
    def _budget_allows_detection(self) -> SteadyStateConfig:
        if self.max_steps < self.min_steps_to_detect:
            raise ValueError(
                f"max_steps={self.max_steps} cannot accommodate detection: "
                f"window({self.window}) + stable_windows({self.stable_windows}) - 1 "
                f"= {self.min_steps_to_detect} steps are required at minimum."
            )
        return self


class SteadyStateDetection(BaseModel):
    """Outcome of steady-state detection over an observed step-time trace.

    ``steady_from_step`` is the 0-based index of the first step inside
    the steady region (the start of the earliest window of the stable
    median run) — steps before it are warm-up transient and must never
    feed a runtime prediction.
    """

    model_config = ConfigDict(frozen=True)

    reached: bool
    steady_from_step: int | None = None
    steps_observed: int = Field(ge=0)
    steady_median_ms: float | None = Field(default=None, gt=0.0)
    steady_mad_ms: float | None = Field(default=None, ge=0.0)
    rolling_medians_ms: list[float] = Field(
        default_factory=list,
        description="Full rolling-median sequence (provenance for the observation store).",
    )
    reason: str = Field(description='"stable_spread" | "budget_exhausted" | "insufficient_steps"')
    config: SteadyStateConfig

    @model_validator(mode="after")
    def _consistency(self) -> SteadyStateDetection:
        if self.reached and (self.steady_from_step is None or self.steady_median_ms is None):
            raise ValueError("reached=True requires steady_from_step and steady_median_ms.")
        if not self.reached and (
            self.steady_from_step is not None or self.steady_median_ms is not None
        ):
            raise ValueError("reached=False must not carry steady_from_step/steady_median_ms.")
        return self


class SteadyStateDetector:
    """Online rolling-median stability detector.

    Feed one step duration at a time with :meth:`observe`; it returns
    ``True`` as soon as steady state is declared. :meth:`result`
    materialises the full :class:`SteadyStateDetection` (also usable
    before detection, e.g. on budget exhaustion).

    Typical verification-loop usage (RT2c)::

        detector = SteadyStateDetector(config)
        while not detector.observe(run_one_step_ms()):
            if detector.steps_observed >= config.max_steps:
                break  # budget exhausted — not steady
        detection = detector.result()
    """

    def __init__(self, config: SteadyStateConfig | None = None):
        self.config = config or SteadyStateConfig()
        self._times_ms: list[float] = []
        self._medians: list[float] = []
        self._steady_from: int | None = None

    @property
    def steps_observed(self) -> int:
        return len(self._times_ms)

    @property
    def detected(self) -> bool:
        return self._steady_from is not None

    def observe(self, step_ms: float) -> bool:
        """Record one step duration; return True once steady state is declared.

        Raises:
            ValueError: non-positive duration (a timing bug upstream —
                fail loudly rather than poisoning the medians).
        """
        if step_ms <= 0:
            raise ValueError(f"step_ms must be positive; got {step_ms!r}.")
        cfg = self.config
        self._times_ms.append(step_ms)
        if len(self._times_ms) >= cfg.window:
            self._medians.append(statistics.median(self._times_ms[-cfg.window :]))

        if self._steady_from is not None:
            # Already declared: further observations (the timed phase-2
            # loop reusing this detector) extend the steady region — but
            # they also keep VERIFYING the declaration. Provenance:
            # measured on H100 — a run can start fast (boosted clocks,
            # cached kernels; ~8 ms/step), satisfy the stability
            # criterion, then drift up to its true sustained plateau
            # (~29 ms/step). If the latest
            # rolling median deviates from the current steady-region
            # median beyond tolerance, the declaration was premature or
            # conditions drifted: RE-ARM detection so steady state is
            # re-declared at the new plateau instead of trusting the
            # stale one.
            region_median = statistics.median(self._times_ms[self._steady_from :])
            if abs(self._medians[-1] / region_median - 1.0) > cfg.rel_spread_tol:
                self._steady_from = None
                return False
            return True

        if len(self._medians) >= cfg.stable_windows:
            recent = self._medians[-cfg.stable_windows :]
            lo, hi = min(recent), max(recent)
            if (hi - lo) / lo <= cfg.rel_spread_tol:
                # Steady region starts at the first step of the earliest
                # window in the stable run: current step index i (0-based,
                # = len-1) closes window ending there; the stable run's
                # earliest window ends at i-(stable_windows-1) and starts
                # window-1 steps earlier.
                i = len(self._times_ms) - 1
                self._steady_from = i - (cfg.stable_windows - 1) - (cfg.window - 1)
                return True
        return False

    def _trimmed_steady_from(self) -> int | None:
        """Steady-region start after leading-transient trim.

        The rolling median is deliberately robust to outliers — which
        means a single extreme first step (measured on the H100: step 0
        at 2307 ms vs a 28 ms steady median, 82x) does NOT destabilise
        the medians, so detection can declare a steady region that still
        CONTAINS the transient. The region contract says transient steps
        must never feed a prediction, so after detection the start is
        advanced past any leading steps whose deviation from the steady
        median exceeds ``rel_spread_tol`` — the same tolerance that
        defines stability. Median/MAD statistics are near-identical
        either way; the trim protects any consumer that sums or averages
        the region.
        """
        if self._steady_from is None:
            return None
        start = self._steady_from
        region = self._times_ms[start:]
        med = statistics.median(region)
        tol = self.config.rel_spread_tol
        # Never trim past the point where detection remains possible.
        max_start = len(self._times_ms) - self.config.window
        while start < max_start and abs(self._times_ms[start] / med - 1.0) > tol:
            start += 1
        return start

    def steady_times_ms(self) -> list[float]:
        """Step durations inside the (transient-trimmed) steady region."""
        start = self._trimmed_steady_from()
        if start is None:
            return []
        return self._times_ms[start:]

    def result(self) -> SteadyStateDetection:
        """Materialise the detection outcome for the current trace."""
        cfg = self.config
        if self._steady_from is not None:
            steady = self.steady_times_ms()
            med = statistics.median(steady)
            mad = statistics.median(abs(t - med) for t in steady)
            return SteadyStateDetection(
                reached=True,
                steady_from_step=self._trimmed_steady_from(),
                steps_observed=self.steps_observed,
                steady_median_ms=med,
                steady_mad_ms=mad,
                rolling_medians_ms=list(self._medians),
                reason="stable_spread",
                config=cfg,
            )
        reason = (
            "insufficient_steps"
            if self.steps_observed < cfg.min_steps_to_detect
            else "budget_exhausted"
        )
        return SteadyStateDetection(
            reached=False,
            steps_observed=self.steps_observed,
            rolling_medians_ms=list(self._medians),
            reason=reason,
            config=cfg,
        )


def detect_steady_state(
    step_times_ms: list[float], config: SteadyStateConfig | None = None
) -> SteadyStateDetection:
    """Offline convenience wrapper: run the online detector over a full trace.

    Detection is bounded by ``config.max_steps`` (the warm-up budget,
    exactly as the online loop would enforce it); once detected, the
    remainder of the trace extends the steady region — mirroring a
    phase-2 loop that keeps feeding the same detector.
    """
    detector = SteadyStateDetector(config)
    for idx, t in enumerate(step_times_ms):
        if not detector.detected and idx >= detector.config.max_steps:
            break
        detector.observe(t)
    return detector.result()
