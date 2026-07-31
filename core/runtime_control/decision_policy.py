"""Shared runtime decision policy (C4).

Implements the operator-resolved §7.4 decision matrix
(runtime_estimation_and_calibration.md) as a TABLE-DRIVEN policy: the
estimator provides evidence (`RuntimeEstimate`), this policy decides —
no consumer computes blocking authority privately (enforced at C8
rewiring; until then this module is additive).

Decision vocabulary (operator-approved):

* ``ADVISORY`` — informational only; execution proceeds unaffected.
* ``REQUEST_PROBE`` — evidence too weak to decide; a bounded live probe
  of the implemented candidate should be run (C6 producer).
* ``ALLOW`` — proceed (possibly with warnings).
* ``REJECT`` — reject the CURRENT candidate or stage transition; the
  workflow remains operational (retries/next candidates proceed).
* ``ABORT`` — the workflow cannot safely continue (invariant breakage,
  unusable configuration). A normal over-budget candidate NEVER maps to
  ABORT.

Authority rules enforced here (in addition to the type-level derivation
in ``estimate_types``):

* static/historical priors (tiers 0-1) can never produce REJECT or
  ABORT from a runtime budget — at most ADVISORY / REQUEST_PROBE;
* an uncalibrated clean live probe may REJECT only on measured hard
  evidence (OOM, wall-cap hit) or when even its OPTIMISTIC bound
  (``lower_seconds``) exceeds the budget — no new numeric thresholds
  are introduced (D3/D4/D5 remain open for C7);
* a contended probe cannot be the sole formal blocker (→ ADVISORY with
  a clean-retry request when probing is available);
* VRAM authority is post-implementation ONLY (operator decision):
  a deterministic capacity check may REJECT only when computed from
  REALIZED model properties; LLM-authored estimates are advisory;
* measured probe OOM / measured peak-VRAM violation may REJECT.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.runtime_control.estimate_types import (
    RuntimeEstimate,
    evidence_rank,
)
from core.runtime_control.identity import component_identity
from core.runtime_control.records import MEASUREMENT_BACKED_SOURCES

RuntimeDecisionKind = Literal["ADVISORY", "REQUEST_PROBE", "ALLOW", "REJECT", "ABORT"]

#: Stage of the candidate relative to implementation — VRAM authority is
#: post-implementation only (operator decision, D2 placement).
CandidateStage = Literal["proposal", "post_implementation"]

MeasuredFailure = Literal["oom", "wall_cap"]

#: State of the evidence channel itself (C8, operator decision 2026-07-30).
#: Distinguishes "the candidate is bad" from "we cannot obtain evidence":
#:
#: * ``ok``                     — evidence is whatever the estimate says;
#: * ``probe_absent``           — no probe has run / no valid probe record
#:                                exists yet for this candidate;
#: * ``infrastructure_failure`` — the probe could not be produced or
#:                                interpreted at all (configuration,
#:                                data path, plugin loading, registry
#:                                corruption, evidence-channel failure).
EvidenceChannel = Literal["ok", "probe_absent", "infrastructure_failure"]


class RuntimeBudget(BaseModel):
    model_config = ConfigDict(frozen=True)

    time_seconds: float | None = Field(default=None, gt=0.0)
    vram_gb: float | None = Field(default=None, gt=0.0)


class RuntimeMode(BaseModel):
    model_config = ConfigDict(frozen=True)

    phase: Literal["proposal", "trial", "formal"]
    candidate_stage: CandidateStage
    probe_available: bool = Field(
        default=False,
        description="Whether a bounded live probe of the implemented "
        "candidate can be requested (C6 producer present + executable "
        "model available).",
    )


class CapacityCheck(BaseModel):
    """Deterministic memory-accounting result (NOT a runtime estimate).

    ``realized=True`` means the accounting was computed from the
    implemented model's realized properties (§16.7); ``False`` means it
    derives from LLM-authored numbers and carries no blocking authority
    (operator decision)."""

    model_config = ConfigDict(frozen=True)

    required_gb: float = Field(gt=0.0)
    available_gb: float = Field(gt=0.0)
    realized: bool

    @property
    def impossible(self) -> bool:
        return self.required_gb > self.available_gb


class RuntimeDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: RuntimeDecisionKind
    reasons: tuple[str, ...]
    evidence_provenance: str
    evidence_rank: int


#: Behavioral payload rows for the identity hash — the complete resolved
#: §7.4 matrix in declarative form. Editing ANY entry changes the policy
#: identity; formatting/comment changes do not.
_POLICY_MATRIX: dict[str, dict[str, str]] = {
    "static_prior": {
        "proposal": "advisory_only",
        "trial": "cannot_block",
        "formal": "cannot_block",
        "watchdog": "never_used",
    },
    "historical_prior_only": {
        "proposal": "advisory_or_request_probe",
        "trial": "cannot_block_alone",
        "formal": "cannot_block_alone",
        "watchdog": "never_used_alone",
    },
    "live_probe_contended": {
        "proposal": "request_clean_retry_or_conservative",
        "trial": "conditional",
        "formal": "cannot_be_sole_formal_blocker",
        "watchdog": "temporary_conservative_deadline_only",
    },
    "live_probe_clean_uncalibrated": {
        "proposal": "may_block_on_measured_oom_or_hard_cap",
        "trial": "conditional",
        "formal": "conditional_with_explicit_uncertainty",
        "watchdog": "may_protect_execution",
    },
    "calibrated_live_probe": {
        "proposal": "may_support_blocking",
        "trial": "may_block",
        "formal": "may_block",
        "watchdog": "yes",
    },
    "in_process_verification": {
        "proposal": "not_applicable_before_implementation",
        "trial": "record_or_adjust",
        "formal": "may_block",
        "watchdog": "yes",
    },
    "complete_observation": {
        "proposal": "future_context",
        "trial": "future_context",
        "formal": "future_context",
        "watchdog": "calibration_update",
    },
}

_BEHAVIORAL_RULES: dict[str, str | list[str]] = {
    "static_prior_advisory_only": "static estimates never revise or reject proposals",
    "historical_prior_non_blocking": "historical evidence alone never blocks a novel candidate",
    "unsupported_extrapolation": "may not block without a live probe",
    "contended_not_clean_calibration": "contended evidence never updates clean calibration",
    "vram_authority": "post_implementation_only: realized deterministic accounting, measured probe OOM, measured peak violation",
    "reject_vs_abort": "REJECT is candidate/stage-local; ABORT only for unsafe-workflow states; over-budget never ABORTs",
    "uncalibrated_probe_time_block_rule": "optimistic-bound (lower_seconds) must exceed budget to REJECT on time alone",
    "concurrency_categories": [
        "single_candidate_idle",
        "pairwise_expected_peer",
        "foreign_contended",
        "unknown_contention",
    ],
    # C8 (operator, 2026-07-30): missing evidence vs broken evidence channel.
    "formal_probe_absent": "REQUEST_PROBE — never a silent static/historical fallback",
    "infrastructure_failure": "ABORT — evidence-channel failure is not a candidate verdict",
    "measured_candidate_failure": "REJECT — oom / wall_cap / deterministic capacity violation",
}

_POLICY_SEMVER = "1.0.0"


def policy_identity_payload() -> dict:
    """The behaviorally relevant configuration — see the identity module
    docstring for exclusions (no paths/hardware/timestamps/etc.)."""
    from core.runtime_control.estimate_types import _EVIDENCE_TIER

    return {
        "decision_vocabulary": ["ADVISORY", "REQUEST_PROBE", "ALLOW", "REJECT", "ABORT"],
        "evidence_tiers": dict(_EVIDENCE_TIER),
        "precedence_order": [
            name for name, _ in sorted(_EVIDENCE_TIER.items(), key=lambda kv: (kv[1], kv[0]))
        ],
        "eligibility_rules": {
            "advisory": "always",
            "blocking": "measurement_backed_and_not_contended",
            "formal": "blocking_and_verification_passed_and_steady_state",
        },
        "policy_matrix": _POLICY_MATRIX,
        "behavioral_rules": _BEHAVIORAL_RULES,
        "defaults": {
            "probe_available": False,
            "candidate_stage_vram_authority": "post_implementation",
        },
    }


class RuntimeDecisionPolicy:
    """The one shared decision path (§7.4). Stateless; identity-stable."""

    def __init__(self) -> None:
        self.identity = component_identity(
            "runtime_decision_policy", _POLICY_SEMVER, policy_identity_payload()
        )

    # ------------------------------------------------------------------
    def decide(
        self,
        estimate: RuntimeEstimate,
        budget: RuntimeBudget,
        mode: RuntimeMode,
        *,
        capacity_check: CapacityCheck | None = None,
        measured_failure: MeasuredFailure | None = None,
        evidence_channel: EvidenceChannel = "ok",
    ) -> RuntimeDecision:
        reasons: list[str] = []

        def _decision(kind: RuntimeDecisionKind) -> RuntimeDecision:
            return RuntimeDecision(
                kind=kind,
                reasons=tuple(reasons),
                evidence_provenance=estimate.provenance,
                evidence_rank=estimate.rank,
            )

        # ── Evidence channel before evidence content (C8) ────────────────
        # A broken channel is an EXECUTION-SYSTEM failure, not a verdict on
        # the candidate: it can never be answered by falling back to a
        # prior, and it is never a REJECT.
        if evidence_channel == "infrastructure_failure":
            reasons.append(
                "the runtime evidence channel failed (configuration, data "
                "path, plugin loading, registry, or probe interpretation) — "
                "no runtime decision can be made from priors"
            )
            return _decision("ABORT")

        # ── Measured hard failures: strongest candidate-local evidence ──
        if measured_failure is not None:
            if estimate.provenance not in MEASUREMENT_BACKED_SOURCES:
                reasons.append(
                    f"measured_failure={measured_failure!r} reported with "
                    f"non-measured provenance {estimate.provenance!r} — "
                    "invalid evidence combination"
                )
                return _decision("ABORT")  # policy misuse: unsafe to trust inputs
            reasons.append(f"measured {measured_failure} on the implemented candidate")
            return _decision("REJECT")

        # ── Deterministic capacity accounting (VRAM authority placement) ──
        if capacity_check is not None and capacity_check.impossible:
            if capacity_check.realized and mode.candidate_stage == "post_implementation":
                reasons.append(
                    f"deterministic capacity impossibility: requires "
                    f"{capacity_check.required_gb:.2f} GB > available "
                    f"{capacity_check.available_gb:.2f} GB (realized accounting)"
                )
                return _decision("REJECT")
            reasons.append(
                "capacity concern from non-realized (LLM-authored) numbers "
                "or pre-implementation stage — advisory only (operator "
                "decision: VRAM authority is post-implementation)"
            )
            return _decision("ADVISORY")

        # ── Measured peak-VRAM violation (probe-measured, on the estimate) ──
        if (
            budget.vram_gb is not None
            and estimate.peak_vram_gb is not None
            and estimate.peak_vram_gb > budget.vram_gb
        ):
            if estimate.blocking_eligible:
                reasons.append(
                    f"measured peak VRAM {estimate.peak_vram_gb:.2f} GB exceeds "
                    f"budget {budget.vram_gb:.2f} GB"
                )
                return _decision("REJECT")
            reasons.append(
                f"projected peak VRAM {estimate.peak_vram_gb:.2f} GB exceeds "
                f"budget {budget.vram_gb:.2f} GB (non-blocking provenance — advisory)"
            )
            return _decision("ADVISORY")

        # ── Missing probe in formal mode (C8) ────────────────────────────
        # A formal decision may not rest on a prior. When no probe has run
        # and the evidence in hand cannot block, the answer is to GET the
        # measurement — never to quietly accept the prior's number.
        if (
            evidence_channel == "probe_absent"
            and mode.phase == "formal"
            and not estimate.blocking_eligible
        ):
            reasons.append(
                f"no valid probe record for this candidate and the available "
                f"evidence ({estimate.provenance}, tier {estimate.rank}) cannot "
                "carry formal authority — a bounded live measurement is required"
            )
            return _decision("REQUEST_PROBE")

        # ── Time budget ─────────────────────────────────────────────────
        over_budget = (
            budget.time_seconds is not None
            and estimate.expected_seconds is not None
            and estimate.expected_seconds > budget.time_seconds
        )
        if not over_budget:
            reasons.append("within budget (or no budget/estimate to compare)")
            return _decision("ALLOW")

        # Over budget — authority now depends entirely on provenance.
        assert budget.time_seconds is not None and estimate.expected_seconds is not None
        reasons.append(
            f"projected {estimate.expected_seconds:.0f}s exceeds budget "
            f"{budget.time_seconds:.0f}s (provenance={estimate.provenance}, "
            f"tier={estimate.rank})"
        )

        if not estimate.blocking_eligible:
            # tiers 0-1 (priors) or contended measurement — never REJECT/ABORT
            # solely on runtime budget.
            if estimate.contended:
                reasons.append(
                    "contended measurement cannot be the sole blocker — request a clean probe"
                    if mode.probe_available
                    else "contended measurement cannot be the sole blocker — advisory"
                )
                return _decision("REQUEST_PROBE" if mode.probe_available else "ADVISORY")
            if evidence_rank(estimate.provenance) <= 1 and mode.probe_available:
                reasons.append("prior-tier evidence — request a bounded live probe")
                return _decision("REQUEST_PROBE")
            reasons.append("prior-tier evidence — advisory only")
            return _decision("ADVISORY")

        # Blocking-eligible measurement over budget.
        if estimate.provenance == "bounded_live_probe":
            # Uncalibrated clean probe: time alone blocks only when even the
            # optimistic bound exceeds the budget (no new thresholds).
            if estimate.lower_seconds is not None and estimate.lower_seconds > budget.time_seconds:
                reasons.append(
                    f"even the optimistic bound {estimate.lower_seconds:.0f}s exceeds the budget"
                )
                return _decision("REJECT")
            reasons.append(
                "uncalibrated probe over budget within uncertainty — allow "
                "with explicit uncertainty warning"
            )
            return _decision("ALLOW")

        # Calibrated probe / in-process verification / complete observation.
        reasons.append("measurement-backed evidence over budget")
        return _decision("REJECT")
