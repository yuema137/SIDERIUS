"""Did the environment change during the case, and did that change anything?

V20 PR C2, operator decisions 2026-08-04 and 2026-08-05. This module has now
been wrong twice in the same direction, and both corrections were the same
correction: **stop refusing on what was present, and start refusing on what
had an effect.**

CORRECTION 1 (2026-08-04) -- presence is not contamination.

```python
own = {os.getpid()}
contaminated = _foreign_processes(before, own) or _foreign_processes(after, own)
```

Three defects. It flagged *presence* rather than effect, though the
candidate's requirement is `own_tree_mib`, attributed by **ancestry**, so a
neighbour is excluded by construction -- and case c9 exists precisely to
prove that split works with an unrelated CUDA process resident. It used a
single PID as "ours", so the harness's own worker and training subprocess
counted as foreign. And it compared only two endpoint snapshots, so a
neighbour that started and exited between them was invisible.

CORRECTION 2 (2026-08-05) -- oscillation is not contamination either.

The replacement concatenated **both arms' series** and refused the pair when
`max - min >= 64 MiB`. Gate 2 Lite-A attempt 20 showed what that costs. Six
formal arms ran with a live neighbour oscillating 692-844 MiB, and all three
pairs were refused. The same artifacts refute the refusal:

```text
                    external MiB   range   candidate peak
p1 with_probe        824 - 824        0        1476
p1 without_probe     694 - 844      150        1476
p2 with_probe        704 - 704        0        1476
p2 without_probe     692 - 824      132        1476
p3 with_probe        704 - 824      120        1476
p3 without_probe     694 - 844      150        1476
```

Every arm measured **1476 MiB**. If the drift had affected the comparison,
six arms could not have agreed to the megabyte. The rule refused evidence
that itself proved the refusal wrong.

Two distinct errors produced that:

1. **Concatenation.** Taking one min/max across both arms cannot tell
   *oscillation within each arm* -- which affects both alike and leaves them
   comparable -- from *a shift between the arms*, which is the only thing
   that breaks a paired comparison. In pair 1 the with-probe arm was
   perfectly flat at 824 MiB; the 150 MiB "shift" was one arm's internal
   wobble, and the global range invented a difference between arms that did
   not exist.
2. **An absolute threshold.** 64 MiB is meaningless without reference to
   what is being measured. Against a 1476 MiB candidate with ~21 GiB of
   headroom, and attribution done by ancestry, 150 MiB of neighbour drift
   cannot change attribution, capacity, causality, or the peak. The
   threshold is removed; it is not replaced by a larger one.

WHAT SEPARATES NOW.

```text
environment_shift_observed   descriptive. Did the surroundings move at all?
                             Recorded always. Refuses nothing.
pair_comparable              the verdict. Could the surroundings have
                             changed the acceptance claim?
```

A shift may be observed while the pair remains perfectly comparable. That
sentence is the whole correction.

WHAT THE ACCEPTANCE PROPERTY IS. For Case 12 it is **GPU-memory peak and
admission equivalence** -- not wall-clock performance under compute
contention. A neighbour that slows both arms equally does not touch the
claim; one that changes what either arm *measured* does.

THREE QUESTIONS, STILL KEPT APART.

```text
what does the candidate need?   own_tree_mib, by ancestry
                                -> external processes NEVER added
can this device fit it now?     device used / free / external occupancy
                                -> external processes ALWAYS considered
did the environment shift?      per-arm membership and MiB over time
                                -> RECORDED; refuses only via its effect
```

NO CASE DEMANDS AN IDLE DEVICE. Dynamic measurement exists so a candidate
can be measured on the card **as it actually is**; a Gate that only runs on
a quiet GPU validates a laboratory rather than production.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

#: What a case needs from its surroundings.
#:
#: There is deliberately NO "quiet" requirement, and no numeric tolerance
#: anywhere in this module. Refusal is effect-based.
EnvironmentRequirement = Literal[
    #: The default. Attribution is by ancestry, so a neighbour is context.
    "stable",
    #: Paired arms. What matters is whether external activity could have
    #: changed the acceptance claim -- NOT whether the surroundings were
    #: still, and NOT whether some MiB figure moved.
    "comparable",
    #: A neighbour is expected and is part of the evidence (c9).
    "controlled_neighbour",
]

#: Paired comparisons.
COMPARABLE_REQUIRED_CASES: frozenset[str] = frozenset({"c12a", "c12b", "c12char"})

#: Cases where a neighbour is the point.
CONTROLLED_NEIGHBOUR_CASES: frozenset[str] = frozenset({"c9"})


def requirement_for_case(case: str) -> EnvironmentRequirement:
    """What surroundings this case needs. One place, so the matrix cannot
    drift from the rule that enforces it.

    Note what is absent: no case demands an idle device, and none demands a
    still one. c4 (timeout) verifies that a deadline stops the work and
    cleans up, not how fast anything runs; c5 (measured OOM) uses a
    configuration exceeding the whole card by construction. Both need their
    CAUSALITY attributable, which is checked on the result.
    """
    if case in CONTROLLED_NEIGHBOUR_CASES:
        return "controlled_neighbour"
    if case in COMPARABLE_REQUIRED_CASES:
        return "comparable"
    return "stable"


# ─────────────────────────────────────────────────────────────────────────
# One arm
# ─────────────────────────────────────────────────────────────────────────


class ArmEnvironment(BaseModel):
    """What one arm ran through, summarized from ITS OWN series.

    Per arm, deliberately. The pair verdict compares two of these; it never
    pools their samples, because a pooled range cannot distinguish a wobble
    inside one arm from a difference between them -- the exact conflation
    that refused all three of attempt 20's pairs.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    arm: str = Field(min_length=1)

    #: Every external PID seen during THIS arm, first-seen order.
    external_pids: tuple[int, ...] = ()
    min_external_mib: int | None = Field(default=None, ge=0)
    max_external_mib: int | None = Field(default=None, ge=0)
    median_external_mib: int | None = Field(default=None, ge=0)
    #: Max - min within this arm. Descriptive: a neighbour breathing does
    #: not, by itself, mean anything about this arm's measurement.
    external_range_mib: int | None = Field(default=None, ge=0)

    #: Tightest moment the arm had to fit into. `None` when the device total
    #: was not supplied -- absence, never a fabricated zero.
    min_free_device_mib: int | None = Field(default=None, ge=0)
    max_device_used_mib: int | None = Field(default=None, ge=0)

    #: THE measured quantity. Excludes every external process, always.
    candidate_peak_mib: int | None = Field(default=None, ge=0)
    admission_result: str | None = None
    #: Candidate/config/GPU identity token; arms must agree.
    identity: str | None = None

    sampling_complete: bool = False
    samples_observed: int = Field(default=0, ge=0)
    samples_missed: int = Field(default=0, ge=0)
    #: At least one own process was attributed while the arm ran. Without
    #: it the peak describes nothing.
    attribution_complete: bool = False

    #: The arm was killed from outside (quota watchdog, operator, OOM
    #: killer) rather than finishing or failing on its own terms.
    externally_terminated: bool = False
    #: The arm failed because the DEVICE could not fit it given everyone
    #: else -- an external-capacity cause, not a candidate property.
    capacity_induced_failure: bool = False

    @property
    def external_present(self) -> bool:
        return bool(self.external_pids)


