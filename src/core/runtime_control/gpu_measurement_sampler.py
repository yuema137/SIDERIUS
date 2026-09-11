"""Watch the candidate's own process tree on the driver, from outside it.

V20 PR C2 / C2-3.

The worker cannot measure this about itself. `torch.cuda.max_memory_allocated()`
is per-process and allocator-visible: it cannot see a child, the CUDA
context, cuDNN workspaces outside the caching allocator, or
reserved-but-unallocated blocks (audit Q8/Q9). The quantity PR B's admission
reasons about is the *driver-visible* total held by the candidate's tree, so
somebody outside the tree has to look at it.

WHY `gpu_accounting.sample` AND NOT NVML. Audited before choosing:

* `nvidia-smi` via `gpu_accounting.sample` -- **selected**. It already
  splits *ours* from *everyone else's* by **process ancestry** from a root
  PID, which is the only test that claims a child started with
  `start_new_session=True` -- exactly what the measurement worker is. It
  already refuses to substitute a device when the requested UUID is absent,
  and it already keeps `telemetry_available=False` distinct from zero.
  Measured cost on this deployment: **~72 ms per sample** (two bounded
  queries -- device totals and per-process rows, audit finding F4).
* **NVML/pynvml** -- rejected. Not installed (`No module named 'pynvml'`),
  so it would be a new dependency, and it would introduce a *second*
  definition of "driver-visible" beside the primitive PR B's admission
  already reasons about. Two answers to that question is how the
  measurement and the gate come to disagree invisibly.

THREE DISTINCTIONS THIS MODULE REFUSES TO COLLAPSE.

1. **No observation is not zero MiB.** A failed driver query leaves
   `own_tree_mib=None` and counts as a *missed* sample. Reading it as zero
   would report a very small candidate, which is the admit-too-eagerly
   direction.
2. **Sampled zero is not no observation.** A successful query that finds
   the candidate holding nothing is real evidence and is retained as such.
3. **One PID is not the candidate.** The peak of a sample is the SUM over
   every own process alive at that instant, maximized across samples.
   Taking one process's maximum would under-read a tree; summing each
   process's own maximum across different instants would over-read one that
   never coexisted.

WHAT IT IS STILL BLIND TO. A polled query cannot see between polls, and no
cadence removes that. `max_gap_seconds` records the largest unwatched
stretch of each window so the exposure travels with the number rather than
staying a caveat somebody has to remember.
"""

from __future__ import annotations

import itertools
import time
from collections.abc import Callable, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.runtime_control.gpu_accounting import (
    DeviceIdentity,
    GpuAccountingSnapshot,
    ProcessOccupancy,
)
from core.runtime_control.gpu_accounting import sample as sample_device
from core.runtime_control.gpu_requirement import SamplingCoverage


