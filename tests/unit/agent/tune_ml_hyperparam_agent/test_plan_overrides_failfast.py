"""
FU-10 — plan_overrides fail-fast hardening.

The operator override lock is a contract:
  * unknown keys fail at SCHEMA validation (input construction — the
    earliest practical point), with keys normalized to alias form so the
    tuner's by_alias merge replaces fields instead of adding stray keys;
  * the merged effective plan is revalidated every round, and an invalid
    result raises PlanOverridesError that terminates the run — it is never
    recorded as a retryable attempt failure, and the run never continues
    on the unclamped LLM plan.
See docs/design/enable_partial_file_list.md (Follow-up tracker, FU-10).
"""

from __future__ import annotations

import tempfile
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import (
    HyperparamTuningInput,
    PlanOverridesError,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from tests.helpers.scoring_stubs import stub_scoring
from tests.unit.agent.tune_ml_hyperparam_agent.test_tuning_agent import (
    FAKE_PLAN_WITH_TRIAL,
    FAKE_REFLECT_RESPONSE,
    _mock_run_skill,
    _synth_reference,
)


def _input(tmp_path, **kwargs) -> HyperparamTuningInput:
    return HyperparamTuningInput(
        model_type="punet",
        file_index=6,
        max_rounds=1,
        is_trial=True,
        expert_advice="",
        llm_provider="gemini",
        llm_model_id="test-model",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="fu10_test"),
        ),
        progress_bar=False,
        **kwargs,
    )


class TestSchemaKeyValidation:
    def test_unknown_key_fails_at_construction(self, tmp_path):
        with pytest.raises(ValidationError, match="unknown ExperimentPlan field"):
            _input(tmp_path, plan_overrides={"not_a_plan_field": 1})

    def test_valid_python_names_pass(self, tmp_path):
        inp = _input(tmp_path, plan_overrides={"trial_portion": 0.05, "is_trial": True})
        assert inp.plan_overrides == {"trial_portion": 0.05, "is_trial": True}

    def test_alias_normalization_both_directions(self, tmp_path):
        # Python name normalizes to the alias the by_alias dump emits...
        inp = _input(tmp_path, plan_overrides={"model_cfg": {"depth": 2}})
        assert inp.plan_overrides == {"model_config": {"depth": 2}}
        # ...and the alias itself is accepted verbatim.
        inp = _input(tmp_path, plan_overrides={"model_config": {"depth": 2}})
        assert inp.plan_overrides == {"model_config": {"depth": 2}}

    def test_name_plus_alias_collision_rejected(self, tmp_path):
        with pytest.raises(ValidationError, match="twice"):
            _input(
                tmp_path,
                plan_overrides={"model_cfg": {"depth": 2}, "model_config": {"depth": 3}},
            )

    def test_empty_overrides_unchanged(self, tmp_path):
        assert _input(tmp_path).plan_overrides == {}


class TestMergeFailFast:
    """An invalid effective plan terminates the run — never a silent
    fallback, never a retryable attempt failure."""

    def _run_agent(self, tmp_path, plan_overrides):
        with (
            patch("nodes.ml_hyperparameter_tune_agent.LLMBridge") as MockBridge,
            patch("nodes.ml_hyperparameter_tune_agent.TidmadSandbox") as MockSandbox,
            patch(
                "nodes.ml_hyperparameter_tune_agent.runtime._run_skill", side_effect=_mock_run_skill
            ),
            patch("nodes.ml_hyperparameter_tune_agent.load_anchor_map") as mock_anchor,
            patch(
                "nodes.ml_hyperparameter_tune_agent.load_reference_scores",
                return_value=_synth_reference(),
            ),
            patch("os.path.exists", return_value=True),
            tempfile.TemporaryDirectory() as configs_dir,
        ):
            mock_brain = MockBridge.return_value
            mock_brain.plan.return_value = FAKE_PLAN_WITH_TRIAL
            mock_brain.reflect.return_value = FAKE_REFLECT_RESPONSE

            mock_anchor.return_value = {"anchors": {}, "s_max": 1.0}

            saved_records: list[dict] = []
            mock_sandbox = MockSandbox.return_value
            mock_sandbox.get_summary.side_effect = lambda: list(saved_records)
            mock_sandbox.save_record.side_effect = saved_records.append
            mock_sandbox.dirs = {"configs": configs_dir, "data": configs_dir}
            stub_scoring(mock_sandbox, [1.0] * 20, 1.5)

            agent = HyperparamTuningAgent()
            inp = _input(tmp_path, plan_overrides=plan_overrides)
            with pytest.raises(PlanOverridesError, match="never silently released"):
                agent.run(inp)
            return mock_brain, saved_records

    def test_invalid_value_terminates_without_retry(self, tmp_path):
        # trial_portion=5.0 fails ExperimentPlan validation after the merge.
        mock_brain, saved_records = self._run_agent(tmp_path, {"trial_portion": 5.0})
        # Exactly ONE plan call: the error propagated instead of burning
        # the attempt-retry budget on a deterministic config error.
        assert mock_brain.plan.call_count == 1
        # And it was never recorded as a retryable attempt failure.
        assert not any(r.get("record_type") == "attempt_failure" for r in saved_records)
