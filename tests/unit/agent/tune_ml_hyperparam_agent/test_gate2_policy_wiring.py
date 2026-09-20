"""
Gate 2 policy-wiring checkpoint (operator plan, 2026-07-24).

Proves that the EXACT approved Scenario A command resolves — through
the chain runner's parser, the input schema, and the tuner's policy
builder — to the intended production-posture RuntimeControlPolicy:

    safety_factor = 1.5
    watchdog.enabled = True
    watchdog.floor_seconds = 120
    watchdog.grace_seconds = 10   (schema default, provenance-recorded)
    watchdog.poll_seconds = 1     (schema default, provenance-recorded)
    max_steps_per_attempt = 150000
    min_formal_batch_size = 4
    allow_extreme_steps = False
    historical_phase_share_limit = 0.10

No real LLM, no training — parser + schema + policy assembly only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from core.runtime_control.session import RuntimeControlPolicy
from nodes.ml_hyperparameter_tune_agent import _build_runtime_policy
from workflows.run_one_iteration import build_parser

# Preserve the historical numeric fixture with today's explicit task and
# admission-source declarations; this is not a scientific campaign launcher.
SCENARIO_A_ARGV = [
    "--task_composition",
    str(Path(__file__).resolve().parents[4] / "configs/task_composition/quickstart.yaml"),
    "--data_dir",
    "/parser-only/synthetic-data",
    "--trial_time_admission_source",
    "forecast",
    "--workspace",
    "/tmp/gate2_rc",
    "--run_name",
    "gate2_rt",
    "--start_iteration",
    "1",
    "--max_rounds",
    "2",
    "--max_proposal_attempts",
    "3",
    "--max_epochs",
    "1",
    "--llm_config",
    "llm_configs/openai_tiered_v1.json",
    "--data_scope",
    "4-9",
    "--is_trial",
    "--trial_portion",
    "0.02",
    "--train_portion",
    "1.0",
    "--eval_portion",
    "0.01",
    "--trial_time_budget_minutes",
    "5",
    "--formal_portion",
    "0.02",
    "--formal_train_portion",
    "1.0",
    "--formal_eval_portion",
    "0.01",
    "--formal_time_budget_minutes",
    "30",
    "--trial_vram_budget_gb",
    "24",
    "--formal_vram_budget_gb",
    "24",
    "--max_steps_per_attempt",
    "150000",
    "--min_formal_batch_size",
    "4",
    "--runtime_watchdog",
    "--runtime_safety_factor",
    "1.5",
    "--runtime_watchdog_floor_seconds",
    "120",
]


@pytest.fixture
def scenario_a_args():
    return build_parser().parse_args(SCENARIO_A_ARGV)


class TestScenarioACommandResolution:
    def test_parser_resolves_approved_values(self, scenario_a_args):
        a = scenario_a_args
        assert a.runtime_safety_factor == 1.5
        assert a.runtime_watchdog_floor_seconds == 120.0
        assert a.runtime_watchdog is True
        # Historical explicit guardrails, no longer production defaults.
        assert a.max_steps_per_attempt == 150_000
        assert a.min_formal_batch_size == 4
        assert a.allow_extreme_steps is False
        # Gate-specific budgets and portions.
        assert a.formal_time_budget_minutes == 30.0
        assert a.trial_time_budget_minutes == 5.0
        assert a.formal_portion == 0.02
        assert a.formal_train_portion == 1.0
        assert a.formal_eval_portion == 0.01
        assert a.trial_vram_budget_gb == 24.0
        assert a.formal_vram_budget_gb == 24.0

    def test_input_and_policy_carry_production_posture(self, scenario_a_args):
        a = scenario_a_args
        # Mirror the runner's field mapping (run_one_iteration → workflow
        # → protocol → HyperparamTuningInput).
        agent_input = HyperparamTuningInput.model_construct(
            max_steps_per_attempt=a.max_steps_per_attempt or None,
            min_formal_batch_size=a.min_formal_batch_size or None,
            allow_extreme_steps=a.allow_extreme_steps,
            runtime_watchdog_enabled=a.runtime_watchdog,
            runtime_safety_factor=a.runtime_safety_factor,
            runtime_watchdog_floor_seconds=a.runtime_watchdog_floor_seconds,
        )
        # FORMAL round with the Gate-specific 30-min budget.
        policy_dict = _build_runtime_policy(
            agent_input,
            chosen_time_budget=a.formal_time_budget_minutes,
            is_trial=False,
            base_dir="/tmp/gate2_rc",
        )
        policy = RuntimeControlPolicy(**policy_dict)
        assert policy.operator_budget_seconds == pytest.approx(1800.0)
        assert policy.safety_factor == 1.5
        assert policy.watchdog.enabled is True
        assert policy.watchdog.floor_seconds == 120.0
        # Schema defaults, provenance-recorded (no CLI flags by design).
        assert policy.watchdog.grace_seconds == 10.0
        assert policy.watchdog.poll_seconds == 1.0
        assert policy.historical_phase_share_limit == pytest.approx(0.10)
        assert policy.observation_store_root == "/tmp/gate2_rc/runtime_observations"

    def test_trial_round_is_record_only_under_same_command(self, scenario_a_args):
        a = scenario_a_args
        agent_input = HyperparamTuningInput.model_construct(
            runtime_watchdog_enabled=a.runtime_watchdog,
            runtime_safety_factor=a.runtime_safety_factor,
            runtime_watchdog_floor_seconds=a.runtime_watchdog_floor_seconds,
        )
        policy_dict = _build_runtime_policy(
            agent_input,
            chosen_time_budget=a.trial_time_budget_minutes,
            admission_source=a.trial_time_admission_source,
            is_trial=True,
            base_dir="/tmp/gate2_rc",
        )
        policy = RuntimeControlPolicy(**policy_dict)
        assert policy.operator_budget_seconds is None  # record-only trial
        assert policy.safety_factor == 1.5  # posture still recorded

    def test_schema_defaults_unchanged_for_programmatic_callers(self):
        fields = HyperparamTuningInput.model_fields
        assert fields["runtime_safety_factor"].default == 1.0
        assert fields["runtime_watchdog_floor_seconds"].default == 60.0