class TreeMemorySample(BaseModel):
    """One driver query, retained raw and timestamped.

    Kept individually rather than folded into a running maximum, because a
    peak with no samples behind it cannot be audited -- an operator asking
    "what was actually on the card, and when" needs the series, and so does
    any later question about which phase a spike belonged to.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: `time.time()`, so it is comparable with the worker's phase windows.
    at: float = Field(ge=0.0)
    telemetry_available: bool

    #: Sum over every candidate-owned process alive at this instant.
    #: `None` when the query failed -- never 0.
    own_tree_mib: int | None = Field(default=None, ge=0)
    #: Who was counted as ours, so the attribution can be audited.
    own_processes: tuple[ProcessOccupancy, ...] = ()
    #: Context, not authority: what the whole device and everyone else held.
    device_used_mib: int | None = Field(default=None, ge=0)
    other_mib: int | None = Field(default=None, ge=0)
    #: WHICH processes were not ours at this instant. Carried through the
    #: series so environmental CHANGE is detectable continuously -- a
    #: neighbour that starts and exits between two endpoint snapshots is
    #: invisible to a before/after comparison and visible here.
    other_processes: tuple[ProcessOccupancy, ...] = ()

    @model_validator(mode="after")
    def _a_gap_is_not_a_zero(self) -> TreeMemorySample:
        if not self.telemetry_available and (self.own_tree_mib is not None or self.own_processes):
            raise ValueError(
                "telemetry_available=False but the sample carries figures; an "
                "unmeasured sample must stay None, because a caller reading a "
                "failed query as zero would under-state the requirement"
            )
        return self

    @property
    def own_pids(self) -> tuple[int, ...]:
        return tuple(p.pid for p in self.own_processes)


class WindowMeasurement(BaseModel):
    """What the driver saw during one phase window.

    This is the driver-visible half of a phase measurement. The allocator
    figures live on the worker's `PhaseExecutionReport` and are joined
    beside these in C2-4 -- never merged into them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    started_at: float = Field(ge=0.0)
    ended_at: float = Field(ge=0.0)

    #: THE AUTHORITY CANDIDATE: peak candidate-owned driver-visible tree
    #: memory over this window. `None` when nothing was observed, which is
    #: refusal rather than zero.
    driver_tree_peak_mib: int | None = Field(default=None, ge=0)
    coverage: SamplingCoverage

    #: Every PID ever attributed to the candidate during the window.
    own_pids: tuple[int, ...] = ()
    #: The most own processes seen resident SIMULTANEOUSLY. Greater than 1
    #: is the proof that a single-process figure would have under-read.
    max_concurrent_own_processes: int = Field(default=0, ge=0)
    #: The sample the peak came from, retained so the figure is traceable.
    peak_sample: TreeMemorySample | None = None