def summarize_arm(
    arm: str,
    samples: Sequence[Any],
    *,
    candidate_peak_mib: int | None = None,
    admission_result: str | None = None,
    identity: str | None = None,
    sampling_complete: bool = False,
    samples_missed: int | None = None,
    externally_terminated: bool = False,
    capacity_induced_failure: bool = False,
    device_total_mib: int | None = None,
) -> ArmEnvironment:
    """Reduce ONE arm's timestamped series to its own environment record.

    Only successful samples contribute. A failed query is a *missed* sample,
    never read as "nobody was there": reading a gap as an empty device is
    how an arm would certify surroundings it never observed.
    """
    ordered = sorted(samples, key=lambda s: float(_get(s, "at", 0.0)))
    observed = [s for s in ordered if _get(s, "telemetry_available", False)]
    missed = samples_missed if samples_missed is not None else len(ordered) - len(observed)

    seen: list[int] = []
    for sample in observed:
        # `_get` at BOTH levels: the nested entries are `ProcessOccupancy`
        # objects live and plain dicts on replay from an artifact, and
        # reaching for `.pid` works only on the first.
        rows = _get(sample, "other_processes", ()) or ()
        for pid in sorted({int(_get(p, "pid")) for p in rows if _get(p, "pid") is not None}):
            if pid not in seen:
                seen.append(pid)

    externals = [int(v) for s in observed if (v := _get(s, "other_mib", None)) is not None]
    useds = [int(v) for s in observed if (v := _get(s, "device_used_mib", None)) is not None]
    owns = [int(v) for s in observed if (v := _get(s, "own_tree_mib", None)) is not None]

    free = None
    if device_total_mib is not None and useds:
        free = max(device_total_mib - max(useds), 0)

    return ArmEnvironment(
        arm=arm,
        external_pids=tuple(seen),
        min_external_mib=min(externals) if externals else None,
        max_external_mib=max(externals) if externals else None,
        median_external_mib=int(statistics.median(externals)) if externals else None,
        external_range_mib=(max(externals) - min(externals)) if externals else None,
        min_free_device_mib=free,
        max_device_used_mib=max(useds) if useds else None,
        candidate_peak_mib=candidate_peak_mib,
        admission_result=admission_result,
        identity=identity,
        sampling_complete=sampling_complete,
        samples_observed=len(observed),
        samples_missed=max(missed, 0),
        attribution_complete=any(v > 0 for v in owns),
        externally_terminated=externally_terminated,
        capacity_induced_failure=capacity_induced_failure,
    )


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """Read a field from a Pydantic sample or a plain dict alike.

    The harness holds `TreeMemorySample`s; a replay from an artifact holds
    dicts. One reader, so a regression fixture exercises the same code the
    Gate runs rather than a parallel path.
    """
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


