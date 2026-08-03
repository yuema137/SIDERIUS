"""Calibration policy: contention classification, promotion lifecycle,
uncertainty, applicability, and unknown-family handling (C7).

Encodes the operator-resolved D3/D4/D5 decisions (2026-07-30). All
thresholds are POLICY-VERSIONED: they live in the
``CalibrationPolicy`` payload, feed the policy identity hash, and may
change only through an explicit future design update.

D3 — contention is classified from PRE-PROBE external state over a
bounded sampling window (never one instantaneous sample, never the
probe's own utilization): known foreign process OR external memory >
max(1 GiB, 10 % VRAM) OR sustained utilization ≥ 20 % across the
window → ``foreign_contended``; telemetry gaps/throttling →
``unknown_contention``; self + registered child PIDs excluded; an
intended peer must be an EXPLICIT PID, never a process-name guess. Raw
samples are recorded verbatim.

D4 — observation lifecycle: immutable candidate ("unvalidated") →
provisional (2 mutually consistent clean observations) → validated
(≥3 consistent, no drift violation; or verification-agreement route).
Consistency: max/min observed rate ≤ 1.5 within one applicability
bucket. Buckets separate operation × unit × concurrency × hardware ×
family. Failure evidence (OOM/wall-cap/abnormal termination) never
updates throughput calibration (structurally: non-ok probes produce no
observations — C6). Promotions are DETERMINISTIC derived records; no
observation is ever mutated.

D5 — unknown family is first-class: probes run regardless; family is
assigned only from explicit implementation metadata; unknown-family
candidates never inherit known-family calibration authority (bucket
separation enforces this).
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterable, Sequence
from statistics import median
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.runtime_control.estimate_types import (
    ConcurrencyIdentity,
    RuntimeApplicability,
    RuntimeEstimate,
    make_estimate,
)
from core.runtime_control.identity import component_identity, config_hash12
from core.runtime_control.probe import ContentionSnapshot, capture_contention_snapshot
from core.runtime_control.registry_schemas import (
    CalibrationObservation,
    CalibrationPromotion,
)

_POLICY_SEMVER = "1.0.0"

#: nvidia-smi ``clocks_throttle_reasons.active`` bits treated as
#: UNEXPLAINED derating (D3 → ``unknown_contention``):
#: HwSlowdown 0x08 | SyncBoost 0x10 | SwThermalSlowdown 0x20 |
#: HwThermalSlowdown 0x40 | HwPowerBrakeSlowdown 0x80.
#: DELIBERATELY EXCLUDED as benign/expected: GpuIdle 0x01,
#: ApplicationsClocksSetting 0x02, SwPowerCap 0x04, DisplayClock 0x100 —
#: idle consumer NVIDIA accelerators commonly report 0x04 continuously,
#: so treating power-capping as throttling would mark EVERY measurement
#: unknown_contention. Policy-versioned: changing this mask changes the
#: policy identity. The specific deployment and driver stack this was
#: observed on are recorded in the §23-C7 implementation record — device
#: facts belong in the design doc, not in a core/ constant (Principle 5).
DEFAULT_DERATING_THROTTLE_MASK = 0x08 | 0x10 | 0x20 | 0x40 | 0x80


class CalibrationPolicy(BaseModel):
    """Versioned D3/D4 thresholds. The identity hash covers every field."""

    model_config = ConfigDict(frozen=True)

    # D3
    contention_memory_floor_gb: float = 1.0
    contention_memory_fraction: float = 0.10
    contention_utilization_pct: float = 20.0
    contention_window_seconds: float = 10.0
    contention_sample_interval_seconds: float = 2.0
    derating_throttle_mask: int = DEFAULT_DERATING_THROTTLE_MASK
    # D4
    consistency_max_min_ratio: float = 1.5
    provisional_min_observations: int = 2
    validated_min_observations: int = 3

    @property
    def identity(self) -> str:
        return component_identity(
            "calibration_policy", _POLICY_SEMVER, self.model_dump(mode="json")
        )


DEFAULT_POLICY = CalibrationPolicy()


# ── D3: windowed contention classification ──────────────────────────────────


class ContentionWindow(BaseModel):
    """A bounded pre-probe sampling window plus its D3 verdict. Carries
    the raw samples so the classification is auditable after the fact."""

    model_config = ConfigDict(frozen=True)

    samples: tuple[ContentionSnapshot, ...]
    classification: ConcurrencyIdentity
    reasons: tuple[str, ...]
    policy_identity: str
    expected_peer_pids: tuple[int, ...] = ()

    def raw_telemetry(self) -> dict[str, Any]:
        """Everything the verdict was derived from — the payload written
        into ``CalibrationObservation.contention_telemetry`` (D3: record
        all raw telemetry used for classification)."""
        return {
            "samples": [s.model_dump(mode="json") for s in self.samples],
            "classification": self.classification,
            "reasons": list(self.reasons),
            "policy_identity": self.policy_identity,
            "expected_peer_pids": list(self.expected_peer_pids),
        }


def classify_contention_window(
    samples: Iterable[ContentionSnapshot],
    *,
    device_vram_gb: float,
    expected_peer_pids: Iterable[int] = (),
    policy: CalibrationPolicy = DEFAULT_POLICY,
) -> tuple[ConcurrencyIdentity, tuple[str, ...]]:
    """Pure classification of a pre-probe sample window (D3 rules).

    ``expected_peer_pids`` are EXPLICITLY REGISTERED peer PIDs (the
    launcher's declared partner process) — a peer is never inferred from
    a process name. Foreign PIDs outside that set make the window
    ``foreign_contended`` even if a registered peer is also present.

    Snapshots arrive self/descendant-excluded from
    ``probe.capture_contention_snapshot``; classification NEVER looks at
    the probe's own utilization (there is none yet — this is a PRE-probe
    window)."""
    samples = tuple(samples)
    peers = set(expected_peer_pids)
    reasons: list[str] = []
    if not samples or any(not s.telemetry_available for s in samples):
        reasons.append("telemetry unavailable in the sampling window")
        return "unknown_contention", tuple(reasons)

    derating = [
        s.throttle_reasons_hex
        for s in samples
        if s.throttle_reasons_hex is not None
        and s.throttle_reasons_hex & policy.derating_throttle_mask
    ]
    if derating:
        reasons.append(
            f"unexplained clock/power throttling reported (active mask "
            f"{derating[0]:#x} intersects derating mask "
            f"{policy.derating_throttle_mask:#x})"
        )
        return "unknown_contention", tuple(reasons)

    mem_threshold = max(
        policy.contention_memory_floor_gb,
        policy.contention_memory_fraction * device_vram_gb,
    )
    observed_foreign: set[int] = set()
    unaccounted_count = 0
    for s in samples:
        observed_foreign |= set(s.foreign_compute_pids)
        # A sample that reports a foreign COUNT without PIDs (older
        # producers / telemetry without PID detail) is still evidence.
        unaccounted_count = max(
            unaccounted_count,
            (s.foreign_compute_processes or 0) - len(s.foreign_compute_pids),
        )
    unregistered = sorted(observed_foreign - peers)
    max_mem = max(s.gpu_memory_used_gb or 0.0 for s in samples)
    sustained_util = all(
        (s.gpu_utilization_pct or 0.0) >= policy.contention_utilization_pct for s in samples
    )

    if unregistered or unaccounted_count > 0:
        reasons.append(
            "known foreign GPU process present "
            f"(unregistered PIDs {unregistered}, "
            f"{unaccounted_count} further unidentified foreign process(es))"
        )
        return "foreign_contended", tuple(reasons)
    if max_mem > mem_threshold:
        reasons.append(
            f"pre-probe external GPU memory {max_mem:.2f} GB exceeds "
            f"max({policy.contention_memory_floor_gb:.0f} GiB, "
            f"{policy.contention_memory_fraction:.0%} VRAM) = "
            f"{mem_threshold:.2f} GB"
        )
        return "foreign_contended", tuple(reasons)
    if sustained_util:
        reasons.append(
            f"sustained GPU utilization ≥ {policy.contention_utilization_pct:.0f}% "
            f"across the whole {len(samples)}-sample window"
        )
        return "foreign_contended", tuple(reasons)
    if observed_foreign:
        reasons.append(
            "only the current probe plus the explicitly registered "
            f"intended peer(s) {sorted(observed_foreign)} are present"
        )
        return "pairwise_expected_peer", tuple(reasons)
    reasons.append("only the current probe process is present")
    return "single_candidate_idle", tuple(reasons)


def sample_contention_window(
    *,
    device_vram_gb: float,
    expected_peer_pids: Iterable[int] = (),
    policy: CalibrationPolicy = DEFAULT_POLICY,
    capture: Callable[..., ContentionSnapshot] = capture_contention_snapshot,
    sleep: Callable[[float], None] = time.sleep,
) -> ContentionWindow:
    """Collect the bounded pre-probe window and classify it (D3).

    Bounded by construction: ``ceil(window / interval)`` samples, never a
    single instantaneous reading. Every raw sample is kept."""
    peers = tuple(sorted(set(expected_peer_pids)))
    n = max(
        1,
        math.ceil(policy.contention_window_seconds / policy.contention_sample_interval_seconds),
    )
    samples: list[ContentionSnapshot] = []
    for i in range(n):
        samples.append(capture())
        if i < n - 1:
            sleep(policy.contention_sample_interval_seconds)
    classification, reasons = classify_contention_window(
        samples,
        device_vram_gb=device_vram_gb,
        expected_peer_pids=peers,
        policy=policy,
    )
    return ContentionWindow(
        samples=tuple(samples),
        classification=classification,
        reasons=reasons,
        policy_identity=policy.identity,
        expected_peer_pids=peers,
    )


# ── D5: family classification ───────────────────────────────────────────────


def classify_model_family(
    *,
    declared_family: str | None = None,
    structural_features: dict[str, Any] | None = None,
) -> str:
    """Family from EXPLICIT implementation metadata or deterministic
    structural features only. Uncertain → 'unknown' (first-class) —
    never the nearest known family."""
    if declared_family and declared_family.strip():
        return declared_family.strip()
    features = structural_features or {}
    dominant = features.get("dominant_block_type")
    if isinstance(dominant, str) and dominant.strip():
        return f"feature:{dominant.strip()}"
    return "unknown"


# ── D4: buckets, clean-ness, consistency, promotion ─────────────────────────


#: Defense in depth for the D4 rule "measured OOM, wall-cap hits and
#: abnormal termination are valuable failure evidence but must not
#: update throughput calibration". The PRIMARY guarantee is structural
#: (``probe_observations`` refuses any non-ok probe); this screens an
#: optional ``source_run["outcome"]`` marker should another producer
#: ever record failure evidence as an observation.
FAILURE_OUTCOMES = frozenset({"oom", "wall_cap", "load_failure", "abnormal_termination"})

#: Only these concurrency regimes may back calibration authority.
CLEAN_CONCURRENCY = ("single_candidate_idle", "pairwise_expected_peer")


def stack_identity(software_stack: dict[str, Any]) -> str:
    """12-char content hash of the software stack (drift anchor)."""
    return f"stack:{config_hash12(software_stack)}"


def bucket_components(obs: CalibrationObservation) -> tuple[str, ...]:
    """Ordered bucket components; the SOFTWARE STACK is last so drift
    analysis can group by ``components[:-1]`` (same workload class,
    different stack)."""
    return (
        obs.operation,
        obs.measurement_unit,
        obs.concurrency_identity,
        obs.hardware_compatibility_id,
        obs.execution_environment_id,
        obs.model_family,
        stack_identity(obs.software_stack),
    )


def bucket_key(obs: CalibrationObservation) -> str:
    """Applicability bucket: operation × unit × concurrency × hardware
    compatibility × execution environment × family × software stack.

    Idle and pairwise never cross-write. The EXECUTION ENVIRONMENT is
    part of the key because §3.3 grants local authority only to local
    evidence: observations from another machine (even one with an
    identical hardware compatibility profile) form their own bucket and
    can never be promoted into local blocking authority. Unknown family
    is its own bucket (D5) — it never inherits a known family's
    calibration. The SOFTWARE STACK is part of the key so that a stack
    change (torch/CUDA/driver) starts a fresh bucket by construction:
    old evidence can never silently back a new stack, which is drift
    handling without any mutation of prior records."""
    return "|".join(bucket_components(obs))


def eligibility_problems(obs: CalibrationObservation) -> list[str]:
    """D4 calibration-eligibility screen for one candidate record —
    returns the reasons it may NOT back calibration (empty ⇒ clean).

    Enforced elsewhere and therefore only referenced here:
    measurement-backed provenance and a non-empty producer identity are
    schema invariants of ``CalibrationObservation``; content-hash and
    schema validity are re-verified by the registry on every load
    (``load_observation``); unsupported extrapolation is a READ-side
    label (``classify_applicability``) — an observation is always a
    measurement AT its own workload, never an extrapolation."""
    problems: list[str] = []
    if obs.concurrency_identity not in CLEAN_CONCURRENCY:
        problems.append(f"concurrency_identity={obs.concurrency_identity!r} is not clean")
    if not obs.measurement_unit:
        problems.append("missing measurement_unit")
    if not obs.workload:
        problems.append("missing workload metadata")
    if not obs.hardware_compatibility_id or not obs.execution_environment_id:
        problems.append("incomplete hardware/environment identity")
    outcome = obs.source_run.get("outcome")
    if isinstance(outcome, str) and outcome in FAILURE_OUTCOMES:
        problems.append(
            f"failure evidence (outcome={outcome!r}) never updates throughput calibration"
        )
    return problems


def is_clean(obs: CalibrationObservation) -> bool:
    """True when the record may participate in a promotion (D4)."""
    return not eligibility_problems(obs)


def consistency_ratio(values_ms: list[float]) -> float:
    return max(values_ms) / min(values_ms)


def evaluate_bucket(
    observations: list[CalibrationObservation],
    *,
    policy: CalibrationPolicy = DEFAULT_POLICY,
    generation: int,
) -> CalibrationPromotion | None:
    """Deterministic D4 promotion decision for ONE bucket of clean
    candidate observations. Returns the derived promotion record (not
    persisted here), or None when the bucket stays candidate-only.

    Drift rule (documented): the SAME 1.5 max/min criterion applied to
    the full bucket — a new observation that breaks the ratio blocks
    validation (the bucket falls back to candidate-only until the
    inconsistency is resolved by further evidence)."""
    if len(observations) < policy.provisional_min_observations:
        return None
    keys = {bucket_key(o) for o in observations}
    if len(keys) != 1:
        raise ValueError(f"evaluate_bucket got mixed buckets: {sorted(keys)}")
    dirty = {o.observation_id: eligibility_problems(o) for o in observations}
    if any(dirty.values()):
        raise ValueError(
            "evaluate_bucket requires pre-screened clean observations: "
            + "; ".join(f"{k}: {v}" for k, v in dirty.items() if v)
        )
    values = sorted(o.measured_value_ms for o in observations)
    ratio = consistency_ratio(values)
    if ratio > policy.consistency_max_min_ratio:
        return None  # inconsistent → stays candidate-only (drift violation)
    level = "validated" if len(observations) >= policy.validated_min_observations else "provisional"
    ids = tuple(sorted(o.observation_id for o in observations))
    return CalibrationPromotion(
        bucket_key=next(iter(keys)),
        level=level,
        source_observation_ids=ids,
        consistency_ratio=round(ratio, 6),
        n_observations=len(observations),
        rate_median_ms=median(values),
        rate_min_ms=values[0],
        rate_max_ms=values[-1],
        policy_identity=policy.identity,
        derived_from_generation=generation,
        validation_route="consistency",
    )


def validate_against_verification(
    probe_obs: CalibrationObservation,
    verification_obs: CalibrationObservation,
    *,
    policy: CalibrationPolicy = DEFAULT_POLICY,
    generation: int,
) -> CalibrationPromotion | None:
    """D4 route B: in-process verification (or complete execution) may
    validate an earlier probe when operation AND unit are comparable and
    the two rates agree within the consistency criterion. Two clean
    observations agreeing across evidence tiers are stronger than two
    probes agreeing, so this route reaches ``validated`` at n=2."""
    if verification_obs.provenance not in (
        "real_training_verification",
        "real_inference_verification",
        "complete_observation",
    ):
        raise ValueError(
            f"route B requires verification/complete provenance, got "
            f"{verification_obs.provenance!r}"
        )
    for label, obs in (("probe", probe_obs), ("verification", verification_obs)):
        problems = eligibility_problems(obs)
        if problems:
            raise ValueError(f"route B {label} observation not clean: {problems}")
    if (
        probe_obs.operation != verification_obs.operation
        or probe_obs.measurement_unit != verification_obs.measurement_unit
    ):
        return None  # units not comparable — no validation
    if bucket_key(probe_obs) != bucket_key(verification_obs):
        return None
    values = sorted([probe_obs.measured_value_ms, verification_obs.measured_value_ms])
    ratio = consistency_ratio(values)
    if ratio > policy.consistency_max_min_ratio:
        return None
    ids = tuple(sorted([probe_obs.observation_id, verification_obs.observation_id]))
    return CalibrationPromotion(
        bucket_key=bucket_key(probe_obs),
        level="validated",
        source_observation_ids=ids,
        consistency_ratio=round(ratio, 6),
        n_observations=2,
        rate_median_ms=median(values),
        rate_min_ms=values[0],
        rate_max_ms=values[-1],
        policy_identity=policy.identity,
        derived_from_generation=generation,
        validation_route="verification_agreement",
    )


def evaluate_promotions(
    observations: Iterable[CalibrationObservation],
    *,
    policy: CalibrationPolicy = DEFAULT_POLICY,
    generation: int,
) -> list[CalibrationPromotion]:
    """Deterministic sweep: group clean candidates by bucket, evaluate
    each. Dirty (contended/unknown) observations are silently excluded
    from promotion — they remain persisted candidates."""
    buckets: dict[str, list[CalibrationObservation]] = {}
    for obs in observations:
        if is_clean(obs):
            buckets.setdefault(bucket_key(obs), []).append(obs)
    promotions = []
    for _, bucket in sorted(buckets.items()):
        promo = evaluate_bucket(bucket, policy=policy, generation=generation)
        if promo is not None:
            promotions.append(promo)
    return promotions


# ── drift + staleness ───────────────────────────────────────────────────────


class DriftReport(BaseModel):
    """What a promotion sweep could NOT conclude, and why (§17.8).

    ``inconsistent_buckets`` — clean, sufficiently populated buckets
    whose max/min ratio breaks the consistency criterion: a drift
    violation blocks promotion (the bucket stays candidate-only) and is
    reported rather than averaged away.
    ``stack_drift`` — one workload class measured under more than one
    software stack: the buckets are separate by construction, so this is
    an ADVISORY signal that older evidence describes a different stack.
    ``stale_buckets`` — buckets whose stack differs from the current one
    (only computed when the caller supplies the current stack)."""

    model_config = ConfigDict(frozen=True)

    inconsistent_buckets: dict[str, float] = Field(default_factory=dict)
    stack_drift: dict[str, list[str]] = Field(default_factory=dict)
    stale_buckets: list[str] = Field(default_factory=list)


def detect_drift(
    observations: Iterable[CalibrationObservation],
    *,
    policy: CalibrationPolicy = DEFAULT_POLICY,
    current_software_stack: dict[str, Any] | None = None,
) -> DriftReport:
    """Deterministic drift/staleness analysis over clean candidates."""
    buckets: dict[str, list[CalibrationObservation]] = {}
    classes: dict[str, set[str]] = {}
    for obs in observations:
        if not is_clean(obs):
            continue
        buckets.setdefault(bucket_key(obs), []).append(obs)
        components = bucket_components(obs)
        classes.setdefault("|".join(components[:-1]), set()).add(components[-1])

    inconsistent = {}
    for key, bucket in sorted(buckets.items()):
        if len(bucket) < policy.provisional_min_observations:
            continue
        ratio = consistency_ratio([o.measured_value_ms for o in bucket])
        if ratio > policy.consistency_max_min_ratio:
            inconsistent[key] = round(ratio, 6)

    current = stack_identity(current_software_stack) if current_software_stack else None
    return DriftReport(
        inconsistent_buckets=inconsistent,
        stack_drift={k: sorted(v) for k, v in sorted(classes.items()) if len(v) > 1},
        stale_buckets=(
            sorted(k for k in buckets if not k.endswith(f"|{current}")) if current else []
        ),
    )


# ── component uncertainty (per bucket) ──────────────────────────────────────


class BucketUncertainty(BaseModel):
    model_config = ConfigDict(frozen=True)

    bucket_key: str
    n_observations: int
    rate_median_ms: float
    max_min_ratio: float
    within_observation_spread_ms: tuple[float, float] | None


def bucket_uncertainty(observations: list[CalibrationObservation]) -> BucketUncertainty:
    """Component-specific uncertainty from a bucket's observations: the
    cross-observation max/min ratio plus the widest within-observation
    spread recorded by the producers (no invented distributions)."""
    if not observations:
        raise ValueError("bucket_uncertainty requires observations")
    keys = {bucket_key(o) for o in observations}
    if len(keys) != 1:
        raise ValueError(f"mixed buckets: {sorted(keys)}")
    values = sorted(o.measured_value_ms for o in observations)
    spreads = [
        tuple(o.uncertainty_inputs["spread_ms"])
        for o in observations
        if isinstance(o.uncertainty_inputs.get("spread_ms"), list)
        and len(o.uncertainty_inputs["spread_ms"]) == 2
    ]
    widest = max(spreads, key=lambda s: s[1] - s[0]) if spreads else None
    return BucketUncertainty(
        bucket_key=next(iter(keys)),
        n_observations=len(values),
        rate_median_ms=median(values),
        max_min_ratio=consistency_ratio(values),
        within_observation_spread_ms=widest,  # type: ignore[arg-type]
    )


# ── applicability (§8.3, threshold-free subset) ─────────────────────────────


def classify_applicability(
    *, requested: float, observed_min: float, observed_max: float
) -> RuntimeApplicability:
    """Interpolation inside the observed range; UNSUPPORTED outside.

    ``bounded_extrapolation`` is RESERVED and deliberately never
    assigned here: choosing how far past measured evidence a prediction
    may still carry authority is a margin decision, and inventing one
    would recreate exactly the uncalibrated-extrapolation failure this
    subsystem exists to prevent. Until an operator fixes that margin,
    anything outside the measured range carries the weakest label."""
    if observed_min <= requested <= observed_max:
        return "interpolation"
    return "unsupported_extrapolation"


def applicability_for_request(
    *,
    requested: dict[str, float],
    observed_ranges: dict[str, tuple[float, float]],
) -> tuple[RuntimeApplicability, tuple[str, ...]]:
    """Weakest label across every dimension with evidence (parameter
    count, batch size, segment length…). A dimension with NO observed
    range yields ``not_applicable`` for the whole request — absent
    evidence is never treated as supporting evidence."""
    labels: list[RuntimeApplicability] = []
    reasons: list[str] = []
    for dim, value in sorted(requested.items()):
        span = observed_ranges.get(dim)
        if span is None:
            reasons.append(f"{dim}: no measured evidence in this bucket")
            labels.append("not_applicable")
            continue
        label = classify_applicability(requested=value, observed_min=span[0], observed_max=span[1])
        if label != "interpolation":
            reasons.append(
                f"{dim}: requested {value:g} outside measured range [{span[0]:g}, {span[1]:g}]"
            )
        labels.append(label)
    if not labels:
        return "not_applicable", ("no request dimensions supplied",)
    for weakest in ("not_applicable", "unsupported_extrapolation", "bounded_extrapolation"):
        if weakest in labels:
            return weakest, tuple(reasons)  # type: ignore[return-value]
    return "interpolation", tuple(reasons)


def downgrade_for_applicability(
    estimate: RuntimeEstimate,
    applicability: RuntimeApplicability,
    *,
    reasons: tuple[str, ...] = (),
) -> RuntimeEstimate:
    """Stamp the applicability label and, when the request falls outside
    the measured range, DEMOTE the evidence to a historical prior.

    Eligibility is derived from provenance (C3), so removing blocking
    authority means changing the provenance — the numbers survive as an
    advisory prior, the authority does not. Measured evidence applied
    INSIDE its measured range is untouched."""
    if applicability == "interpolation":
        return estimate.model_copy(update={"applicability": applicability})
    note = (
        f"applicability={applicability}: measured evidence cannot carry "
        "blocking authority outside its measured range"
        + (f" ({'; '.join(reasons)})" if reasons else "")
    )
    payload = estimate.model_dump()
    for derived in (
        "provenance",
        "confidence",
        "verification_passed",
        "steady_state",
        "concurrency_identity",
        "advisory_eligible",
        "blocking_eligible",
        "formal_execution_eligible",
        "applicability",
        "warnings",
    ):
        payload.pop(derived, None)
    return make_estimate(
        provenance="historical_observation_prior",
        confidence="low",
        concurrency_identity=estimate.concurrency_identity,
        applicability=applicability,
        warnings=(*estimate.warnings, note),
        **payload,
    )


# ── V20 PR C1 / C-C2: the applicability envelope ────────────────────────────


class ApplicabilityEnvelope(BaseModel):
    """WHO ELSE a bucket of measurements may speak for.

    The second of the three models the PR C design separates (§8.1).
    `MeasurementIdentity` answers "is this the same thing?" by equality;
    this answers "is the candidate inside the region we actually observed?"
    by bounded range. Neither substitutes for the other, and neither is
    policy.

    Built from what a bucket MEASURED, never from what a caller hopes. A
    dimension with no observed span is absent from `ranges`, and
    `applicability_for_request` fails closed on it -- absent evidence is
    never supporting evidence. That rule already exists; this model gives
    it a typed carrier instead of a bare dict passed between functions.

    A matching identity plus an out-of-range candidate is NOT applicable.
    That is the frozen invariant "a bucket match is not applicability"
    (§8.A) made structural: you cannot obtain an envelope verdict by
    matching the key, because the key is not in this model.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Dimension -> (observed_min, observed_max), from real measurements.
    #: Typical dimensions: parameter_count, batch_size, segment_length.
    ranges: dict[str, tuple[float, float]] = Field(default_factory=dict)
    #: How many observations backed these ranges. A span derived from one
    #: sample is a point, not a range; promotion policy owns the threshold,
    #: but the count travels with the envelope so a reader can judge it.
    sample_count: int = Field(default=0, ge=0)
    #: The concurrency class every backing observation was taken under.
    #: Mixing idle and contended evidence into one span would describe a
    #: condition that never occurred.
    concurrency_identity: ConcurrencyIdentity | None = None

    @model_validator(mode="after")
    def _spans_are_ordered(self) -> ApplicabilityEnvelope:
        for dim, span in self.ranges.items():
            if span[0] > span[1]:
                raise ValueError(
                    f"{dim}: observed_min {span[0]} exceeds observed_max {span[1]}; "
                    "an inverted span would make every request look out of range"
                )
        return self

    def classify(self, requested: dict[str, float]) -> tuple[RuntimeApplicability, tuple[str, ...]]:
        """Weakest label across the requested dimensions, with reasons."""
        return applicability_for_request(requested=requested, observed_ranges=self.ranges)

    @classmethod
    def from_observations(
        cls,
        observations: Sequence[CalibrationObservation],
        *,
        dimensions: Sequence[str] = ("batch_size", "segment_length"),
    ) -> ApplicabilityEnvelope:
        """Derive the envelope from a bucket's own observations.

        Reads the numeric dimensions out of `workload`; a dimension no
        observation carries is simply absent, which is what makes the
        read side fail closed on it rather than inventing a span.
        """
        spans: dict[str, tuple[float, float]] = {}
        for dim in dimensions:
            values = [
                float(obs.workload[dim])
                for obs in observations
                if isinstance(obs.workload.get(dim), (int, float))
            ]
            if values:
                spans[dim] = (min(values), max(values))
        regimes = {obs.concurrency_identity for obs in observations}
        return cls(
            ranges=spans,
            sample_count=len(observations),
            concurrency_identity=regimes.pop() if len(regimes) == 1 else None,
        )
