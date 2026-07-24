"""
core/runtime_control/total_assembly.py

Component-wise total assembly with the contribution-based eligibility
policy (RT2-E, operator decision 2026-07-23).

Design: docs/design/runtime_estimation_and_watchdog.md §2.7-§2.9, §3.
The verification strategy for a phase is determined by its RUNTIME
CONTRIBUTION, never by its name:

- **Live-verified phases** carry measurement-backed predictions
  (individually ``formal_execution_eligible`` — the RT2-A schema
  invariant is untouched).
- **Historically estimated phases** carry evidence-backed non-live
  predictions (``historical_observation_prior``,
  ``historical_orchestration``, ``bounded_negligible``,
  ``legacy_calibration_prior``) — individually NEVER eligible, but
  admissible into the total while the combined historical share stays
  below ``historical_phase_share_limit``.
- Exceeding the share limit AUTOMATICALLY escalates: the historical
  phases become live-verification candidates and the total is
  ineligible until they are measured. A future workflow whose
  "minor" phase grows large is caught with no framework change.

Static/derived sources (``static_uncalibrated``, ``derived_total``,
plain ``historical_orchestration`` misuse aside) are never admissible
inside a formal total.

Conservative aggregation (§2.9, simple + explicit): the total is the
exact component sum; the safety factor multiplies the sum; overall
confidence is the MINIMUM component confidence.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.runtime_control.phases import RuntimePhase
from core.runtime_control.records import (
    MEASUREMENT_BACKED_SOURCES,
    Confidence,
    PhaseComponentRecord,
    TotalRecord,
)

#: Evidence-backed non-live sources admissible into a formal total
#: under the share limit. Everything else non-live is inadmissible.
HISTORICAL_EVIDENCE_SOURCES: frozenset[str] = frozenset(
    {
        "historical_observation_prior",
        "historical_orchestration",
        "legacy_calibration_prior",
        "bounded_negligible",
    }
)

_CONFIDENCE_ORDER: dict[Confidence, int] = {"low": 0, "medium": 1, "high": 2}

#: Provisional default for the configurable share limit (operator
#: decision 2026-07-23: "the exact default can be determined later").
DEFAULT_HISTORICAL_SHARE_LIMIT: float = 0.10

PhaseClass = Literal["live_verified", "historical_estimate", "inadmissible"]


class TotalAssessment(BaseModel):
    """Outcome of assembling one attempt's component-wise total."""

    model_config = ConfigDict(frozen=True)

    total: TotalRecord | None = None
    formal_eligible: bool
    reason: str
    phase_classes: dict[RuntimePhase, PhaseClass] = Field(default_factory=dict)
    historical_share: float | None = Field(
        default=None,
        ge=0.0,
        description="Σ historical predictions ÷ total predictions.",
    )
    escalation_required: list[RuntimePhase] = Field(
        default_factory=list,
        description=(
            "Historical phases that must move to live verification "
            "(share limit exceeded), largest contribution first."
        ),
    )
    missing_phases: list[RuntimePhase] = Field(default_factory=list)
    overall_confidence: Confidence | None = None


def evidence_backed_prediction(
    *,
    predicted_seconds: float,
    source: str,
    confidence: Confidence,
    unit_count: int | None = None,
    evidence: dict | None = None,
):
    """Build an evidence-backed HISTORICAL phase prediction.

    Individually never formal-eligible (the RT2-A schema invariant);
    admissible into a formal total only through the share rule. The
    evidence dict is mandatory in spirit: a historical estimate must
    say what backs it (§2.7 — never assumption-based).

    Raises:
        ValueError: ``source`` is not an admissible historical-evidence
            source.
    """
    from core.runtime_control.records import RuntimePrediction

    if source not in HISTORICAL_EVIDENCE_SOURCES:
        raise ValueError(
            f"source {source!r} is not an evidence-backed historical source "
            f"(allowed: {sorted(HISTORICAL_EVIDENCE_SOURCES)})."
        )
    return RuntimePrediction(
        predicted_seconds=max(predicted_seconds, 1e-9),
        source=source,  # type: ignore[arg-type]
        formal_execution_eligible=False,
        steady_state=False,
        verification="not_attempted",
        confidence=confidence,
        unit_count=unit_count,
        safety_factor=1.0,
        detail={"classification": "historical_estimate", "evidence": dict(evidence or {})},
    )