# ─────────────────────────────────────────────────────────────────────────
# The pair
# ─────────────────────────────────────────────────────────────────────────


class PairComparability(BaseModel):
    """Whether two arms may be compared, and everything that decided it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case: str = Field(min_length=1)
    requirement: EnvironmentRequirement
    arms: tuple[ArmEnvironment, ArmEnvironment]

    #: DESCRIPTIVE. The surroundings moved -- membership changed, or a
    #: neighbour's occupancy varied, in either arm. Recorded always,
    #: refuses nothing on its own.
    environment_shift_observed: bool
    shift_detail: str = ""

    #: THE VERDICT. False only when external activity could have changed the
    #: acceptance claim.
    pair_comparable: bool
    blocking_reasons: tuple[str, ...] = ()
    detail: str = ""

    @property
    def acceptable(self) -> bool:
        """Alias kept for the harness and its artifacts."""
        return self.pair_comparable


def assess_pair_comparability(
    first: ArmEnvironment,
    second: ArmEnvironment,
    *,
    case: str,
) -> PairComparability:
    """Could external activity have changed what this pair claims?

    Returns a VALUE. An incomparable pair is an expected outcome of
    checking, not an error in checking.

    THE ACCEPTANCE PROPERTY for Case 12 is GPU-memory peak and admission
    equivalence. So the question is never "was the card busy" but "could the
    surroundings have moved the peak or the verdict".

    The last rule is the subtle one and it is deliberately NOT circular. If
    the two arms measured the SAME peak and the SAME admission, external
    activity demonstrably did not change them -- whatever it was doing. If
    they DIFFER, the difference is only unattributable when the arms also
    met materially different conditions; when conditions matched, a
    difference is a real probe effect and the pair is comparable, which is
    exactly what lets Case 12 still detect perturbation.
    """
    arms = (first, second)
    blocking: list[str] = []

    for a in arms:
        if not a.attribution_complete:
            blocking.append(
                f"{a.arm}: no candidate-owned process was ever attributed, so its "
                "peak describes nothing"
            )
        if not a.sampling_complete:
            blocking.append(
                f"{a.arm}: sampling incomplete ({a.samples_missed} missed of "
                f"{a.samples_observed + a.samples_missed}); a peak may have risen unwatched"
            )
        if a.externally_terminated:
            blocking.append(
                f"{a.arm}: terminated from outside, so it never reached its own outcome"
            )
        if a.capacity_induced_failure:
            blocking.append(
                f"{a.arm}: failed because the DEVICE could not fit it given other "
                "tenants -- an external-capacity cause, not a candidate property"
            )
        if a.min_free_device_mib is not None and a.min_free_device_mib <= 0:
            blocking.append(f"{a.arm}: device free memory reached zero during the arm")

    if first.identity is None or second.identity is None:
        blocking.append("an arm carries no candidate/configuration identity")
    elif first.identity != second.identity:
        blocking.append(
            f"the arms measured different candidates or configurations "
            f"({first.identity!r} vs {second.identity!r})"
        )

    conditions_differ, condition_note = _conditions_materially_differ(first, second)
    peaks_agree = (
        first.candidate_peak_mib is not None
        and first.candidate_peak_mib == second.candidate_peak_mib
    )
    admission_agree = first.admission_result == second.admission_result

    if (not peaks_agree or not admission_agree) and conditions_differ:
        changed = []
        if not peaks_agree:
            changed.append(f"peak {first.candidate_peak_mib} vs {second.candidate_peak_mib} MiB")
        if not admission_agree:
            changed.append(f"admission {first.admission_result!r} vs {second.admission_result!r}")
        blocking.append(
            f"the arms disagree ({'; '.join(changed)}) AND met materially different "
            f"external conditions ({condition_note}), so the difference cannot be "
            "attributed to the probe"
        )

    shift, shift_detail = _describe_shift(first, second)

    if blocking:
        detail = (
            f"case {case}: external activity could have changed the acceptance claim; "
            "preserve the artifact and rerun only this pair"
        )
    elif shift:
        detail = (
            "the surroundings moved but the acceptance claim did not: "
            f"both arms measured {first.candidate_peak_mib} MiB with "
            f"admission {first.admission_result!r}. Recorded as context, not contamination"
        )
    else:
        detail = "external conditions were steady and the arms agree"

    return PairComparability(
        case=case,
        requirement=requirement_for_case(case),
        arms=arms,
        environment_shift_observed=shift,
        shift_detail=shift_detail,
        pair_comparable=not blocking,
        blocking_reasons=tuple(blocking),
        detail=detail,
    )


def _conditions_materially_differ(a: ArmEnvironment, b: ArmEnvironment) -> tuple[bool, str]:
    """Did the two arms meet conditions different enough to explain a
    disagreement between them?

    Compared as OVERLAPPING RANGES rather than as a pooled min/max. Two arms
    whose external occupancy ranges overlap experienced the same band of
    conditions, however much either wobbled inside it. Attempt 20's pair 1
    -- one arm flat at 824 MiB, the other spanning 694-844 -- overlaps, and
    is not a difference.
    """
    if a.max_external_mib is None or b.max_external_mib is None:
        # One arm saw no neighbour at all and the other did: a real
        # asymmetry, but only reported here. Whether it MATTERED is decided
        # by the caller, from the arms' results.
        if a.external_present != b.external_present:
            return True, (
                f"{a.arm} external={'present' if a.external_present else 'absent'}, "
                f"{b.arm} external={'present' if b.external_present else 'absent'}"
            )
        return False, "neither arm observed external occupancy"

    lo = max(int(a.min_external_mib or 0), int(b.min_external_mib or 0))
    hi = min(int(a.max_external_mib), int(b.max_external_mib))
    if lo > hi:
        return True, (
            f"{a.arm} ran at {a.min_external_mib}-{a.max_external_mib} MiB and "
            f"{b.arm} at {b.min_external_mib}-{b.max_external_mib} MiB -- no overlap"
        )
    return False, (
        f"external occupancy bands overlap ({a.arm} {a.min_external_mib}-"
        f"{a.max_external_mib}, {b.arm} {b.min_external_mib}-{b.max_external_mib} MiB)"
    )


def _describe_shift(a: ArmEnvironment, b: ArmEnvironment) -> tuple[bool, str]:
    """Purely descriptive: did anything move? No threshold, by design.

    Reporting a 4 MiB wobble is harmless because nothing is refused on it.
    A threshold here would be the same mistake at a smaller number.
    """
    notes: list[str] = []
    for arm in (a, b):
        if arm.external_range_mib:
            notes.append(
                f"{arm.arm} neighbour varied {arm.min_external_mib}-"
                f"{arm.max_external_mib} MiB (range {arm.external_range_mib})"
            )
    only_a = tuple(p for p in a.external_pids if p not in b.external_pids)
    only_b = tuple(p for p in b.external_pids if p not in a.external_pids)
    if only_a or only_b:
        notes.append(f"membership differs: only in {a.arm}={only_a}, only in {b.arm}={only_b}")
    return bool(notes), "; ".join(notes) if notes else "no external movement observed"


# ─────────────────────────────────────────────────────────────────────────
# Single-arm cases
# ─────────────────────────────────────────────────────────────────────────


class EnvironmentAssessment(BaseModel):
    """Whether a single (unpaired) case's surroundings permit its claim."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case: str = Field(min_length=1)
    requirement: EnvironmentRequirement
    arm: ArmEnvironment
    acceptable: bool
    environment_shift_observed: bool
    reason: str = ""


