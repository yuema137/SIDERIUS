"""Whether a calibration may carry blocking authority (V20 PR C).

**The frozen principle** (operator, 2026-08-05):

> External occupancy does not invalidate a calibration. Only occupancy that
> CHANGES identity during the measurement, or that cannot be reliably
> attributed, makes a measurement unable to carry blocking authority.

The rule this replaces asked the wrong question:

```text
blocking = measured and not contended          # presence-based, WRONG
blocking = measured and validity == valid_current_conditions
```

`contended` was true whenever *any* foreign process held *any* memory,
however steadily. That is a statement about the device being busy, not about
the measurement being trustworthy — and it made a correct measurement taken
under a stable neighbour unusable, which aborted a real chain (Gate 2 attempt
1, 2026-08-05).

**T0, as ruled**: this is an IDENTITY-AND-ATTRIBUTION stability rule, **not**
a requirement that external attributed bytes stay numerically constant.

* the **presence** of external occupancy, at any size, is fine;
* **variation in bytes held by the same identified processes** is fine — it
  is the real current environment, to be measured rather than rejected;
* only **evidence-quality** failures remove blocking authority.

No numeric tolerance is defined here, deliberately: T0 is a predicate over
measured facts, not a tuned threshold. If it proves too strict, the
rejections will be visible in the recorded reasons and a byte tolerance can
be designed from that evidence.

**Validity does not imply admission.** A valid measurement may still reject a
candidate because free memory or measured performance is insufficient. This
module answers only "can this measurement be trusted to block?", never
"should this candidate run?".

**No new occupancy model.** `GpuAccountingSnapshot` (PR B) already carries
candidate-owned, external, unattributed and free memory with per-PID detail.
This module consumes it; it does not restate it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.runtime_control.gpu_accounting import GpuAccountingSnapshot

MeasurementValidity = Literal[
    "valid_current_conditions",
    "unstable_external_identity",
    "unattributed_occupancy_growth",
    "sampling_incomplete",
]

#: The only value that may carry blocking authority.
VALID: MeasurementValidity = "valid_current_conditions"


class OccupancyWindow(BaseModel):
    """A bounded series of accounting snapshots, plus its validity verdict.

    Deliberately thin: it holds the snapshots and the conservative
    aggregates a decision needs, and derives nothing that
    `GpuAccountingSnapshot` already states.
    """

    model_config = ConfigDict(frozen=True)

    snapshots: tuple[GpuAccountingSnapshot, ...]
    validity: MeasurementValidity
    reasons: tuple[str, ...] = ()

    #: The worst case in the window — what the candidate must actually fit
    #: into. `None` when telemetry never produced the figure.
    min_free_mib: int | None = Field(default=None, ge=0)
    #: The worst neighbour state observed in the window.
    max_external_mib: int | None = Field(default=None, ge=0)

    @property
    def blocking_capable(self) -> bool:
        """Whether a measurement taken over this window may block."""
        return self.validity == VALID


def _external_identity(snapshot: GpuAccountingSnapshot) -> frozenset[int]:
    return frozenset(p.pid for p in snapshot.other_processes)


def classify_measurement_validity(
    snapshots: Iterable[GpuAccountingSnapshot],
) -> tuple[MeasurementValidity, tuple[str, ...]]:
    """Classify a bounded observation window (T0).

    Order matters, and it is from most to least fundamental: a window that
    was not fully sampled cannot support any claim about stability, so
    `sampling_incomplete` is decided before identity or attribution.

    Args:
        snapshots: the bounded window, in observation order.

    Returns:
        `(validity, reasons)`. `reasons` is never empty for a non-valid
        verdict — an operator reading a refusal must be able to see which
        fact produced it.
    """
    window: Sequence[GpuAccountingSnapshot] = tuple(snapshots)

    # --- sampling completeness ------------------------------------------
    #
    # An empty window is not a clean device; it is an unobserved one. A
    # snapshot whose telemetry failed carries no numbers at all (the schema
    # enforces that), so it cannot contribute to any comparison below.
    if not window:
        return "sampling_incomplete", ("no occupancy samples were taken",)
    gaps = [i for i, s in enumerate(window) if not s.telemetry_available]
    if gaps:
        return "sampling_incomplete", (
            f"{len(gaps)} of {len(window)} samples had no telemetry "
            f"(indices {gaps}); an unobserved interval cannot support a "
            "stability claim",
        )

    # --- external identity stability (T0's core) -------------------------
    #
    # Identity, NOT bytes. The same neighbours holding a varying amount are
    # stable conditions; a neighbour arriving or leaving is a different
    # environment before and after, and a measurement spanning both
    # describes neither.
    identities = {_external_identity(s) for s in window}
    if len(identities) > 1:
        first = sorted(_external_identity(window[0]))
        arrived = sorted(set().union(*identities) - _external_identity(window[0]))
        departed = sorted(_external_identity(window[0]) - set().intersection(*identities))
        return "unstable_external_identity", (
            f"the external process set changed during the window "
            f"(started as {first}; joined {arrived}; left {departed}) — the "
            "conditions before and after are different environments",
        )

    # --- attribution completeness ---------------------------------------
    #
    # Growth in unattributed occupancy means bytes appeared that nobody can
    # account to a process — including a candidate child that was spawned
    # after the process tree was enumerated. Either way the window no longer
    # supports an attribution claim.
    #
    # GROWTH, not presence: a device may carry a constant unattributed
    # baseline (driver context, a graphics client), and that is part of the
    # stable conditions being measured.
    unattributed = [s.unattributed_mib for s in window if s.unattributed_mib is not None]
    if len(unattributed) != len(window):
        return "sampling_incomplete", (
            "a sample reported telemetry without an unattributed figure, so "
            "attribution completeness cannot be established",
        )
    if unattributed and max(unattributed) > unattributed[0]:
        return "unattributed_occupancy_growth", (
            f"unattributed GPU memory grew during the window "
            f"({unattributed[0]} -> {max(unattributed)} MiB); those bytes "
            "belong to no enumerated process, so neither the candidate's "
            "demand nor the neighbours' can be stated",
        )

    return VALID, ()


def build_occupancy_window(snapshots: Iterable[GpuAccountingSnapshot]) -> OccupancyWindow:
    """Classify a window and record the conservative aggregates with it.

    The aggregates are the worst case observed, not an average: a decision
    made from the mean of a varying environment is a decision about a moment
    that never occurred.
    """
    window = tuple(snapshots)
    validity, reasons = classify_measurement_validity(window)

    # Free memory is DERIVED here rather than read: `device_free_mib` lives
    # on `DeviceBaselineSnapshot`, not on `GpuAccountingSnapshot`, which
    # states used and total instead. Deriving it keeps this module on the
    # one snapshot type the calibration path actually has, rather than
    # requiring a second sample from a different producer.
    free = [
        s.device_total_mib - s.device_used_mib
        for s in window
        if s.device_total_mib is not None and s.device_used_mib is not None
    ]
    external = [s.other_mib for s in window if s.other_mib is not None]

    return OccupancyWindow(
        snapshots=window,
        validity=validity,
        reasons=reasons,
        min_free_mib=min(free) if free else None,
        max_external_mib=max(external) if external else None,
    )


def attribute_measured_failure(
    validity: MeasurementValidity,
) -> Literal["candidate", "insufficient_evidence"]:
    """Who owns a measured OOM or wall-cap failure (operator ruling).

    A failure is only the candidate's when the conditions around it were
    trustworthy:

    * stable, attributable occupancy and genuinely insufficient memory — a
      **valid current-condition rejection**. The measurement is good and the
      answer is no;
    * identity change, unattributed growth or incomplete sampling — **not a
      candidate rejection**. The evidence is insufficient to blame anyone,
      and charging the candidate for a neighbour's memory would reject a
      model for someone else's behaviour.

    This is attribution only. It moves no threshold, and it never turns a
    failure into a pass.
    """
    return "candidate" if validity == VALID else "insufficient_evidence"
