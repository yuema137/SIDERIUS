"""Canonical runtime-evidence envelope types (C3).

Design contract: docs/design/runtime_estimation_and_calibration.md
§7.2/§7.3/§8.4. This module WRAPS the existing phase-level vocabulary in
``core/runtime_control/records.py`` — ``PredictionSource``,
``MEASUREMENT_BACKED_SOURCES``, ``Confidence``,
``RuntimePrediction.formal_execution_eligible`` — into an estimate-level
envelope shared by every runtime consumer (proposer advisory, tuner,
admission, watchdog, reporting) from C4/C8 onward.

Reconciliation rules (operator-resolved, §7.3):

* ONE canonical vocabulary — ``records.PredictionSource`` — extended,
  never forked. The design's presentation names map onto it:
  static prior ↔ ``static_uncalibrated``; historical prior ↔
  ``historical_observation_prior``; live probe ↔ ``bounded_live_probe``;
  calibrated live probe ↔ ``bounded_live_probe_calibrated``;
  in-process verification ↔ ``real_*_verification``;
  complete observation ↔ ``complete_observation``.
* The existing field name ``formal_execution_eligible`` is KEPT (its
  records.py usage is documented and schema-enforced); no
  ``formal_decision_eligible`` synonym is introduced.
* Decision eligibility is DERIVED from provenance + measurement state
  by ``derive_decision_eligibility`` — never caller-assigned. The
  illegal state ``static prior + blocking authority`` is
  unrepresentable: the ``RuntimeEstimate`` validator rejects it.

C3 scope note: these types are ADDITIVE. No production consumer decides
through them yet (C4 builds the estimator/policy; C8 rewires
consumers). The adapters below wrap the four existing evidence
producers read-only.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.runtime_control.measurement_validity import (
    VALID as VALID_MEASUREMENT,
)
from core.runtime_control.measurement_validity import (
    MeasurementValidity,
)
from core.runtime_control.records import (
    MEASUREMENT_BACKED_SOURCES,
    Confidence,
    PredictionSource,
)

# ── Vocabulary (estimate level) ──────────────────────────────────────────────

#: §21-policy concurrency identities (operator-resolved). ``None`` on an
#: estimate means the producing path predates concurrency capture (C6).
ConcurrencyIdentity = Literal[
    "single_candidate_idle",
    "pairwise_expected_peer",
    "foreign_contended",
    "unknown_contention",
]

#: §8.3 applicability labels for historically-corrected evidence.
RuntimeApplicability = Literal[
    "interpolation",
    "bounded_extrapolation",
    "unsupported_extrapolation",
    "not_applicable",
]

RuntimePhaseName = Literal["proposal", "trial", "formal"]
RuntimeOperation = Literal["training", "inference", "combined"]

# ── Evidence precedence (§8.4) ───────────────────────────────────────────────

#: Tier per source; HIGHER outranks lower. A lower-ranked estimate must
#: never overwrite a higher-ranked measurement.
_EVIDENCE_TIER: dict[str, int] = {
    "static_uncalibrated": 0,
    # historical / similarity priors
    "legacy_calibration_prior": 1,
    "historical_observation_prior": 1,
    "historical_orchestration": 1,
    "bounded_negligible": 1,
    # uncalibrated live probe
    "bounded_live_probe": 2,
    # calibrated live probe
    "bounded_live_probe_calibrated": 3,
    # in-process verification (RT2)
    "real_dataset_setup": 4,
    "real_dataset_warmup": 4,
    "real_training_verification": 4,
    # Step 07 / PR 07c C5 — the first real validation batches, timed
    # in-subprocess. Tier 4 with its siblings: it is the same KIND of
    # evidence, an in-process verification of the actual configuration, and
    # the phase it describes is what distinguishes it.
    "real_validation_verification": 4,
    "real_inference_verification": 4,
    "measured_representative_scoring": 4,
    "derived_total": 4,
    # complete observed execution
    "complete_observation": 5,
}


def evidence_rank(source: PredictionSource) -> int:
    """§8.4 precedence tier of a provenance value (total order, pure)."""
    try:
        return _EVIDENCE_TIER[source]
    except KeyError:  # pragma: no cover — Literal prevents this at type time
        raise ValueError(f"unknown provenance source: {source!r}") from None


def derive_decision_eligibility(
    source: PredictionSource,
    *,
    verification_passed: bool = False,
    steady_state: bool = False,
    contended: bool = False,
    measurement_validity: str | None = None,
    concurrency_identity: str | None = None,
) -> tuple[bool, bool, bool]:
    """Derive ``(advisory_eligible, blocking_eligible,
    formal_execution_eligible)`` from provenance + measurement state.

    §7.4 policy skeleton (the full budget-aware decision matrix lives in
    the C4 ``RuntimeDecisionPolicy``; this function fixes only what
    provenance can EVER authorize):

    * every estimate is advisory-eligible;
    * priors (static/historical, tiers 0-1) can never block;
    * measurement-backed evidence may block only when the measurement is
      VALID;
    * formal execution eligibility additionally requires verification
      passed + steady state (mirrors the records.py admission
      invariant).

    **V20 PR C — the blocking rule changed.** It was::

        blocking = measured and not contended

    where ``contended`` was true whenever any foreign process held any
    memory, however steadily. That asked whether the device was busy, not
    whether the measurement could be trusted, and it made a correct
    measurement taken beside a stable neighbour unusable — which aborted a
    real chain (Gate 2 attempt 1, 2026-08-05). It is now::

        blocking = measured and validity == valid_current_conditions

    The presence of external occupancy no longer decides anything.

    ``measurement_validity`` is the verdict from
    :mod:`core.runtime_control.measurement_validity`, computed over a
    bounded observation window. When it is ``None`` the caller had no
    window, and validity is inferred **conservatively** from
    ``contended``: an idle or registered-peer identity is treated as valid,
    while a contended or unknown identity **cannot establish** validity and
    therefore cannot block. That is deliberately the pre-PR-C outcome —
    without window evidence there is no basis for claiming stability, and
    inventing one is exactly the error being corrected. Producers that want
    a stable neighbour to count must supply the window.

    Args:
        source: evidence provenance.
        verification_passed: whether real-training verification passed.
        steady_state: whether the measurement reached steady state.
        contended: legacy presence flag, used ONLY to infer validity
            conservatively when ``measurement_validity`` is absent.
        measurement_validity: the typed verdict, when a window exists.
    """
    if measurement_validity is None:
        # No occupancy window was supplied, so validity was never computed.
        #
        # SCOPE NOTE (2026-08-06). The presence-based REFUSAL was removed
        # where it did real harm: bootstrap readiness, which stopped the flow
        # before validity was ever computed on a shared device.
        #
        # This fallback is deliberately left conservative. It applies ONLY
        # when no occupancy window exists — i.e. when no device identity was
        # named, so `gpu_accounting` was never sampled and integrity was
        # never assessed. Granting blocking authority there would rest on no
        # evidence at all.
        #
        # Read it as "validity NOT ESTABLISHED", not as "presence
        # invalidates". Every path that names its device — including the real
        # Case B bootstrap/probe path after FU-C-1 — builds a window and is
        # decided by integrity above, never by this branch.
        #
        # Widening it was tried and reverted: it changed behaviour across
        # five modules for paths carrying no occupancy evidence, which is
        # scope the mandate's narrow-correction rule excludes.
        measurement_validity = None if contended else VALID_MEASUREMENT
    advisory = True
    measured = source in MEASUREMENT_BACKED_SOURCES
    blocking = measured and measurement_validity == VALID_MEASUREMENT
    formal = blocking and verification_passed and steady_state
    return advisory, blocking, formal


# ── Envelope types (§7.2 / §7.3) ─────────────────────────────────────────────


class RuntimeEstimateRequest(BaseModel):
    """What a consumer asks the estimator (C4) to price."""

    model_config = ConfigDict(frozen=True)

    phase: RuntimePhaseName
    operation: RuntimeOperation

    model_identity: str | None = None
    model_family: str | None = None
    parameter_count: int | None = Field(default=None, gt=0)
    parameter_count_realized: bool = Field(
        default=False,
        description="True when parameter_count was recomputed from the "
        "implemented model (§16.7); False for LLM-authored estimates.",
    )
    model_features: dict[str, Any] = Field(default_factory=dict)

    batch_size: int = Field(gt=0)
    segment_length: int = Field(gt=0)
    train_steps: int = Field(ge=0)
    inference_batches: int = Field(ge=0)

    dtype: str = "float32"
    device: str | None = None
    workspace: str | None = None

    executable_model_available: bool = False
    allow_live_probe: bool = False


class RuntimeEstimate(BaseModel):
    """One runtime estimate with provenance, uncertainty, applicability,
    and DERIVED decision eligibility.

    Invariants (schema-enforced):
    * ``blocking_eligible``/``formal_execution_eligible`` must equal the
      derivation from provenance + measurement state — a static or
      historical prior with blocking authority is unrepresentable;
    * ``lower_seconds <= expected_seconds <= upper_seconds`` when all
      are present;
    * training/inference are separate fields (§16.6) — a combined-only
      estimate leaves them ``None`` explicitly rather than folding one
      into the other.
    """

    model_config = ConfigDict(frozen=True)

    expected_seconds: float | None = Field(default=None, gt=0.0)
    lower_seconds: float | None = Field(default=None, gt=0.0)
    upper_seconds: float | None = Field(default=None, gt=0.0)

    training_seconds: float | None = Field(default=None, ge=0.0)
    inference_seconds: float | None = Field(default=None, ge=0.0)
    setup_seconds: float | None = Field(default=None, ge=0.0)

    peak_vram_gb: float | None = Field(default=None, gt=0.0)

    provenance: PredictionSource
    calibration_id: str | None = None
    hardware_profile_id: str | None = None
    probe_id: str | None = None

    applicability: RuntimeApplicability = "not_applicable"
    confidence: Confidence

    verification_passed: bool = False
    steady_state: bool = False
    concurrency_identity: ConcurrencyIdentity | None = None
    #: V20 PR C. The verdict from a bounded occupancy window, when one was
    #: observed. ``None`` means no window existed, NOT that the measurement
    #: was found invalid — the two are different claims, and conflating them
    #: is how presence became doubt in the first place.
    measurement_validity: MeasurementValidity | None = None

    advisory_eligible: bool = True
    blocking_eligible: bool
    formal_execution_eligible: bool

    warnings: tuple[str, ...] = ()

    @property
    def rank(self) -> int:
        return evidence_rank(self.provenance)

    @property
    def contended(self) -> bool:
        return self.concurrency_identity in ("foreign_contended", "unknown_contention")

    @model_validator(mode="after")
    def _eligibility_is_derived(self) -> RuntimeEstimate:
        advisory, blocking, formal = derive_decision_eligibility(
            self.provenance,
            verification_passed=self.verification_passed,
            steady_state=self.steady_state,
            contended=self.contended,
            measurement_validity=self.measurement_validity,
            concurrency_identity=self.concurrency_identity,
        )
        problems: list[str] = []
        if self.advisory_eligible is not advisory:
            problems.append(f"advisory_eligible must be {advisory}")
        if self.blocking_eligible is not blocking:
            problems.append(
                f"blocking_eligible must be {blocking} for provenance="
                f"{self.provenance!r} (contended={self.contended})"
            )
        if self.formal_execution_eligible is not formal:
            problems.append(
                f"formal_execution_eligible must be {formal} for provenance="
                f"{self.provenance!r} (verification_passed="
                f"{self.verification_passed}, steady_state={self.steady_state})"
            )
        if problems:
            raise ValueError(
                "decision eligibility is DERIVED from provenance, never "
                "caller-assigned: " + "; ".join(problems)
            )
        ordered = [
            v
            for v in (self.lower_seconds, self.expected_seconds, self.upper_seconds)
            if v is not None
        ]
        if ordered != sorted(ordered):
            raise ValueError(
                f"lower/expected/upper must be non-decreasing; got "
                f"{self.lower_seconds}/{self.expected_seconds}/{self.upper_seconds}"
            )
        return self


def make_estimate(
    *,
    provenance: PredictionSource,
    confidence: Confidence,
    verification_passed: bool = False,
    steady_state: bool = False,
    concurrency_identity: ConcurrencyIdentity | None = None,
    measurement_validity: MeasurementValidity | None = None,
    **fields: Any,
) -> RuntimeEstimate:
    """Construct a ``RuntimeEstimate`` with eligibility DERIVED — the only
    supported construction path for producers/adapters."""
    contended = concurrency_identity in ("foreign_contended", "unknown_contention")
    advisory, blocking, formal = derive_decision_eligibility(
        provenance,
        verification_passed=verification_passed,
        steady_state=steady_state,
        contended=contended,
        measurement_validity=measurement_validity,
        concurrency_identity=concurrency_identity,
    )
    return RuntimeEstimate(
        provenance=provenance,
        confidence=confidence,
        verification_passed=verification_passed,
        steady_state=steady_state,
        concurrency_identity=concurrency_identity,
        measurement_validity=measurement_validity,
        advisory_eligible=advisory,
        blocking_eligible=blocking,
        formal_execution_eligible=formal,
        **fields,
    )


# ── Read-only adapters for the four existing producers ───────────────────────


def from_proposer_preflight(verdict: dict[str, Any]) -> RuntimeEstimate:
    """Wrap an ``estimate_proposal_time`` result (C1 advisory dict).

    Static tier: never blocking-eligible, low confidence, combined
    operation (the C1 dict does not split phases)."""
    if verdict.get("provenance", "static_uncalibrated") != "static_uncalibrated":
        raise ValueError(
            f"proposer pre-flight adapter expects static_uncalibrated, got "
            f"{verdict.get('provenance')!r}"
        )
    minutes = float(verdict["estimated_minutes"])
    return make_estimate(
        provenance="static_uncalibrated",
        confidence="low",
        expected_seconds=minutes * 60.0 if minutes > 0 else None,
        warnings=(str(verdict.get("verdict", "")),),
    )


def from_time_eval_result(result: dict[str, Any]) -> RuntimeEstimate:
    """Wrap a TimeEval wrapper ``run_skill`` RESULT (tuner-side gate).

    Real shape (``wrapper.py:812-824``): ``status``, ``feasible``,
    ``estimated_minutes``, ``breakdown.source`` (``static_uncalibrated``,
    ``real_dataset_warmup``, or ``store``), ``phase_breakdown`` =
    {phase: estimator result with ``seconds``},
    ``inference_batch_uncalibrated``.
    Warmup-backed estimates are measurement-backed but NOT
    steady-state-verified at this layer, so they are blocking-capable
    per §7.4 yet never formal-eligible here (RT2 in-process
    verification owns that).

    C8: ``store`` is the RT3 observation-store reuse path — a unit time
    measured in an EARLIER attempt, i.e. a historical prior (tier 1). It
    never blocks alone, which is why the wrapper stamps
    ``formal_execution_eligible: False`` on it."""
    if result.get("status") != "success":
        raise ValueError(f"cannot wrap a non-success TimeEval result: {result.get('status')!r}")
    raw_source = (result.get("breakdown") or {}).get("source")
    if raw_source not in ("static_uncalibrated", "real_dataset_warmup", "store"):
        raise ValueError(f"unexpected TimeEval breakdown source: {raw_source!r}")
    source = "historical_observation_prior" if raw_source == "store" else raw_source
    phases = result.get("phase_breakdown") or {}

    def _phase_seconds(name: str) -> float | None:
        entry = phases.get(name)
        return float(entry["seconds"]) if entry and "seconds" in entry else None

    minutes = result.get("estimated_minutes")
    warn = result.get("inference_batch_uncalibrated")
    return make_estimate(
        provenance=source,  # type: ignore[arg-type]
        confidence="medium" if source == "real_dataset_warmup" else "low",
        expected_seconds=float(minutes) * 60.0 if minutes else None,
        training_seconds=_phase_seconds("training"),
        inference_seconds=_phase_seconds("inference"),
        warnings=tuple(w for w in ((str(warn) if warn else None),) if w),
    )


def from_runtime_observation(record: dict[str, Any]) -> RuntimeEstimate:
    """Wrap one RT2 runtime-observation sidecar record (per-attempt JSONL
    line). Components carry full ``RuntimePrediction`` dumps; the
    envelope aggregates their seconds and takes the WEAKEST component
    state (an estimate is only as verified as its least-verified
    phase)."""
    components: dict[str, dict] = record.get("components") or {}
    if not components:
        raise ValueError("observation record has no components")
    # A component without a prediction is a PROVENANCE GAP (e.g. the trial
    # attempt before adaptive inference verification formed one). Gaps are
    # excluded from pricing and surfaced as warnings — never fabricated as
    # static provenance (provenance.py: "a provenance gap is recorded as a
    # gap, never fabricated").
    preds = {
        name: c["prediction"]
        for name, c in components.items()
        if isinstance(c.get("prediction"), dict)
    }
    if not preds:
        raise ValueError("observation record has no priced components")
    unpriced = sorted(set(components) - set(preds))
    seconds = {
        n: float(p["predicted_seconds"]) for n, p in preds.items() if p.get("predicted_seconds")
    }
    all_verified = all(p.get("verification") == "passed" for p in preds.values())
    all_steady = all(bool(p.get("steady_state")) for p in preds.values())
    weakest = min(preds.values(), key=lambda p: evidence_rank(p["source"]))
    order = {"low": 0, "medium": 1, "high": 2}
    confidences: list[str] = [p.get("confidence", "low") for p in preds.values()]
    return make_estimate(
        provenance=weakest["source"],
        confidence=min(confidences, key=lambda c: order.get(c, 0)),  # type: ignore[arg-type]
        verification_passed=all_verified,
        steady_state=all_steady,
        expected_seconds=sum(seconds.values()) or None,
        setup_seconds=seconds.get("setup"),
        training_seconds=seconds.get("training"),
        inference_seconds=seconds.get("inference"),
        warnings=tuple(
            f"component '{n}' has no prediction — excluded from the total; "
            f"expected_seconds does NOT cover it"
            for n in unpriced
        ),
    )


def from_legacy_calibration_entry(entry: dict[str, Any]) -> RuntimeEstimate:
    """Wrap one k-table history entry (``calibration.make_entry`` shape)
    as a TRAINING-phase historical prior. Never blocking-eligible alone
    (§10.3: legacy priors never bypass live verification)."""
    actual_min = entry.get("actual_minutes")
    if actual_min is None or float(actual_min) <= 0:
        raise ValueError("legacy calibration entry has no usable actual_minutes")
    return make_estimate(
        provenance="legacy_calibration_prior",
        confidence="low",
        expected_seconds=float(actual_min) * 60.0,
        training_seconds=float(actual_min) * 60.0,
        applicability="not_applicable",
        warnings=(
            "legacy k-table prior: applicability labeling arrives in C6/C7; "
            "treat as similarity evidence only",
        ),
    )
