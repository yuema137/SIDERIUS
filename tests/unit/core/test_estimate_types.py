"""C3 — canonical runtime-evidence envelope types.

Contract: docs/design/runtime_estimation_and_calibration.md §7.2/§7.3/
§8.4 + the §23-C3 stage. Proves:

* the illegal state ``static (or historical) prior + blocking
  authority`` is UNREPRESENTABLE — the validator rejects any
  non-derived eligibility assignment;
* eligibility derivation: priors advisory-only; measurement-backed
  blocking-capable unless contended; formal eligibility additionally
  requires verification passed + steady state (mirror of the records.py
  admission invariant);
* §8.4 evidence precedence is a total order over every canonical
  provenance value, with the design's six tiers;
* the four read-only adapters produce validated estimates from REAL
  producer artifacts — including genuine RT2 sidecar records preserved
  from the stopped V19 wave-1 forensic snapshot;
* the extended vocabulary (bounded_live_probe[_calibrated],
  complete_observation) composes with the EXISTING records.py
  admission invariant unchanged.
"""

from __future__ import annotations

import json
import typing
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.utils.proposer_preflight import estimate_proposal_time
from core.runtime_control.estimate_types import (
    _EVIDENCE_TIER,
    RuntimeEstimate,
    RuntimeEstimateRequest,
    derive_decision_eligibility,
    evidence_rank,
    from_legacy_calibration_entry,
    from_proposer_preflight,
    from_runtime_observation,
    from_time_eval_result,
    make_estimate,
)
from core.runtime_control.records import (
    MEASUREMENT_BACKED_SOURCES,
    PredictionSource,
    RuntimePrediction,
)

FIXTURES = Path(__file__).parent / "fixtures"

# Every canonical provenance value (kept in sync with the Literal by the
# vocabulary-total test below).
ALL_SOURCES: tuple[str, ...] = typing.get_args(PredictionSource)


# ---------------------------------------------------------------------------
# Vocabulary + precedence
# ---------------------------------------------------------------------------


class TestVocabularyAndPrecedence:
    def test_every_source_has_exactly_one_tier(self):
        assert set(_EVIDENCE_TIER) == set(ALL_SOURCES), (
            "evidence tiers and the canonical PredictionSource Literal "
            "must cover exactly the same values (one vocabulary, §7.3)"
        )

    def test_six_design_tiers_in_order(self):
        assert evidence_rank("static_uncalibrated") == 0
        assert evidence_rank("historical_observation_prior") == 1
        assert evidence_rank("legacy_calibration_prior") == 1
        assert evidence_rank("bounded_live_probe") == 2
        assert evidence_rank("bounded_live_probe_calibrated") == 3
        assert evidence_rank("real_training_verification") == 4
        assert evidence_rank("complete_observation") == 5

    def test_lower_rank_never_outranks_measurement(self):
        for prior in ("static_uncalibrated", "legacy_calibration_prior"):
            for measured in sorted(MEASUREMENT_BACKED_SOURCES):
                assert evidence_rank(prior) < evidence_rank(measured)

    def test_new_sources_are_measurement_backed(self):
        for s in (
            "bounded_live_probe",
            "bounded_live_probe_calibrated",
            "complete_observation",
        ):
            assert s in MEASUREMENT_BACKED_SOURCES

    def test_records_admission_invariant_holds_for_new_sources(self):
        """The EXISTING RuntimePrediction invariant governs the extended
        vocabulary unchanged: a probe source without verification/steady
        state cannot be formal-eligible."""
        with pytest.raises(ValidationError):
            RuntimePrediction(
                predicted_seconds=10.0,
                source="bounded_live_probe",
                formal_execution_eligible=True,
                steady_state=False,
                verification="passed",
                confidence="medium",
                safety_factor=1.0,
            )


# ---------------------------------------------------------------------------
# Eligibility derivation + unrepresentable illegal states
# ---------------------------------------------------------------------------


class TestEligibilityDerivation:
    def test_priors_can_never_block(self):
        for source in ALL_SOURCES:
            if source in MEASUREMENT_BACKED_SOURCES:
                continue
            advisory, blocking, formal = derive_decision_eligibility(
                source, verification_passed=True, steady_state=True
            )
            assert advisory is True
            assert blocking is False
            assert formal is False

    def test_measured_blocks_unless_contended(self):
        _, blocking, _ = derive_decision_eligibility("bounded_live_probe")
        assert blocking is True
        _, blocking_contended, _ = derive_decision_eligibility("bounded_live_probe", contended=True)
        assert blocking_contended is False

    def test_formal_requires_verified_steady_state(self):
        _, _, formal = derive_decision_eligibility(
            "real_training_verification", verification_passed=True, steady_state=True
        )
        assert formal is True
        _, _, no_verif = derive_decision_eligibility(
            "real_training_verification", verification_passed=False, steady_state=True
        )
        assert no_verif is False

    def test_static_plus_blocking_is_unrepresentable(self):
        with pytest.raises(ValidationError, match="DERIVED"):
            RuntimeEstimate(
                provenance="static_uncalibrated",
                confidence="low",
                advisory_eligible=True,
                blocking_eligible=True,  # illegal
                formal_execution_eligible=False,
            )

    def test_historical_plus_formal_is_unrepresentable(self):
        with pytest.raises(ValidationError, match="DERIVED"):
            RuntimeEstimate(
                provenance="legacy_calibration_prior",
                confidence="low",
                advisory_eligible=True,
                blocking_eligible=False,
                formal_execution_eligible=True,  # illegal
            )

    def test_contended_probe_loses_blocking(self):
        est = make_estimate(
            provenance="bounded_live_probe",
            confidence="medium",
            concurrency_identity="foreign_contended",
            expected_seconds=100.0,
        )
        assert est.contended is True
        assert est.blocking_eligible is False
        assert est.formal_execution_eligible is False

    def test_bounds_ordering_enforced(self):
        with pytest.raises(ValidationError, match="non-decreasing"):
            make_estimate(
                provenance="bounded_live_probe",
                confidence="medium",
                lower_seconds=100.0,
                expected_seconds=50.0,
            )

    def test_request_validates(self):
        req = RuntimeEstimateRequest(
            phase="trial",
            operation="combined",
            parameter_count=18_400_000,
            batch_size=8,
            segment_length=1000,
            train_steps=25_000,
            inference_batches=400,
        )
        assert req.parameter_count_realized is False  # LLM-authored default


