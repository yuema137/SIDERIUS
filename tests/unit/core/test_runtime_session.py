"""
RT2-B unit tests: RuntimeControlPolicy + RuntimeVerificationSession.

Design: docs/design/runtime_estimation_and_watchdog.md §2.1/§2.2/§6.2.
Pins the event-log contract (observation exists from setup start, every
stage transition atomically persisted), the RT2-B admission semantics
(reject exactly when measured setup alone exceeds the operator budget),
and the schema validity of the observation at EVERY stage — a partially
complete observation is still a valid RuntimeObservation.
"""

from __future__ import annotations

import json
from typing import ClassVar

import pytest
from pydantic import ValidationError

from core.runtime_control.records import RuntimeObservation
from core.runtime_control.session import (
    ADMISSION_STAGE_POST_SETUP,
    RuntimeControlPolicy,
    RuntimeVerificationSession,
)
from core.runtime_control.workload import ResolvedPhaseWorkload

_STORAGE = {
    "dataset_root": "/data",
    "file_count": 2,
    "files_present": 2,
    "expected_raw_bytes": 4_000,
    "filesystem_type": "ext4",
}


def _load(path) -> dict:
    with open(path) as f:
        return json.load(f)


class TestRuntimeControlPolicy:
    def test_defaults_are_record_only(self):
        assert RuntimeControlPolicy().operator_budget_seconds is None

    def test_budget_must_be_positive(self):
        with pytest.raises(ValidationError):
            RuntimeControlPolicy(operator_budget_seconds=0.0)
        with pytest.raises(ValidationError):
            RuntimeControlPolicy(operator_budget_seconds=-5.0)

    def test_frozen(self):
        policy = RuntimeControlPolicy(operator_budget_seconds=60.0)
        with pytest.raises(ValidationError):
            policy.operator_budget_seconds = 10.0  # type: ignore[misc]


class TestEventLogLifecycle:
    def test_sidecar_exists_from_creation(self, tmp_path):
        path = tmp_path / "rv.json"
        RuntimeVerificationSession(str(path), attempt_id="exp_1")
        obs = _load(path)
        assert obs["final_status"] == "setup_started"
        assert obs["attempt_id"] == "exp_1"
        # Valid observation at the very first stage.
        RuntimeObservation.model_validate(obs)

    def test_every_stage_transition_is_persisted_and_valid(self, tmp_path):
        path = tmp_path / "rv.json"
        session = RuntimeVerificationSession(str(path), attempt_id="exp_2")

        session.complete_setup(storage_provenance=_STORAGE)
        obs = _load(path)
        assert obs["final_status"] == "setup_complete"
        RuntimeObservation.model_validate(obs)

        session.decide_admission()
        obs = _load(path)
        assert obs["final_status"] == "admitted"
        RuntimeObservation.model_validate(obs)

        session.record_phase_actual("training", 42.0)
        session.finalize("completed")
        obs = _load(path)
        assert obs["final_status"] == "completed"
        parsed = RuntimeObservation.model_validate(obs)
        assert parsed.components["training"].actual_seconds == pytest.approx(42.0)

    def test_setup_component_is_measurement_backed_and_eligible(self, tmp_path):
        session = RuntimeVerificationSession(str(tmp_path / "rv.json"))
        session.complete_setup(storage_provenance=_STORAGE)
        setup = session.observation.components["setup"]
        assert setup.prediction is not None
        assert setup.prediction.source == "real_dataset_setup"
        assert setup.prediction.formal_execution_eligible is True
        # Prediction IS the measurement for the in-subprocess setup, so
        # the error is zero by construction (§2.2).
        assert setup.prediction_error is not None
        assert setup.prediction_error.log_error == pytest.approx(0.0, abs=1e-9)

    def test_training_workload_recorded_without_prediction(self, tmp_path):
        session = RuntimeVerificationSession(str(tmp_path / "rv.json"))
        workload = ResolvedPhaseWorkload(
            phase="training", unit="optimizer_step", unit_count=480_000
        )
        session.complete_setup(storage_provenance=_STORAGE, training_workload=workload)
        training = session.observation.components["training"]
        assert training.workload is not None
        assert training.workload.unit_count == 480_000
        assert training.prediction is None  # prediction arrives in RT2-C

    def test_storage_provenance_lands_on_observation(self, tmp_path):
        session = RuntimeVerificationSession(str(tmp_path / "rv.json"))
        session.complete_setup(storage_provenance=_STORAGE)
        storage = session.observation.storage
        assert storage["dataset_root"] == "/data"
        assert storage["cache_state"] in (
            "cold_first_access",
            "warm_page_cache",
            "already_materialized",
            "unknown",
        )
        assert "rss_bytes_before_setup" in storage
        assert "rss_bytes_after_setup" in storage


