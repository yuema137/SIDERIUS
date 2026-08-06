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

#: What was ELSE on the device. Context and provenance — never a validity
#: criterion. `unknown` means telemetry could not say, which is itself a fact
#: rather than a verdict.
ExternalActivity = Literal["absent", "stable", "variable", "unknown"]

MeasurementValidity = Literal[
    # The measurement can be trusted.
    "valid_current_conditions",
    # --- integrity failures, each naming what actually broke -------------
    "candidate_attribution_failed",
    "device_identity_unavailable",
    "sampling_incomplete",
    "probe_lifecycle_incomplete",
    "measurement_invariant_failed",
]

#: The only value that may carry blocking authority.
VALID: MeasurementValidity = "valid_current_conditions"

#: Reasons that were REMOVED (operator, 2026-08-06). Kept as a named set so a
#: regression that reintroduces one is obvious in review, and so historical
#: artifacts remain readable.
#:
#: External activity is CONTEXT. None of these may ever be a direct invalidity
#: reason: an external process exists; it is unregistered; the external PID
#: set changed; external memory fluctuated; the workload is bursty.
#:
#: `unattributed_occupancy_growth` survives only in re-grounded form, as
#: `candidate_attribution_failed`: growth invalidates when it makes candidate
#: demand INSEPARABLE, never because a neighbour grew.
RETIRED_PRESENCE_REASONS: frozenset[str] = frozenset(
    {"unstable_external_identity", "unattributed_occupancy_growth"}
)


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
    # enforces that), so it cannot support any attribution claim.
    if not window:
        return "sampling_incomplete", ("no occupancy samples were taken",)
    gaps = [i for i, s in enumerate(window) if not s.telemetry_available]
    if gaps:
        return "sampling_incomplete", (
            f"{len(gaps)} of {len(window)} samples had no telemetry "
            f"(indices {gaps}); an unobserved interval cannot support an "
            "attribution claim",
        )

    # --- device identity --------------------------------------------------
    #
    # A measurement that cannot say WHICH device it describes cannot be
    # compared with anything.
    devices = {s.device.uuid for s in window}
    if len(devices) > 1:
        return "device_identity_unavailable", (
            f"the window spans more than one device ({sorted(devices)}); a "
            "single measurement cannot describe two accelerators",
        )

    # --- candidate attribution -------------------------------------------
    #
    # THE integrity question: can the candidate's own demand be separated
    # from everyone else's? Note what is NOT asked — whether anyone else is
    # present, whether they are registered, whether their PID set changed,
    # whether their memory moved. Those are recorded by
    # `summarise_external_activity` as CONTEXT (operator, 2026-08-06).
    own = [s.own_tree_mib for s in window if s.own_tree_mib is not None]
    if len(own) != len(window):
        return "candidate_attribution_failed", (
            "a sample reported telemetry without a candidate process-tree "
            "figure, so the candidate's own demand cannot be separated from "
            "other demand",
        )

    unattributed = [s.unattributed_mib for s in window if s.unattributed_mib is not None]
    if len(unattributed) != len(window):
        return "candidate_attribution_failed", (
            "a sample reported telemetry without an unattributed figure, so "
            "the share of memory belonging to no enumerated process — and "
            "therefore the candidate's separable demand — is unknown",
        )

    # Growth in UNATTRIBUTED memory invalidates only because it means bytes
    # exist that belong to no enumerated process, so candidate demand can no
    # longer be stated. This is the re-grounded form of the retired
    # `unattributed_occupancy_growth`: the failure is ATTRIBUTION, never the
    # fact that a neighbour grew. A neighbour whose OWN attributed memory
    # grows leaves this untouched.
    if unattributed and max(unattributed) > unattributed[0]:
        return "candidate_attribution_failed", (
            f"unattributed GPU memory grew during the window "
            f"({unattributed[0]} -> {max(unattributed)} MiB): those bytes "
            "belong to no enumerated process, so the candidate's own demand "
            "can no longer be separated from unaccounted usage",
        )

    return VALID, ()


class ExternalActivityObservation(BaseModel):
    """What ELSE was on the device — recorded, never a validity criterion.

    Every field here is an observation. None of them may decide validity or
    readiness (operator, 2026-08-06): presence, non-registration, PID-set
    change, memory fluctuation and burstiness are facts about the
    environment, not defects in the measurement.

    Registration appears only as the split between `registered_pids` and
    `unregistered_pids`. That split is PROVENANCE: given identical measured
    facts, a registered and an unregistered neighbour must produce identical
    validity and admission outcomes.
    """

    model_config = ConfigDict(frozen=True)

    activity: ExternalActivity = "unknown"
    #: Peers the launcher explicitly declared. Labelling only.
    registered_pids: tuple[int, ...] = ()
    #: Everything else on the device. NOT a defect.
    unregistered_pids: tuple[int, ...] = ()
    #: Whether the external PID set changed across the window. Recorded so
    #: the environment is described honestly; it does not invalidate anything.
    pid_set_changed: bool = False
    external_mib_min: int | None = Field(default=None, ge=0)
    external_mib_max: int | None = Field(default=None, ge=0)
    external_mib_latest: int | None = Field(default=None, ge=0)

    @property
    def present(self) -> bool:
        return bool(self.registered_pids or self.unregistered_pids)


def summarise_external_activity(
    snapshots: Iterable[GpuAccountingSnapshot],
    *,
    registered_pids: Iterable[int] = (),
) -> ExternalActivityObservation:
    """Describe external activity across a window. Pure observation.

    Deliberately returns no verdict: a caller that wants to know whether the
    measurement can be trusted asks `classify_measurement_validity`, and a
    caller that wants to know whether the candidate may run asks admission.
    """
    window = tuple(snapshots)
    usable = [s for s in window if s.telemetry_available]
    if not usable:
        return ExternalActivityObservation(activity="unknown")

    registered = set(registered_pids)
    per_sample_sets: list[frozenset[int]] = []
    seen_registered: set[int] = set()
    seen_unregistered: set[int] = set()
    totals: list[int] = []

    for snap in usable:
        pids = frozenset(p.pid for p in snap.other_processes)
        per_sample_sets.append(pids)
        seen_registered |= pids & registered
        seen_unregistered |= pids - registered
        if snap.other_mib is not None:
            totals.append(snap.other_mib)

    if not seen_registered and not seen_unregistered and not any(totals):
        return ExternalActivityObservation(activity="absent")

    changed = len(set(per_sample_sets)) > 1
    varied = bool(totals) and min(totals) != max(totals)

    return ExternalActivityObservation(
        # `variable` covers both a moving PID set and moving bytes. Both are
        # ordinary shared-device behaviour.
        activity="variable" if (changed or varied) else "stable",
        registered_pids=tuple(sorted(seen_registered)),
        unregistered_pids=tuple(sorted(seen_unregistered)),
        pid_set_changed=changed,
        external_mib_min=min(totals) if totals else None,
        external_mib_max=max(totals) if totals else None,
        external_mib_latest=totals[-1] if totals else None,
    )


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
