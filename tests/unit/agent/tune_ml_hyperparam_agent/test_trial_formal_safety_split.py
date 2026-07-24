"""
Wave-1A trial/formal safety-factor split (operator decision, 2026-07-24).

The Wave-1A diagnostic showed trial attempts running a systematic
1.54-1.61x past stable verification under 2-way concurrency, so the
production posture splits the §2.10 factor:

    trial  attempts → 2.0   (--runtime_trial_safety_factor)
    formal attempts → 1.5   (legacy --runtime_safety_factor)

Precedence per phase: phase-specific factor when provided → legacy
``runtime_safety_factor`` → its schema default. Enforcement (admission
+ watchdog deadline) reads only the resolved ``safety_factor``; both
configured phase values are recorded in runtime-policy provenance.

No real LLM, no training — parser + schema + policy assembly + the
watchdog deadline provider against a synthetic sidecar.
"""

from __future__ import annotations

import json

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from core.runtime_control.session import RuntimeControlPolicy
from core.sandbox_executor import _watchdog_deadline_provider
from nodes.ml_hyperparameter_tune_agent import _build_runtime_policy
from sdsc_submission_scripts.run_one_iteration import build_parser

# The V18r relaunch posture flags, as emitted by launch_v18_wave1.sh.
V18R_POSTURE_ARGV = [
    "--workspace",
    "/tmp/v18r_ws",
    "--run_name",
    "v18r_loss_04_09",
    "--runtime_watchdog",
    "--runtime_safety_factor",
    "1.5",
    "--runtime_trial_safety_factor",
    "2.0",
    "--runtime_watchdog_floor_seconds",
    "120",
]


def _input_from_args(a) -> HyperparamTuningInput:
    """Mirror the runner's field mapping for the runtime-policy fields."""
    return HyperparamTuningInput.model_construct(
        runtime_watchdog_enabled=a.runtime_watchdog,
        runtime_safety_factor=a.runtime_safety_factor,
        runtime_trial_safety_factor=a.runtime_trial_safety_factor,
        runtime_formal_safety_factor=a.runtime_formal_safety_factor,
        runtime_watchdog_floor_seconds=a.runtime_watchdog_floor_seconds,
    )


@pytest.fixture
def posture_input():
    return _input_from_args(build_parser().parse_args(V18R_POSTURE_ARGV))


class TestPhaseResolution:
    def test_trial_uses_trial_factor(self, posture_input):
        policy = RuntimeControlPolicy(
            **_build_runtime_policy(
                posture_input, chosen_time_budget=20.0, is_trial=True, base_dir="/tmp/v18r_ws"
            )
        )
        assert policy.safety_factor == 2.0
        assert policy.operator_budget_seconds is None  # trials stay record-only

    def test_formal_falls_back_to_legacy_factor(self, posture_input):
        policy = RuntimeControlPolicy(
            **_build_runtime_policy(
                posture_input, chosen_time_budget=120.0, is_trial=False, base_dir="/tmp/v18r_ws"
            )
        )
        assert policy.safety_factor == 1.5  # no formal-specific flag → legacy
        assert policy.operator_budget_seconds == pytest.approx(7200.0)

    def test_formal_specific_factor_wins_when_provided(self):
        agent_input = HyperparamTuningInput.model_construct(
            runtime_safety_factor=1.5,
            runtime_trial_safety_factor=2.0,
            runtime_formal_safety_factor=1.25,
            runtime_watchdog_enabled=False,
            runtime_watchdog_floor_seconds=60.0,
        )
        policy_dict = _build_runtime_policy(
            agent_input, chosen_time_budget=120.0, is_trial=False, base_dir="/tmp/v18r_ws"
        )
        assert policy_dict["safety_factor"] == 1.25

    def test_both_phase_values_recorded_in_provenance(self, posture_input):
        for is_trial in (True, False):
            policy = RuntimeControlPolicy(
                **_build_runtime_policy(
                    posture_input,
                    chosen_time_budget=None,
                    is_trial=is_trial,
                    base_dir="/tmp/v18r_ws",
                )
            )
            assert policy.trial_safety_factor == 2.0
            assert policy.formal_safety_factor is None