class TestAdmissionSemantics:
    def test_no_budget_admits_record_only(self, tmp_path):
        session = RuntimeVerificationSession(str(tmp_path / "rv.json"))
        session.complete_setup(storage_provenance=_STORAGE)
        adm = session.decide_admission()
        assert adm.decision == "admitted"
        assert adm.stage == ADMISSION_STAGE_POST_SETUP
        assert adm.reason is not None and "record-only" in adm.reason

    def test_setup_exceeding_budget_rejects(self, tmp_path):
        session = RuntimeVerificationSession(
            str(tmp_path / "rv.json"),
            policy=RuntimeControlPolicy(operator_budget_seconds=1e-9),
        )
        session.complete_setup(storage_provenance=_STORAGE)
        adm = session.decide_admission()
        assert adm.decision == "rejected"
        assert adm.setup_cost_seconds is not None and adm.setup_cost_seconds > 0.0
        assert adm.verification_cost_seconds == 0.0
        assert session.observation.final_status == "rejected"

    def test_setup_within_budget_admits_pending_verification(self, tmp_path):
        session = RuntimeVerificationSession(
            str(tmp_path / "rv.json"),
            policy=RuntimeControlPolicy(operator_budget_seconds=3600.0),
        )
        session.complete_setup(storage_provenance=_STORAGE)
        adm = session.decide_admission()
        assert adm.decision == "admitted"
        assert adm.reason is not None and "pending" in adm.reason

    def test_admission_before_setup_raises(self, tmp_path):
        session = RuntimeVerificationSession(str(tmp_path / "rv.json"))
        with pytest.raises(RuntimeError, match="complete_setup"):
            session.decide_admission()

    def test_policy_recorded_on_observation(self, tmp_path):
        session = RuntimeVerificationSession(
            str(tmp_path / "rv.json"),
            policy=RuntimeControlPolicy(operator_budget_seconds=120.0),
        )
        recorded = session.observation.runtime_policy
        assert recorded["operator_budget_seconds"] == 120.0
        # Full validated policy is recorded (§5): safety factor + the
        # RT2-C verification stopping policy materialize alongside.
        assert recorded["safety_factor"] == 1.0
        assert "verification" in recorded


