"""
agent/skills/evaluate_time_skill/trigger_policy.py

Non-formal estimation trigger policy (RT3, design §3 table).

Decides whether a NON-formal (trial) round may reuse a stored
historical unit time instead of running the real-dataset warm-up.
Formal rounds never consult this policy — their sole authority is the
in-subprocess measured verification (§2.1/§3).

The §3 matrix, verbatim:

| Condition (non-formal)                                | Action          |
|-------------------------------------------------------|-----------------|
| Store hit (exact §6a key) and n_steps ≤ 50k and trial  | reuse store     |
| Novel plugin / unseen family fingerprint (no store hit)| warm-up required|
| batch_size < 4 or > 512; seg_size < 2500 or > 40000    | warm-up required|
| n_steps > 50,000                                       | warm-up required|
| static vs store estimates disagree > 3×                | warm-up required|

Thresholds are provisional §3 values, overridable per call — never a
hidden protocol constant.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: §3 provisional thresholds.
STORE_REUSE_MAX_STEPS: int = 50_000
BATCH_SIZE_BOUNDS: tuple[int, int] = (4, 512)
SEG_SIZE_BOUNDS: tuple[int, int] = (2500, 40_000)
STATIC_STORE_DISAGREE_FACTOR: float = 3.0


class NonFormalEstimationDecision(BaseModel):
    """Outcome of the §3 non-formal screening matrix."""

    model_config = ConfigDict(frozen=True)

    action: Literal["reuse_store", "warmup_required"]
    reasons: list[str] = Field(
        default_factory=list,
        description="Every §3 row that forced warm-up (empty on reuse).",
    )
    store_unit_ms: float | None = Field(default=None, gt=0.0)


def decide_nonformal_estimation(
    *,
    is_trial_round: bool,
    n_steps: int,
    batch_size: int,
    seg_size: int,
    store_prior_unit_ms: float | None,
    static_ms_per_step: float | None,
    max_steps: int = STORE_REUSE_MAX_STEPS,
    batch_bounds: tuple[int, int] = BATCH_SIZE_BOUNDS,
    seg_bounds: tuple[int, int] = SEG_SIZE_BOUNDS,
    disagree_factor: float = STATIC_STORE_DISAGREE_FACTOR,
) -> NonFormalEstimationDecision:
    """Apply the §3 non-formal matrix.

    Args:
        is_trial_round:      Non-formal trial round? Formal rounds must
                             not call this (they always live-verify);
                             passing False forces warm-up defensively.
        n_steps:             Resolved optimizer-step count (§1.2).
        batch_size/seg_size: Plan values.
        store_prior_unit_ms: A VALID §6b store lookup's unit time, or
                             ``None`` (absent/stale/drift/mismatch —
                             the "novel plugin / unseen fingerprint"
                             row collapses here: no valid hit → no
                             reuse).
        static_ms_per_step:  Static prior for the §3 disagreement row
                             (``None`` skips that row).
    """
    reasons: list[str] = []
    if not is_trial_round:
        reasons.append("not a trial round — non-formal store reuse never applies")
    if store_prior_unit_ms is None:
        reasons.append("no valid store hit for the exact §6a key (novel/unseen/invalidated)")
    if n_steps > max_steps:
        reasons.append(f"n_steps {n_steps} > {max_steps} store-reuse ceiling")
    lo_b, hi_b = batch_bounds
    if not (lo_b <= batch_size <= hi_b):
        reasons.append(f"batch_size {batch_size} outside [{lo_b}, {hi_b}]")
    lo_s, hi_s = seg_bounds
    if not (lo_s <= seg_size <= hi_s):
        reasons.append(f"seg_size {seg_size} outside [{lo_s}, {hi_s}]")
    if (
        store_prior_unit_ms is not None
        and static_ms_per_step is not None
        and static_ms_per_step > 0
    ):
        ratio = max(store_prior_unit_ms, static_ms_per_step) / max(
            min(store_prior_unit_ms, static_ms_per_step), 1e-12
        )
        if ratio > disagree_factor:
            reasons.append(
                f"static ({static_ms_per_step:.2f} ms) vs store "
                f"({store_prior_unit_ms:.2f} ms) disagree {ratio:.1f}x > "
                f"{disagree_factor:g}x"
            )
    if reasons:
        return NonFormalEstimationDecision(action="warmup_required", reasons=reasons)
    return NonFormalEstimationDecision(action="reuse_store", store_unit_ms=store_prior_unit_ms)