def assess_environment(arm: ArmEnvironment, *, case: str) -> EnvironmentAssessment:
    """A single case's surroundings. Effect-based, like the pair rule.

    `stable` no longer means "nothing moved" -- it means nothing moved that
    could invalidate the measurement. What invalidates it is the same short
    list: attribution, sampling, external termination, capacity causality.
    """
    need = requirement_for_case(case)
    shift = bool(arm.external_range_mib) or arm.external_present

    if need == "controlled_neighbour" and not arm.external_present:
        return EnvironmentAssessment(
            case=case,
            requirement=need,
            arm=arm,
            acceptable=False,
            environment_shift_observed=shift,
            reason=(
                f"case {case} requires a controlled neighbouring CUDA process as its "
                "evidence, and none was observed"
            ),
        )

    problems: list[str] = []
    if not arm.attribution_complete:
        problems.append("no candidate-owned process was attributed")
    if not arm.sampling_complete:
        problems.append(f"sampling incomplete ({arm.samples_missed} missed)")
    if arm.externally_terminated:
        problems.append("the arm was terminated from outside")
    if arm.capacity_induced_failure:
        problems.append("the failure came from device capacity, not the candidate")

    if problems:
        return EnvironmentAssessment(
            case=case,
            requirement=need,
            arm=arm,
            acceptable=False,
            environment_shift_observed=shift,
            reason="; ".join(problems),
        )
    return EnvironmentAssessment(
        case=case,
        requirement=need,
        arm=arm,
        acceptable=True,
        environment_shift_observed=shift,
        reason=(
            f"external occupancy {arm.min_external_mib}-{arm.max_external_mib} MiB recorded "
            "as headroom context; never counted in the candidate's requirement"
            if arm.external_present
            else "no external occupancy observed"
        ),
    )