class TestPhaseVerificationIntegration:
    """RT2-C: session-level verification lifecycle + admission."""

    @staticmethod
    def _policy(**overrides) -> RuntimeControlPolicy:
        from core.runtime_control.adaptive import AdaptiveVerificationConfig
        from core.runtime_control.steady_state import SteadyStateConfig

        verification = AdaptiveVerificationConfig(
            steady=SteadyStateConfig(window=4, stable_windows=3, rel_spread_tol=0.10),
            min_timed_steps=5,
            min_timed_ms=0.0,
            max_steps=50,
        )
        return RuntimeControlPolicy(verification=verification, **overrides)

    def _session_with_setup(self, tmp_path, *, unit_count: int, **policy_overrides):
        session = RuntimeVerificationSession(
            str(tmp_path / "rv.json"), policy=self._policy(**policy_overrides)
        )
        session.complete_setup(
            storage_provenance=_STORAGE,
            training_workload=ResolvedPhaseWorkload(
                phase="training", unit="optimizer_step", unit_count=unit_count
            ),
        )
        return session

    def _run_verification(self, session, trace):
        verifier = session.start_phase_verification("training", unit="optimizer_step")
        for t in trace:
            verifier.feed(t)
            if verifier.is_terminal:
                break
        return session.complete_phase_verification(
            "training", verifier, source="real_training_verification"
        )

    def test_verified_prediction_recorded_and_admitted(self, tmp_path):
        session = self._session_with_setup(tmp_path, unit_count=100, operator_budget_seconds=3600.0)
        prediction = self._run_verification(session, [10.0] * 30)
        assert prediction is not None
        assert prediction.source == "real_training_verification"

        adm = session.decide_admission(stage="post_training_verification")
        assert adm.decision == "admitted"
        assert adm.stage == "post_training_verification"
        assert adm.verification_cost_seconds is not None
        assert adm.verification_cost_seconds > 0.0

        training = session.observation.components["training"]
        assert training.prediction is not None
        assert training.measurement is not None
        assert training.workload is not None  # preserved from setup

    def test_budget_exceeding_prediction_rejects(self, tmp_path):
        # 480k steps × 10 ms = 4800 s ≫ 120 s budget (the incident shape).
        session = self._session_with_setup(
            tmp_path, unit_count=480_000, operator_budget_seconds=120.0
        )
        prediction = self._run_verification(session, [10.0] * 30)
        assert prediction is not None
        adm = session.decide_admission(stage="post_training_verification")
        assert adm.decision == "rejected"
        assert adm.avoided_predicted_runtime_seconds is not None
        assert adm.avoided_predicted_runtime_seconds > 4000.0

    def test_safety_factor_tightens_admission(self, tmp_path):
        # 100 steps × 10 ms = 1 s; budget 1.5 s → admitted at safety 1.0,
        # rejected at safety 2.0.
        admitted = self._session_with_setup(tmp_path, unit_count=100, operator_budget_seconds=1.5)
        self._run_verification(admitted, [10.0] * 30)
        assert admitted.decide_admission().decision == "admitted"

        rejected = RuntimeVerificationSession(
            str(tmp_path / "rv2.json"),
            policy=self._policy(operator_budget_seconds=1.5, safety_factor=2.0),
        )
        rejected.complete_setup(
            storage_provenance=_STORAGE,
            training_workload=ResolvedPhaseWorkload(
                phase="training", unit="optimizer_step", unit_count=100
            ),
        )
        self._run_verification(rejected, [10.0] * 30)
        assert rejected.decide_admission().decision == "rejected"

    def test_failed_verification_fails_closed_with_budget(self, tmp_path):
        session = self._session_with_setup(tmp_path, unit_count=100, operator_budget_seconds=3600.0)
        prediction = self._run_verification(session, [10.0 * (1.2**i) for i in range(60)])
        assert prediction is None
        adm = session.decide_admission(stage="post_training_verification")
        assert adm.decision == "rejected"
        assert adm.reason is not None and "2.11" in adm.reason

    def test_failed_verification_record_only_admits(self, tmp_path):
        session = self._session_with_setup(tmp_path, unit_count=100)  # no budget
        prediction = self._run_verification(session, [10.0 * (1.2**i) for i in range(60)])
        assert prediction is None
        adm = session.decide_admission(stage="post_training_verification")
        assert adm.decision == "admitted"
        assert adm.reason is not None and "record-only" in adm.reason
        # Evidence retained despite the failure (§6.2).
        training = session.observation.components["training"]
        assert training.measurement is not None
        assert training.prediction is None

    def test_verified_without_workload_raises(self, tmp_path):
        session = RuntimeVerificationSession(str(tmp_path / "rv.json"), policy=self._policy())
        session.complete_setup(storage_provenance=_STORAGE)  # no training workload
        verifier = session.start_phase_verification("training", unit="optimizer_step")
        for t in [10.0] * 30:
            verifier.feed(t)
            if verifier.is_terminal:
                break
        with pytest.raises(RuntimeError, match="workload"):
            session.complete_phase_verification(
                "training", verifier, source="real_training_verification"
            )

    def test_actual_after_verification_derives_error(self, tmp_path):
        session = self._session_with_setup(tmp_path, unit_count=100)
        self._run_verification(session, [10.0] * 30)
        session.record_phase_actual("training", 1.5)
        training = session.observation.components["training"]
        assert training.prediction_error is not None
        assert training.prediction_error.ratio == pytest.approx(
            1.5 / training.prediction.predicted_seconds  # type: ignore[union-attr]
        )