def observation_formal_eligible(
    components: dict[RuntimePhase, PhaseComponentRecord],
    runtime_policy: dict | None = None,
) -> bool:
    """Contribution-based total eligibility for a persisted observation.

    Judged against the phases PRESENT in the observation (the required
    set of the execution class is the admission layer's business —
    RT2-G); the share limit comes from the observation's recorded
    policy, falling back to the provisional default. Fail-closed on
    any assembly problem.
    """
    if not components:
        return False
    limit = DEFAULT_HISTORICAL_SHARE_LIMIT
    if runtime_policy:
        raw = runtime_policy.get("historical_phase_share_limit")
        if isinstance(raw, int | float) and 0.0 <= raw <= 1.0:
            limit = float(raw)
    try:
        assessment = assemble_total(
            components,
            required_phases=tuple(components.keys()),
            historical_phase_share_limit=limit,
        )
    except Exception:
        return False
    return assessment.formal_eligible


def classify_prediction_source(source: str) -> PhaseClass:
    """Contribution-policy class of one prediction source."""
    if source in MEASUREMENT_BACKED_SOURCES:
        return "live_verified"
    if source in HISTORICAL_EVIDENCE_SOURCES:
        return "historical_estimate"
    return "inadmissible"


def assemble_total(
    components: dict[RuntimePhase, PhaseComponentRecord],
    *,
    required_phases: tuple[RuntimePhase, ...],
    historical_phase_share_limit: float,
    safety_factor: float = 1.0,
    operator_budget_seconds: float | None = None,
) -> TotalAssessment:
    """Assemble the derived total and judge its formal eligibility.

    Args:
        components:      The attempt's phase components.
        required_phases: The execution class's required phase set (the
                         caller — RT2-G admission wiring — owns this;
                         §3 completeness is judged against it).
        historical_phase_share_limit: Maximum admissible Σ(historical)
                         ÷ total. Configurable policy, never hardcoded
                         phase names.
        safety_factor:   §2.9 conservative multiplier for the adjusted
                         total.
        operator_budget_seconds: Recorded on the TotalRecord.

    The assessment never raises on incomplete/ineligible input — an
    ineligible total with a structured reason IS the §3 fail-closed
    answer.
    """
    missing: list[RuntimePhase] = [
        p for p in required_phases if p not in components or components[p].prediction is None
    ]
    if missing:
        return TotalAssessment(
            formal_eligible=False,
            reason=(
                f"incomplete component predictions (missing: {missing}) — "
                "never sufficient for formal admission (§3)."
            ),
            missing_phases=missing,
        )

    phase_classes: dict[RuntimePhase, PhaseClass] = {}
    live_sum = 0.0
    historical_sum = 0.0
    inadmissible: list[RuntimePhase] = []
    confidences: list[Confidence] = []
    for phase in required_phases:
        prediction = components[phase].prediction
        assert prediction is not None  # guarded above
        cls = classify_prediction_source(prediction.source)
        phase_classes[phase] = cls
        confidences.append(prediction.confidence)
        if cls == "live_verified":
            live_sum += prediction.predicted_seconds
        elif cls == "historical_estimate":
            historical_sum += prediction.predicted_seconds
        else:
            inadmissible.append(phase)

    total_seconds = (
        live_sum
        + historical_sum
        + sum(
            components[p].prediction.predicted_seconds  # type: ignore[union-attr]
            for p in inadmissible
        )
    )
    total = TotalRecord(
        predicted_seconds=max(total_seconds, 1e-9),
        safety_adjusted_seconds=max(total_seconds, 1e-9) * safety_factor,
        operator_budget_seconds=operator_budget_seconds,
    )
    overall_confidence = min(confidences, key=lambda c: _CONFIDENCE_ORDER[c])

    if inadmissible:
        return TotalAssessment(
            total=total,
            formal_eligible=False,
            reason=(
                f"phases {inadmissible} carry inadmissible prediction sources "
                "(static/derived are never part of a formal total — §1.1/§3)."
            ),
            phase_classes=phase_classes,
            overall_confidence=overall_confidence,
        )

    share = historical_sum / total_seconds if total_seconds > 0 else 0.0
    if share > historical_phase_share_limit:
        escalate: list[RuntimePhase] = sorted(
            (p for p, c in phase_classes.items() if c == "historical_estimate"),
            key=lambda p: -components[p].prediction.predicted_seconds,  # type: ignore[union-attr]
        )
        return TotalAssessment(
            total=total,
            formal_eligible=False,
            reason=(
                f"historical share {share:.1%} exceeds the "
                f"{historical_phase_share_limit:.1%} limit — phases {escalate} "
                "must escalate to live verification (contribution-based "
                "policy, operator decision 2026-07-23)."
            ),
            phase_classes=phase_classes,
            historical_share=share,
            escalation_required=escalate,
            overall_confidence=overall_confidence,
        )

    return TotalAssessment(
        total=total,
        formal_eligible=True,
        reason=(
            f"complete: {sum(1 for c in phase_classes.values() if c == 'live_verified')} "
            f"live-verified phase(s) + historical share {share:.1%} within the "
            f"{historical_phase_share_limit:.1%} limit."
        ),
        phase_classes=phase_classes,
        historical_share=share,
        overall_confidence=overall_confidence,
    )