class GpuTreeSampler:
    """Polls the driver for one candidate tree, on demand.

    Deliberately **not** a thread. The caller already runs a supervision
    loop -- deadline, host-RSS bound, process reaping -- and `poll()` slots
    into it. That keeps the whole sampler deterministic under test: a fake
    clock and a fake device sampler drive it with no sleeps and no races,
    so the tests exercise the real attribution logic rather than a timing
    approximation of it.

    A consequence worth stating: if the caller's loop stalls, samples are
    missed. That is not hidden -- it shows up as a larger
    `max_gap_seconds`, which is the truth about how closely the phase was
    actually watched.
    """

    def __init__(
        self,
        root_pid: int,
        device: DeviceIdentity,
        *,
        interval_seconds: float = 0.25,
        device_sampler: Callable[..., GpuAccountingSnapshot] = sample_device,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if interval_seconds <= 0.0:
            raise ValueError("interval_seconds must be positive")
        self.root_pid = root_pid
        self.device = device
        self.interval_seconds = interval_seconds
        self._device_sampler = device_sampler
        self._clock = clock
        self._samples: list[TreeMemorySample] = []
        self._last_at: float | None = None
        self.started_at = clock()
        self.stopped_at: float | None = None

    @property
    def samples(self) -> tuple[TreeMemorySample, ...]:
        return tuple(self._samples)

    def poll(self, *, force: bool = False) -> TreeMemorySample | None:
        """Sample if the cadence has come round, else do nothing.

        `force` takes one regardless, for the boundary samples the caller
        wants: immediately after spawn and immediately before reaping.
        """
        now = self._clock()
        if (
            not force
            and self._last_at is not None
            and (now - self._last_at) < self.interval_seconds
        ):
            return None
        self._last_at = now
        sample = self._to_sample(now)
        self._samples.append(sample)
        return sample

    def _to_sample(self, now: float) -> TreeMemorySample:
        try:
            snapshot = self._device_sampler(self.root_pid, self.device)
        except Exception:
            # The sampler failing is a MISSED sample, not an empty device.
            return TreeMemorySample(at=now, telemetry_available=False)
        if not snapshot.telemetry_available:
            return TreeMemorySample(at=now, telemetry_available=False)
        return TreeMemorySample(
            at=now,
            telemetry_available=True,
            own_tree_mib=snapshot.own_tree_mib,
            own_processes=snapshot.own_processes,
            device_used_mib=snapshot.device_used_mib,
            other_mib=snapshot.other_mib,
            other_processes=snapshot.other_processes,
        )

    def stop(self) -> None:
        """Mark the end of the watch. Windows extending past this point
        cannot be `covered_whole_phase`."""
        self.stopped_at = self._clock()

    def measure_window(self, started_at: float, ended_at: float) -> WindowMeasurement:
        """The driver's account of one phase, with its coverage.

        A window is judged only by samples that fall inside it. A training
        peak must never be able to answer an inference question, and the
        window is what enforces that: samples outside it are not consulted,
        not borrowed, and not extrapolated from.
        """
        return measure_window(
            self._samples,
            started_at=started_at,
            ended_at=ended_at,
            interval_seconds=self.interval_seconds,
            watch_started_at=self.started_at,
            watch_stopped_at=self.stopped_at,
        )


def measure_window(
    samples: Sequence[TreeMemorySample],
    *,
    started_at: float,
    ended_at: float,
    interval_seconds: float,
    watch_started_at: float,
    watch_stopped_at: float | None,
) -> WindowMeasurement:
    """Reduce raw samples to one window's peak and coverage.

    Free of the sampler so it can be tested directly against hand-built
    series, and so C2-4 can re-derive a window from a persisted run without
    a live sampler.
    """
    in_window = [s for s in samples if started_at <= s.at <= ended_at]
    observed = [s for s in in_window if s.telemetry_available and s.own_tree_mib is not None]
    missed = len(in_window) - len(observed)

    peak_sample: TreeMemorySample | None = None
    for candidate in observed:
        if peak_sample is None or (candidate.own_tree_mib or 0) > (peak_sample.own_tree_mib or 0):
            peak_sample = candidate

    # The watch must have been running for the whole window. Starting late
    # or stopping early means part of the phase went unobserved, and an
    # unobserved part can hold the peak.
    covered = watch_started_at <= started_at and (
        watch_stopped_at is None or watch_stopped_at >= ended_at
    )

    own_pids: list[int] = []
    concurrent = 0
    for entry in observed:
        concurrent = max(concurrent, len(entry.own_processes))
        for pid in entry.own_pids:
            if pid not in own_pids:
                own_pids.append(pid)

    return WindowMeasurement(
        started_at=started_at,
        ended_at=ended_at,
        driver_tree_peak_mib=peak_sample.own_tree_mib if peak_sample is not None else None,
        coverage=SamplingCoverage(
            interval_seconds=interval_seconds,
            samples_taken=len(observed),
            samples_missed=missed,
            covered_whole_phase=covered,
            max_gap_seconds=_largest_gap(in_window, started_at, ended_at),
        ),
        own_pids=tuple(own_pids),
        max_concurrent_own_processes=concurrent,
        peak_sample=peak_sample,
    )


def _largest_gap(
    in_window: Sequence[TreeMemorySample], started_at: float, ended_at: float
) -> float:
    """The longest unwatched stretch, boundaries included.

    The edges count: a window whose only sample sits at its very start was
    unwatched for the rest of it, and a peak in that stretch is invisible.
    With no samples at all the gap is the whole window, which is the
    honest answer.
    """
    marks = sorted([started_at, *[s.at for s in in_window], ended_at])
    return round(max(b - a for a, b in itertools.pairwise(marks)), 6)


# NOTE, deliberate absence: there is no `device_identity_for(uuid)` helper
# here. One was written and removed. `device_identity_from_hardware` in
# `gpu_accounting` is the ONLY translation into a `DeviceIdentity`, and a
# guardrail test enforces that; a UUID-only constructor would have had to
# guess `physical_index=0`, which is the exact conflation that module warns
# against -- "filling in device 0 ... would silently conflate two cards of
# the same model, and every measurement attributed to the wrong one would
# look perfectly valid". Callers supply the identity discovery produced.