class TestResumeAcrossSubprocesses:
    """RT2-D: the inference subprocess continues the attempt's observation."""

    def test_resume_preserves_previous_components(self, tmp_path):
        path = str(tmp_path / "rv.json")
        first = RuntimeVerificationSession(path, attempt_id="exp_r")
        first.complete_setup(
            storage_provenance=_STORAGE,
            training_workload=ResolvedPhaseWorkload(
                phase="training", unit="optimizer_step", unit_count=100
            ),
        )
        first.decide_admission()
        first.record_phase_actual("training", 12.0)

        resumed = RuntimeVerificationSession.resume_or_start(
            path, attempt_id="exp_r", resumed_status="inference_started"
        )
        obs = resumed.observation
        assert obs.final_status == "inference_started"
        assert "setup" in obs.components and "training" in obs.components
        assert obs.components["training"].actual_seconds == pytest.approx(12.0)
        assert obs.storage["dataset_root"] == "/data"
        assert obs.admission is not None and obs.admission.decision == "admitted"
        # Setup window NOT restarted: restored from the setup actual.
        assert resumed.decide_admission().decision == "admitted"

    def test_resume_without_sidecar_starts_fresh(self, tmp_path):
        resumed = RuntimeVerificationSession.resume_or_start(
            str(tmp_path / "absent.json"), attempt_id="exp_f"
        )
        assert resumed.observation.components == {}

    def test_resume_malformed_starts_fresh(self, tmp_path):
        path = tmp_path / "rv.json"
        path.write_text("{broken")
        resumed = RuntimeVerificationSession.resume_or_start(str(path))
        assert resumed.observation.components == {}

    def test_record_phase_workload_merges(self, tmp_path):
        session = RuntimeVerificationSession(str(tmp_path / "rv.json"))
        session.record_phase_workload(
            "inference",
            ResolvedPhaseWorkload(phase="inference", unit="inference_batch", unit_count=120),
        )
        inference = session.observation.components["inference"]
        assert inference.workload is not None
        assert inference.workload.unit_count == 120

    def test_inference_dominated_worked_example(self, tmp_path):
        # §11 RT2-D checkpoint: the V18 lesson — training fits the budget
        # but inference independently blows it; the component-wise total
        # catches what a training-only estimate cannot.
        from core.runtime_control.adaptive import AdaptiveVerificationConfig
        from core.runtime_control.steady_state import SteadyStateConfig

        policy = RuntimeControlPolicy(
            operator_budget_seconds=3600.0,
            verification=AdaptiveVerificationConfig(
                steady=SteadyStateConfig(window=4, stable_windows=3, rel_spread_tol=0.10),
                min_timed_steps=5,
                min_timed_ms=0.0,
                max_steps=50,
            ),
        )
        session = RuntimeVerificationSession(str(tmp_path / "rv.json"), policy=policy)
        session.complete_setup(
            storage_provenance=_STORAGE,
            training_workload=ResolvedPhaseWorkload(
                phase="training", unit="optimizer_step", unit_count=30_000
            ),
        )
        # Training: 30k steps × 10 ms = 300 s — comfortably within budget.
        trainer = session.start_phase_verification("training", unit="optimizer_step")
        for t in [10.0] * 30:
            trainer.feed(t)
            if trainer.is_terminal:
                break
        session.complete_phase_verification(
            "training", trainer, source="real_training_verification"
        )
        assert session.decide_admission("post_training_verification").decision == "admitted"

        # Inference: 1200 batches × 6 s = 7200 s — inference-dominated.
        session.record_phase_workload(
            "inference",
            ResolvedPhaseWorkload(phase="inference", unit="inference_batch", unit_count=1200),
        )
        inf = session.start_phase_verification("inference", unit="inference_batch")
        for t in [6000.0] * 30:
            inf.feed(t)
            if inf.is_terminal:
                break
        session.complete_phase_verification("inference", inf, source="real_inference_verification")
        adm = session.decide_admission("post_inference_verification")
        assert adm.decision == "rejected"
        assert adm.avoided_predicted_runtime_seconds is not None
        assert adm.avoided_predicted_runtime_seconds > 7000.0


