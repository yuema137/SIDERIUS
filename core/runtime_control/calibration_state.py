"""Honest reporting of what the calibration registry actually holds.

V20 PR C1 / C-C7.

THE FAILURE THIS PREVENTS. The live v1 registry sat at 20 observations and 0
promotions for weeks, and nothing said so. "Calibration exists" was true;
"calibration is working" was not; and no artifact distinguished them. A
subsystem that has collected evidence but promoted none of it is not
calibrated -- it is a subsystem whose evidence has never met its own bar.

So `is_active` is defined by AUTHORITATIVE BUCKETS, never by record counts.
Twenty thousand observations and zero validated buckets is still inactive,
and the report says why rather than leaving the reader to infer it from a
number that looks reassuring.

REPORTING NEVER CHANGES THE WORKFLOW. Every entry point returns a report or a
report describing its own failure. A registry that is missing, locked or
corrupt produces `readable=False` with the reason attached -- it does not
raise into whatever asked, because asking "how is calibration doing?" must
never be able to cost a run its result.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict


class CalibrationStateReport(BaseModel):
    """What the registry holds, in the categories that actually differ.

    Counts are deliberately separate rather than a single "total": an
    operator asking why nothing is authoritative needs to see WHERE evidence
    is being lost -- quarantined for incomplete identity, ineligible for
    failure provenance, or eligible but not yet numerous or consistent
    enough to promote.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: False when the registry could not be read at all. Every count is then
    #: zero and `reasons` explains why, so an unreadable registry is never
    #: reported as an empty one.
    readable: bool = True

    observations_collected: int = 0
    #: Eligible to serve as calibration evidence at all: complete identity,
    #: measured (not failure) provenance.
    observations_eligible: int = 0
    #: Recorded but held back for incomplete identity (O-2). Evidence is
    #: kept; authority is refused.
    observations_quarantined: int = 0
    #: Eligible observations sitting in buckets that have not been promoted.
    observations_promotion_eligible: int = 0

    buckets_total: int = 0
    buckets_provisional: int = 0
    buckets_validated: int = 0
    #: Buckets with evidence that has NOT reached any promotion, with the
    #: reason each was refused -- the entry the v1 registry never had.
    buckets_unpromoted: int = 0
    rejected_promotion_reasons: tuple[str, ...] = ()

    reasons: tuple[str, ...] = ()

    @property
    def buckets_authoritative(self) -> int:
        """Only `validated` is calibration-authoritative (D4).

        `provisional` is deliberately excluded: it is a real state, but it is
        explicitly not authoritative, and counting it here is exactly how a
        report starts overstating what the subsystem can do.
        """
        return self.buckets_validated

    @property
    def is_active(self) -> bool:
        """Whether calibration can actually decide anything.

        Defined by authoritative buckets, never by how much evidence has
        been collected.
        """
        return self.readable and self.buckets_authoritative > 0

    def summary_line(self) -> str:
        """One line an operator can read without decoding the model."""
        if not self.readable:
            return f"calibration: UNREADABLE ({'; '.join(self.reasons) or 'no reason recorded'})"
        if not self.is_active:
            return (
                f"calibration: INACTIVE — {self.observations_collected} observation(s), "
                f"{self.buckets_validated} validated bucket(s)"
                + (f"; {'; '.join(self.reasons)}" if self.reasons else "")
            )
        return (
            f"calibration: ACTIVE — {self.buckets_validated} validated bucket(s) "
            f"from {self.observations_eligible} eligible observation(s)"
        )


def collect_calibration_state(
    registry: Any = None, *, root: Any = None, policy: Any = None
) -> CalibrationStateReport:
    """Read the registry and describe it. Never raises.

    A reporting failure must not alter the scientific workflow, so an
    unreadable registry becomes `readable=False` with its reason rather than
    an exception reaching the caller.

    `root` exists so that CONSTRUCTION is guarded too. `CalibrationRegistry`
    mkdirs its six subdirectories in `__init__`, so building one from a
    read-only or non-existent parent raises -- and a caller that constructs
    it before calling this function has already lost the guarantee this
    function advertises. Pass `root`; do not build the registry yourself.
    """
    try:
        from core.runtime_control.calibration_policy import (
            DEFAULT_POLICY,
            bucket_key,
            eligibility_problems,
            evaluate_bucket,
        )
        from core.runtime_control.calibration_registry import CalibrationRegistry

        if registry is not None:
            reg = registry
        else:
            reg = CalibrationRegistry(Path(root)) if root is not None else CalibrationRegistry()
        resolved_policy = policy if policy is not None else DEFAULT_POLICY

        observations = list(reg.iter_observations())
        quarantined = list(reg.iter_quarantined()) if hasattr(reg, "iter_quarantined") else []

        buckets: dict[str, list[Any]] = {}
        eligible = 0
        for obs in observations:
            if eligibility_problems(obs):
                continue
            eligible += 1
            buckets.setdefault(bucket_key(obs), []).append(obs)

        promoted_levels: dict[str, str] = {}
        for key in buckets:
            level, _ = reg.bucket_status(key)
            promoted_levels[key] = level

        provisional = sum(1 for v in promoted_levels.values() if v == "provisional")
        validated = sum(1 for v in promoted_levels.values() if v == "validated")

        refusals: list[str] = []
        unpromoted = 0
        promotion_eligible = 0
        generation = reg.load_manifest().generation
        for key, members in buckets.items():
            if promoted_levels.get(key) in ("provisional", "validated"):
                continue
            unpromoted += 1
            promotion_eligible += len(members)
            if evaluate_bucket(members, policy=resolved_policy, generation=generation) is None:
                refusals.append(
                    f"{key}: {len(members)} observation(s) — below the minimum "
                    f"({resolved_policy.provisional_min_observations}) or outside the "
                    f"consistency ratio ({resolved_policy.consistency_max_min_ratio})"
                )

        reasons: list[str] = []
        if not observations:
            reasons.append("registry holds no observations")
        elif validated == 0:
            reasons.append(
                "no bucket has reached `validated`; only validated evidence is "
                "calibration-authoritative (D4)"
            )
        if quarantined:
            reasons.append(f"{len(quarantined)} observation(s) quarantined for incomplete identity")

        return CalibrationStateReport(
            observations_collected=len(observations),
            observations_eligible=eligible,
            observations_quarantined=len(quarantined),
            observations_promotion_eligible=promotion_eligible,
            buckets_total=len(buckets),
            buckets_provisional=provisional,
            buckets_validated=validated,
            buckets_unpromoted=unpromoted,
            rejected_promotion_reasons=tuple(refusals),
            reasons=tuple(reasons),
        )
    except Exception as exc:
        return CalibrationStateReport(
            readable=False,
            reasons=(f"calibration registry could not be read ({type(exc).__name__}: {exc})",),
        )
