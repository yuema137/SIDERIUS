"""
RT2-G — tuner-side formal admission wiring.

Harness mirrors ``test_silent_train_crash_routing.py`` (hermetic: LLM,
sandbox, skills, references, hardware all patched). Pins:

1. the operator runtime policy reaches the training skill — formal
   rounds carry the operator budget (seconds), record-only otherwise —
   plus the observation-store root;
2. a clean in-subprocess REJECTION (``rejected_time_risk``) is saved as
   a ``skipped_time_risk`` record (existing vocabulary §2.11) marked
   ``verification_stage="in_subprocess"``, carries the runtime
   observation, CONSUMES an attempt (operator decision 2026-07-23),
   and appends the observation to the run's store;
3. a successful attempt's final record carries the (inference-side,
   §7.3 additive) ``runtime_verification`` block and appends it to the
   store.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from core.hardware_context import HardwareContext
from core.runtime_control.observation_store import ObservationStore
from core.runtime_control.session import RuntimeControlPolicy, RuntimeVerificationSession
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from nodes.scoring_reference import ReferenceScores
from tests.helpers.scoring_stubs import stub_scoring


def _stub_hardware_context() -> HardwareContext:
    return HardwareContext(
        device_name="stub-cuda-device",
        total_memory_bytes=32 * 1024**3,
        compute_capability=(9, 0),
        multiprocessor_count=128,
        cuda_runtime_version="12.4",
        torch_version="2.5.1",
        hostname="test-host",
        device_available=True,
        discovered_at=datetime(2026, 4, 26, tzinfo=UTC),
    )


def _synth_reference_stub() -> ReferenceScores:
    return ReferenceScores(
        raw_per_file_log=[-2.7] * 20,
        gt_per_file_log=[7.0] * 20,
        raw_per_file_linear_sum=[2.0] * 20,
        raw_per_file_n_segments=[200] * 20,
        gt_per_file_linear_sum=[2000.0] * 20,
        gt_per_file_n_segments=[200] * 20,
        raw_scalar_full=-2.7,
        gt_scalar_full=7.0,
        s_max=295_715_680.14,
    )


FAKE_PLAN = {
    "model_type": "punet",
    "hypothesis": "h",
    "reasoning": "r",
    "model_config": {"depth": 4, "segmentation_size": 40000, "batch_size": 1},
    "train_config": {"epochs": 5, "lr": 1e-4},
    "loss_config": {"loss_type": "ce"},
}
FAKE_REFLECT = {"conclusion": "c", "key_factor": "k", "discovery": "d", "memory_update": "m"}
FAKE_CONFIG_MANUAL = {
    "status": "success",
    "data": {"punet": {"fields": ["depth", "segmentation_size"]}},
}
FAKE_VRAM_OK = {
    "status": "success",
    "feasible": True,
    "estimated_gb": 2.5,
    "limit_gb": 6.0,
    "vram_budget_gb": 8.0,
    "verdict": "FITS",
    "suggestion": "",
}
FAKE_TIME_OK = {
    "status": "success",
    "feasible": True,
    "estimated_minutes": 10.0,
    "limit_minutes": 120.0,
    "verdict": "FITS",
    "suggestion": "",
    "breakdown": {},
}


def _rejected_observation_block(tmp_dir: str) -> dict:
    """A REAL rejected observation (schema-true) via the session."""
    import os

    session = RuntimeVerificationSession(
        os.path.join(tmp_dir, "rv_reject.json"),
        policy=RuntimeControlPolicy(operator_budget_seconds=1e-9),
        attempt_id="exp_reject",
    )
    session.complete_setup(storage_provenance={"expected_raw_bytes": 10})
    session.decide_admission()
    return session.observation.model_dump(mode="json")


def _completed_observation_block(tmp_dir: str) -> dict:
    import os

    session = RuntimeVerificationSession(os.path.join(tmp_dir, "rv_ok.json"), attempt_id="exp_ok")
    session.complete_setup(storage_provenance={"expected_raw_bytes": 10})
    session.decide_admission()
    session.record_phase_actual("training", 5.0)
    session.finalize("completed")
    return session.observation.model_dump(mode="json")


def _make_input(tmp_path) -> HyperparamTuningInput:
    return HyperparamTuningInput(
        model_type="punet",
        file_index=6,
        max_rounds=1,  # single round → forced formal
        attempts_per_round=1,
        attempts_per_formal_round=1,
        max_fail_rounds=1,
        formal_time_budget_minutes=120,
        expert_advice="",
        llm_provider="gemini",
        llm_model_id="test-model",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="rt2g_test"),
        ),
        progress_bar=False,
    )


@pytest.fixture
def harness():
    """Factory wiring the hermetic tuner harness around scripted skill
    responses. Returns ``(agent, saved_records, seen_params, workspace,
    cleanup)``."""

    def make(train_response: dict, inference_response: dict, scoring_ok: bool = True):
        seen_params: dict[str, dict] = {}

        def side_effect(skill_folder, sandbox, **params):
            seen_params[skill_folder] = params
            if skill_folder == "check_config_format_skill":
                return FAKE_CONFIG_MANUAL
            if skill_folder == "evaluate_vram_skill":
                return FAKE_VRAM_OK
            if skill_folder == "evaluate_time_skill":
                return FAKE_TIME_OK
            if skill_folder == "training_skill":
                return train_response
            if skill_folder == "inference_skill":
                return inference_response
            return {"status": "error", "message": f"unexpected skill {skill_folder}"}

        cms = (
            patch("nodes.ml_hyperparameter_tune_agent.LLMBridge"),
            patch("nodes.ml_hyperparameter_tune_agent.TidmadSandbox"),
            patch("nodes.ml_hyperparameter_tune_agent.runtime._run_skill", side_effect=side_effect),
            patch(
                "nodes.ml_hyperparameter_tune_agent.load_reference_scores",
                return_value=_synth_reference_stub(),
            ),
            patch(
                "nodes.ml_hyperparameter_tune_agent.get_or_create",
                return_value=_stub_hardware_context(),
            ),
            tempfile.TemporaryDirectory(),
        )
        bridge_cm, sandbox_cm, skill_cm, ref_cm, hw_cm, ws_cm = cms
        MockBridge = bridge_cm.__enter__()
        MockSandbox = sandbox_cm.__enter__()
        skill_cm.__enter__()
        ref_cm.__enter__()
        hw_cm.__enter__()
        workspace = ws_cm.__enter__()

        mock_brain = MockBridge.return_value
        mock_brain.plan.return_value = FAKE_PLAN
        mock_brain.reflect.return_value = FAKE_REFLECT

        saved: list[dict] = []
        mock_sandbox = MockSandbox.return_value
        mock_sandbox.get_summary.side_effect = lambda: list(saved)
        mock_sandbox.save_record.side_effect = lambda r: saved.append(r)
        mock_sandbox.dirs = {"configs": workspace}
        mock_sandbox.base_dir = workspace  # store root anchor
        if scoring_ok:
            stub_scoring(mock_sandbox, [-2.5] * 20, -2.5)

        def cleanup():
            ws_cm.__exit__(None, None, None)
            hw_cm.__exit__(None, None, None)
            ref_cm.__exit__(None, None, None)
            skill_cm.__exit__(None, None, None)
            sandbox_cm.__exit__(None, None, None)
            bridge_cm.__exit__(None, None, None)

        return HyperparamTuningAgent(), saved, seen_params, workspace, cleanup

    yield make


class TestPolicyPropagation:
    def test_formal_round_policy_carries_budget_and_store_root(self, harness, tmp_path):
        with tempfile.TemporaryDirectory() as obs_dir:
            rejected = {
                "status": "rejected_time_risk",
                "message": "rejected",
                "runtime_verification": _rejected_observation_block(obs_dir),
            }
        agent, _saved, seen_params, _workspace, cleanup = harness(rejected, {"status": "error"})
        try:
            agent.run(_make_input(tmp_path))
        finally:
            cleanup()

        policy = seen_params["training_skill"]["runtime_policy"]
        # 1-round runs force the round formal → budget enforced (seconds).
        assert policy["operator_budget_seconds"] == pytest.approx(120 * 60.0)
        assert policy["observation_store_root"].endswith("runtime_observations")
        # The policy validates against the executor-boundary schema.
        RuntimeControlPolicy(**policy)


class TestInSubprocessRejectionRouting:
    def test_rejection_consumes_attempt_with_structured_record(self, harness, tmp_path):
        with tempfile.TemporaryDirectory() as obs_dir:
            block = _rejected_observation_block(obs_dir)
        rejected = {
            "status": "rejected_time_risk",
            "message": "rejected",
            "runtime_verification": block,
        }
        agent, saved, seen_params, _workspace, cleanup = harness(rejected, {"status": "error"})
        try:
            agent.run(_make_input(tmp_path))
        finally:
            cleanup()

        skips = [r for r in saved if r.get("status") == "skipped_time_risk"]
        assert len(skips) == 1, f"statuses: {[r.get('status') for r in saved]}"
        rec = skips[0]
        assert rec["memory"]["verification_stage"] == "in_subprocess"
        assert rec["runtime_verification"]["admission"]["decision"] == "rejected"
        assert "consumed an attempt" in rec["memory"]["memory_update"]
        # No success record — with attempts=1 and max_fail_rounds=1 the
        # consumed attempt ends the run (the accounting contract).
        assert not any(r.get("status") == "success" for r in saved)
        # Inference never ran after the rejection.
        assert "inference_skill" not in seen_params

    def test_rejection_appends_observation_to_store(self, harness, tmp_path):
        with tempfile.TemporaryDirectory() as obs_dir:
            block = _rejected_observation_block(obs_dir)
        rejected = {
            "status": "rejected_time_risk",
            "message": "rejected",
            "runtime_verification": block,
        }
        agent, _saved, _seen_params, workspace, cleanup = harness(rejected, {"status": "error"})
        try:
            agent.run(_make_input(tmp_path))
            import os

            store = ObservationStore(os.path.join(workspace, "runtime_observations"))
            observations = store.read_all()
        finally:
            cleanup()
        assert len(observations) == 1
        assert observations[0].admission is not None
        assert observations[0].admission.decision == "rejected"


class TestSuccessPathAttachment:
    def test_final_record_carries_and_stores_observation(self, harness, tmp_path):
        with tempfile.TemporaryDirectory() as obs_dir:
            block = _completed_observation_block(obs_dir)
        train_ok = {
            "status": "success",
            "results": {"final_loss": 0.5, "model_params": 100000},
            "runtime_verification": None,  # training-side (legacy shape ok)
        }
        inference_ok = {
            "status": "success",
            "message": "ok",
            "per_file_timings_ms": [],
            "process_startup_ms": 10.0,
            "subprocess_wall_ms": 10.0,
            "runtime_verification": block,  # resumed observation (RT2-D)
        }
        agent, saved, _seen_params, workspace, cleanup = harness(train_ok, inference_ok)
        try:
            agent.run(_make_input(tmp_path))
            import os

            store = ObservationStore(os.path.join(workspace, "runtime_observations"))
            observations = store.read_all()
        finally:
            cleanup()

        successes = [r for r in saved if r.get("status") in ("success", "failed_mode_collapse")]
        assert successes, f"statuses: {[r.get('status') for r in saved]}"
        rec = successes[0]
        # Inference-side block preferred (§7.3 additive field).
        assert rec["runtime_verification"]["final_status"] == "completed"
        assert len(observations) == 1
        assert observations[0].final_status == "completed"

    def test_legacy_results_without_block_stay_compatible(self, harness, tmp_path):
        train_ok = {"status": "success", "results": {"final_loss": 0.5, "model_params": 1}}
        inference_ok = {
            "status": "success",
            "message": "ok",
            "per_file_timings_ms": [],
            "process_startup_ms": 10.0,
            "subprocess_wall_ms": 10.0,
        }
        agent, saved, _seen_params, _workspace, cleanup = harness(train_ok, inference_ok)
        try:
            agent.run(_make_input(tmp_path))
        finally:
            cleanup()
        successes = [r for r in saved if r.get("status") in ("success", "failed_mode_collapse")]
        assert successes
        assert successes[0]["runtime_verification"] is None  # explicit absence


class TestWatchdogTimeoutRouting:
    """RT4: a watchdog kill surfaces as attempt_failure /
    wall_clock_timeout with the §4 provenance triplet, counts toward
    the attempt budget, and appends the partial observation."""

    def test_timeout_records_attempt_failure_with_provenance(self, harness, tmp_path):
        with tempfile.TemporaryDirectory() as obs_dir:
            import os

            session = RuntimeVerificationSession(os.path.join(obs_dir, "rv.json"))
            session.complete_setup(storage_provenance={"expected_raw_bytes": 1})
            partial_block = session.observation.model_dump(mode="json")
        timeout = {
            "status": "wall_clock_timeout",
            "message": "watchdog killed training after 12.0s",
            "watchdog": {
                "elapsed_s": 12.0,
                "deadline_s": 10.0,
                "estimate_source": "verified_components",
                "escalated_to_kill": False,
                "survivors_detected": False,
            },
            "runtime_verification": partial_block,
        }
        agent, saved, _seen_params, workspace, cleanup = harness(timeout, {"status": "error"})
        try:
            agent.run(_make_input(tmp_path))
            import os

            observations = ObservationStore(
                os.path.join(workspace, "runtime_observations")
            ).read_all()
        finally:
            cleanup()

        failures = [r for r in saved if r.get("record_type") == "attempt_failure"]
        assert len(failures) == 1, f"statuses: {[r.get('status') for r in saved]}"
        rec = failures[0]
        assert rec["failure_type"] == "wall_clock_timeout"  # §4 decision
        assert rec["failure_stage"] == "training"
        assert rec["counts_toward_attempt_budget"] is True
        assert rec["watchdog"]["elapsed_s"] == 12.0
        assert rec["watchdog"]["deadline_s"] == 10.0
        assert rec["memory"]["watchdog_estimate_source"] == "verified_components"
        # Partial observation of the killed attempt is store evidence
        # (§6c keeps it OUT of calibration; the ledger keeps it visible).
        assert len(observations) == 1


pytestmark = pytest.mark.usefixtures("synthetic_run_authorities")