class TestStorePriorConsumption:
    """RT2-G: verifiers consume historical priors from the store."""

    _CONTEXT: ClassVar[dict] = {
        "precision": "float32",
        "optimizer_type": "adam",
        "model_family": "wavenet",
        "param_count": 100_000,
        "seg_size": 1000,
        "batch_size": 1,
    }

    def _store_with_observation(self, tmp_path, session) -> None:
        """Persist one CLEAN observation matching the session's key.

        §6c eligibility demands a steady measurement, so the donor runs
        a real verified verification (not just an actual) before its
        actual is recorded — exactly what a production attempt leaves
        behind.
        """
        from core.runtime_control.adaptive import AdaptiveVerificationConfig
        from core.runtime_control.observation_store import ObservationStore
        from core.runtime_control.steady_state import SteadyStateConfig

        donor = RuntimeVerificationSession(
            str(tmp_path / "donor.json"),
            policy=RuntimeControlPolicy(
                verification=AdaptiveVerificationConfig(
                    steady=SteadyStateConfig(window=4, stable_windows=3, rel_spread_tol=0.10),
                    min_timed_steps=5,
                    min_timed_ms=0.0,
                    max_steps=50,
                )
            ),
        )
        donor.complete_setup(
            storage_provenance=_STORAGE,
            training_workload=ResolvedPhaseWorkload(
                phase="training", unit="optimizer_step", unit_count=1000
            ),
        )
        donor.set_calibration_context(self._CONTEXT)
        verifier = donor.start_phase_verification("training", unit="optimizer_step")
        for t in [40.0] * 30:
            verifier.feed(t)
            if verifier.is_terminal:
                break
        donor.complete_phase_verification("training", verifier, source="real_training_verification")
        donor.record_phase_actual("training", 40.0)  # realized 40 ms/step × 1000
        # Match the donor's environment to the consuming session's so the
        # §6b env checks pass deterministically in any test environment.
        donor._environment = dict(session._environment)
        obs = donor.finalize("completed")
        ObservationStore(str(tmp_path / "store")).append(obs, writer_id="donor")

    def test_lookup_phase_prior_round_trip(self, tmp_path):
        session = RuntimeVerificationSession(
            str(tmp_path / "rv.json"),
            policy=RuntimeControlPolicy(observation_store_root=str(tmp_path / "store")),
        )
        session.complete_setup(storage_provenance=_STORAGE)
        session.set_calibration_context(self._CONTEXT)
        self._store_with_observation(tmp_path, session)
        prior = session.lookup_phase_prior("training")
        assert prior == pytest.approx(40.0)

    def test_no_store_root_or_context_yields_none(self, tmp_path):
        no_root = RuntimeVerificationSession(str(tmp_path / "a.json"))
        no_root.set_calibration_context(self._CONTEXT)
        assert no_root.lookup_phase_prior("training") is None

        no_ctx = RuntimeVerificationSession(
            str(tmp_path / "b.json"),
            policy=RuntimeControlPolicy(observation_store_root=str(tmp_path / "store")),
        )
        assert no_ctx.lookup_phase_prior("training") is None

    def test_prior_enables_verified_match_early_exit(self, tmp_path):
        from core.runtime_control.adaptive import AdaptiveVerificationConfig
        from core.runtime_control.steady_state import SteadyStateConfig

        policy = RuntimeControlPolicy(
            observation_store_root=str(tmp_path / "store"),
            verification=AdaptiveVerificationConfig(
                steady=SteadyStateConfig(window=4, stable_windows=3, rel_spread_tol=0.10),
                min_timed_steps=5,
                min_timed_ms=0.0,
                max_steps=50,
            ),
        )
        session = RuntimeVerificationSession(str(tmp_path / "rv.json"), policy=policy)
        session.complete_setup(
            storage_provenance=_STORAGE,
            training_workload=ResolvedPhaseWorkload(
                phase="training", unit="optimizer_step", unit_count=100
            ),
        )
        session.set_calibration_context(self._CONTEXT)
        self._store_with_observation(tmp_path, session)

        verifier = session.start_phase_verification(
            "training",
            unit="optimizer_step",
            prior_expected_unit_ms=session.lookup_phase_prior("training"),
        )
        for t in [40.0] * 30:  # matches the 40 ms prior
            verifier.feed(t)
            if verifier.is_terminal:
                break
        assert verifier.prior_agreement == "verified_match"
        prediction = session.complete_phase_verification(
            "training", verifier, source="real_training_verification"
        )
        assert prediction is not None
        assert prediction.prior_agreement_ratio == pytest.approx(1.0, rel=0.05)


class TestAtomicWrite:
    def test_no_tmp_file_left_behind(self, tmp_path):
        path = tmp_path / "rv.json"
        session = RuntimeVerificationSession(str(path))
        session.complete_setup(storage_provenance=_STORAGE)
        session.decide_admission()
        assert path.exists()
        assert not (tmp_path / "rv.json.tmp").exists()

    def test_write_failure_never_raises(self, tmp_path):
        # The session must not kill a healthy run when the sidecar
        # cannot be persisted (class-docstring contract).
        session = RuntimeVerificationSession(str(tmp_path / "missing_dir" / "rv.json"))
        session.complete_setup(storage_provenance=_STORAGE)
        adm = session.decide_admission()
        assert adm.decision == "admitted"
