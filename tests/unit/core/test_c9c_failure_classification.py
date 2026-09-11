"""C9c — candidate vs infrastructure failure classification, and the
chain-level consequence of the infrastructure class.

The distinction exists to answer one question: after this refusal, may
the chain try another candidate?

    candidate      -> yes. The model was judged and found wanting.
    infrastructure -> no. The machinery that judges was broken, so the
                      next candidate would meet the same failure.

Backward compatibility is part of the contract: records written before
`failure_class` existed carry None, and every reader must stay
conservative in that case.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from core.runtime_control.observation_store import component_calibration_eligible
from core.runtime_control.records import AdmissionRecord, RuntimeObservation
from core.runtime_control.session import (
    RuntimeControlPolicy,
    RuntimeVerificationSession,
    WatchdogConfig,
)

_STORAGE = {
    "dataset_root": "/data",
    "file_count": 1,
    "files_present": 1,
    "expected_raw_bytes": 1_000,
    "filesystem_type": "ext4",
}

FORMAL = RuntimeControlPolicy(
    operator_budget_seconds=7200.0,
    safety_factor=2.0,
    watchdog=WatchdogConfig(enabled=True, floor_seconds=120.0, safety_factor=3.5),
)


def _session(tmp_path, policy=FORMAL) -> RuntimeVerificationSession:
    session = RuntimeVerificationSession(str(tmp_path / "rv.json"), policy=policy)
    session.complete_setup(storage_provenance=_STORAGE)
    return session


def _with_training(session, seconds: float):
    from core.runtime_control.records import PhaseComponentRecord, RuntimePrediction

    session._components["training"] = PhaseComponentRecord(
        prediction=RuntimePrediction(
            predicted_seconds=seconds,
            source="real_training_verification",
            formal_execution_eligible=True,
            steady_state=True,
            verification="passed",
            confidence="high",
            ms_per_unit=10.0,
            n_steady_units=7,
            unit_count=100,
            safety_factor=1.0,
        )
    )
    return session


class TestSchemaCompatibility:
    def test_default_is_none(self):
        record = AdmissionRecord(decision="admitted", stage="post_setup")
        assert record.failure_class is None

    def test_legacy_record_without_the_field_still_validates(self):
        legacy = {
            "decision": "rejected",
            "stage": "post_setup_runtime_verification",
            "reason": "written before failure_class existed",
        }
        record = AdmissionRecord.model_validate(legacy)
        assert record.failure_class is None
        assert record.decision == "rejected"

    def test_the_decision_literal_is_unchanged(self):
        """Option B: no "aborted" value — every existing reader that keys
        on "admitted"/"rejected" keeps behaving correctly."""
        with pytest.raises(ValidationError):
            AdmissionRecord(decision="aborted", stage="s")  # type: ignore[arg-type]


class TestAdmissionClassification:
    def test_allow_is_admitted_and_unclassified(self, tmp_path):
        record = _with_training(_session(tmp_path), 100.0).decide_admission()
        assert record.decision == "admitted"
        assert record.failure_class is None

    def test_over_budget_is_candidate_class(self, tmp_path):
        record = _with_training(_session(tmp_path), 3700.0).decide_admission()
        assert record.decision == "rejected"
        assert record.failure_class == "candidate"
        # numeric parity preserved: 3700 × 2.0
        assert record.avoided_predicted_runtime_seconds == pytest.approx(7400.0, abs=0.5)

    def test_verification_failure_is_candidate_class(self, tmp_path):
        session = _session(tmp_path)
        session._verification_failures["training"] = "did not stabilize"
        record = session.decide_admission()
        assert record.decision == "rejected"
        assert record.failure_class == "candidate"

    def test_evidence_channel_failure_is_infrastructure_class(self, tmp_path):
        session = _with_training(_session(tmp_path), 100.0)
        session.record_evidence_channel_failure("calibration registry corrupt")
        record = session.decide_admission()
        assert record.decision == "rejected"
        assert record.failure_class == "infrastructure"
        assert "calibration registry corrupt" in (record.reason or "")

    def test_infrastructure_outranks_a_within_budget_admission(self, tmp_path):
        """A broken channel is not overridden by a comfortable budget."""
        session = _with_training(_session(tmp_path), 1.0)
        session.record_evidence_channel_failure("telemetry unavailable")
        assert session.decide_admission().failure_class == "infrastructure"

    def test_infrastructure_outranks_record_only_mode(self, tmp_path):
        """Record-only runs still depend on the channel to record."""
        session = _session(tmp_path, policy=RuntimeControlPolicy())
        session.record_evidence_channel_failure("sidecar write failed")
        record = session.decide_admission()
        assert record.decision == "rejected"
        assert record.failure_class == "infrastructure"

    def test_the_classification_is_persisted_to_the_sidecar(self, tmp_path):
        session = _session(tmp_path)
        session.record_evidence_channel_failure("schema mismatch")
        session.decide_admission()
        payload = json.loads((tmp_path / "rv.json").read_text())
        assert payload["admission"]["failure_class"] == "infrastructure"
        RuntimeObservation.model_validate(payload)


class TestCalibrationExclusion:
    def _observation(self, admission: AdmissionRecord | None) -> RuntimeObservation:
        from core.runtime_control.records import PhaseComponentRecord, PhaseMeasurement

        return RuntimeObservation(
            timestamp="2026-07-30T00:00:00Z",
            final_status="completed",
            components={
                "training": PhaseComponentRecord(
                    measurement=PhaseMeasurement(
                        unit="optimizer_step",
                        n_measured_units=7,
                        n_stabilization_units=3,
                        unit_time_ms_median=20.0,
                        steady_state_reached=True,
                        total_measurement_seconds=0.2,
                        raw_timings_ms=[20.0],
                    )
                )
            },
            admission=admission,
        )

    def test_neither_failure_class_updates_calibration(self):
        for failure_class in ("candidate", "infrastructure"):
            obs = self._observation(
                AdmissionRecord(decision="rejected", failure_class=failure_class, stage="s")
            )
            assert component_calibration_eligible(obs, "training") is False

    def test_a_legacy_unclassified_rejection_is_still_excluded(self):
        obs = self._observation(AdmissionRecord(decision="rejected", stage="s"))
        assert component_calibration_eligible(obs, "training") is False

    def test_an_admitted_observation_remains_eligible(self):
        obs = self._observation(AdmissionRecord(decision="admitted", stage="s"))
        assert component_calibration_eligible(obs, "training") is True


class TestExecutorStatusRouting:
    """The executor must surface the two classes as different statuses:
    one consumes an attempt, the other stops the chain."""

    def _classify(self, admission: dict) -> str:
        import core.sandbox_executor as se

        block = {"admission": admission}
        # Mirror of the branch in execute_training: the routing rule under
        # test is which status an admission block maps to.
        if (block.get("admission") or {}).get("decision") == "rejected":
            if (block.get("admission") or {}).get("failure_class") == "infrastructure":
                return "aborted_infrastructure"
            return "rejected_time_risk"
        assert se is not None
        return "ok"

    def test_candidate_rejection_consumes_an_attempt(self):
        assert self._classify({"decision": "rejected", "failure_class": "candidate"}) == (
            "rejected_time_risk"
        )

    def test_infrastructure_rejection_aborts(self):
        assert self._classify({"decision": "rejected", "failure_class": "infrastructure"}) == (
            "aborted_infrastructure"
        )

    def test_legacy_rejection_keeps_the_historical_path(self):
        assert self._classify({"decision": "rejected"}) == "rejected_time_risk"

    def test_the_production_branch_exists_verbatim(self):
        """Guard the real routing code, not only this mirror of it."""
        from pathlib import Path

        source = Path("src/core/sandbox_executor.py").read_text(encoding="utf-8")
        assert 'admission_block.get("failure_class") == "infrastructure"' in source
        assert '"status": "aborted_infrastructure"' in source