# ---------------------------------------------------------------------------
# Adapters — real producer artifacts
# ---------------------------------------------------------------------------


class TestAdapters:
    def test_proposer_preflight_adapter_on_real_verdict(self):
        verdict = estimate_proposal_time(
            model_type="audit_probe_arch",
            model_config={"segmentation_size": 40_000},
            train_config={"epochs": 1, "batch_size": 8},
            loss_config={"loss_type": "ce"},
            num_params=18_400_000,
            time_budget_minutes=20.0,
        )
        est = from_proposer_preflight(verdict)
        assert est.provenance == "static_uncalibrated"
        assert est.blocking_eligible is False
        assert est.formal_execution_eligible is False
        assert est.rank == 0
        assert est.expected_seconds and est.expected_seconds > 0

    def test_observation_adapter_on_formal_forensic_sidecar(self):
        """REAL RT2 record from the stopped V19 wave-1 attempt (formal
        round): all three components priced → measurement-backed envelope
        with separate setup/training/inference seconds (§16.6)."""
        record = json.loads((FIXTURES / "runtime_observation_wave1_formal.json").read_text())
        est = from_runtime_observation(record)
        assert est.provenance in MEASUREMENT_BACKED_SOURCES
        assert est.setup_seconds is not None
        assert est.training_seconds is not None
        assert est.inference_seconds is not None
        assert est.expected_seconds == pytest.approx(
            est.setup_seconds + est.training_seconds + est.inference_seconds
        )
        # training and inference remain SEPARATE values
        assert est.training_seconds != est.inference_seconds
        assert est.warnings == ()

    def test_observation_adapter_records_provenance_gap_honestly(self):
        """The wave-1 TRIAL record has components.inference.prediction ==
        None (adaptive inference verification had not formed one yet).
        The adapter must EXCLUDE the gap and warn — never fabricate
        static provenance for an absent prediction."""
        record = json.loads((FIXTURES / "runtime_observation_wave1_trial.json").read_text())
        est = from_runtime_observation(record)
        assert est.provenance in MEASUREMENT_BACKED_SOURCES  # weakest PRICED
        assert est.inference_seconds is None
        assert est.expected_seconds == pytest.approx(est.setup_seconds + est.training_seconds)
        assert any("inference" in w and "does NOT cover" in w for w in est.warnings)

    def test_time_eval_adapter_static_shape(self):
        result = {
            "status": "success",
            "feasible": True,
            "estimated_minutes": 4.3,
            "breakdown": {"source": "static_uncalibrated"},
            "phase_breakdown": {
                "training": {"phase": "training", "seconds": 65.0},
                "inference": {"phase": "inference", "seconds": 136.3},
                "scoring": {"phase": "scoring", "seconds": 55.2},
            },
            "inference_batch_uncalibrated": "inference_batch_uncalibrated: fallback 25",
        }
        est = from_time_eval_result(result)
        assert est.provenance == "static_uncalibrated"
        assert est.blocking_eligible is False
        assert est.training_seconds == 65.0
        assert est.inference_seconds == 136.3
        assert any("fallback 25" in w for w in est.warnings)

    def test_time_eval_adapter_warmup_shape_blocking_capable(self):
        result = {
            "status": "success",
            "feasible": True,
            "estimated_minutes": 2.0,
            "breakdown": {"source": "real_dataset_warmup"},
            "phase_breakdown": {
                "training": {"phase": "training", "seconds": 60.0},
                "inference": {"phase": "inference", "seconds": 40.0},
                "scoring": {"phase": "scoring", "seconds": 20.0},
            },
            "inference_batch_uncalibrated": None,
        }
        est = from_time_eval_result(result)
        assert est.provenance == "real_dataset_warmup"
        assert est.blocking_eligible is True
        assert est.formal_execution_eligible is False  # RT2 owns formal

    def test_legacy_calibration_adapter(self):
        entry = {
            "gpu_name": "NVIDIA GeForce RTX 5090",
            "model_type": "punet_hf_loss_solidification_tiny",
            "seg_size": 40_000,
            "batch_size": 8,
            "total_steps": 3125,
            "warmup_ms_per_step": 3.7917,
            "actual_ms_per_step": 4.109,
            "ratio": 1.0837,
            "estimated_minutes": 1.2,
            "actual_minutes": 1.4,
            "estimate_violated": True,
            "timestamp": "2026-07-20T16:10:16Z",
        }
        est = from_legacy_calibration_entry(entry)
        assert est.provenance == "legacy_calibration_prior"
        assert est.blocking_eligible is False
        assert est.rank == 1
        assert est.training_seconds == pytest.approx(84.0)

    def test_adapter_rejects_wrong_provenance(self):
        with pytest.raises(ValueError):
            from_proposer_preflight({"estimated_minutes": 5, "provenance": "real_dataset_warmup"})
        with pytest.raises(ValueError):
            from_time_eval_result({"status": "error"})
        with pytest.raises(ValueError):
            from_runtime_observation({"components": {}})
        with pytest.raises(ValueError):
            from_legacy_calibration_entry({"actual_minutes": 0})


pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")