class TestLegacyCompatibility:
    def test_legacy_caller_without_phase_flags_keeps_prior_behavior(self):
        a = build_parser().parse_args(
            ["--workspace", "/tmp/w", "--run_name", "r", "--runtime_safety_factor", "1.5"]
        )
        assert a.runtime_trial_safety_factor is None
        assert a.runtime_formal_safety_factor is None
        agent_input = _input_from_args(a)
        for is_trial in (True, False):
            policy_dict = _build_runtime_policy(
                agent_input, chosen_time_budget=None, is_trial=is_trial, base_dir="/tmp/w"
            )
            assert policy_dict["safety_factor"] == 1.5

    def test_schema_defaults(self):
        fields = HyperparamTuningInput.model_fields
        assert fields["runtime_safety_factor"].default == 1.0
        assert fields["runtime_trial_safety_factor"].default is None
        assert fields["runtime_formal_safety_factor"].default is None
        # Fully-default input resolves to the legacy schema default.
        agent_input = HyperparamTuningInput.model_construct(
            runtime_watchdog_enabled=False,
            runtime_safety_factor=1.0,
            runtime_trial_safety_factor=None,
            runtime_formal_safety_factor=None,
            runtime_watchdog_floor_seconds=60.0,
        )
        for is_trial in (True, False):
            assert (
                _build_runtime_policy(
                    agent_input, chosen_time_budget=None, is_trial=is_trial, base_dir="/tmp/w"
                )["safety_factor"]
                == 1.0
            )


class TestWatchdogDeadlineUsesPhaseFactor:
    def _sidecar(self, tmp_path, predicted_seconds: float) -> str:
        # The executor validates the sidecar as a full RuntimeObservation
        # (fail-open to "no evidence" on anything less), so build a
        # minimal VALID one.
        path = tmp_path / "runtime_verification_test.json"
        path.write_text(
            json.dumps(
                {
                    "timestamp": "2026-07-24T05:00:00+0000",
                    "components": {
                        "training": {
                            "prediction": {
                                "predicted_seconds": predicted_seconds,
                                "source": "real_training_verification",
                                "formal_execution_eligible": True,
                                "steady_state": True,
                                "verification": "passed",
                                "confidence": "high",
                                "safety_factor": 1.0,
                                "ms_per_unit": 10.0,
                                "n_steady_units": 20,
                                "unit_count": 10000,
                            }
                        }
                    },
                }
            )
        )
        return str(path)

    def test_trial_deadline_scales_by_trial_factor(self, tmp_path, posture_input):
        sidecar = self._sidecar(tmp_path, predicted_seconds=100.0)
        trial_policy = RuntimeControlPolicy(
            **_build_runtime_policy(
                posture_input, chosen_time_budget=20.0, is_trial=True, base_dir=str(tmp_path)
            )
        )
        deadline, source = _watchdog_deadline_provider(trial_policy, sidecar)()
        assert source == "verified_components"
        assert deadline == pytest.approx(200.0)  # 100 s × trial 2.0

    def test_formal_deadline_scales_by_formal_factor(self, tmp_path, posture_input):
        sidecar = self._sidecar(tmp_path, predicted_seconds=100.0)
        formal_policy = RuntimeControlPolicy(
            **_build_runtime_policy(
                posture_input, chosen_time_budget=120.0, is_trial=False, base_dir=str(tmp_path)
            )
        )
        deadline, source = _watchdog_deadline_provider(formal_policy, sidecar)()
        assert source == "verified_components"
        assert deadline == pytest.approx(150.0)  # 100 s × legacy/formal 1.5
