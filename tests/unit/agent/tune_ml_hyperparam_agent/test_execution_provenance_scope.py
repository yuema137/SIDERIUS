"""Resolved workload provenance must match the config persisted by the real tuner.

Drive run -> prepare_attempt -> reflection with only LLM/heavy skills stubbed.
The saved TrialConfig is the independent execution-side witness: a plan-only
tracker can pass its own unit tests while disagreeing with this configuration.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.prompts import get_reflector_user_prompt
from agent.schemas.hyperparam_tuning import HyperparamTuningInput, TrialConfig
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from tests.helpers.scoring_stubs import stub_scoring
from tests.unit.agent.tune_ml_hyperparam_agent.test_tuning_agent import (
    FAKE_PLAN_WITH_TRIAL,
    FAKE_REFLECT_RESPONSE,
    _mock_run_skill,
    _synth_reference,
)


def _run_real_route(tmp_path, *, authored=None, **settings):
    """Capture the real reflector boundary and the already persisted config."""
    plan = {
        **deepcopy(FAKE_PLAN_WITH_TRIAL),
        "trial_portion": 0.2,
        "train_portion": 0.6,
        "eval_portion": 0.3,
        **(authored or {}),
    }
    original = deepcopy(plan)
    configs = tmp_path / "configs"
    configs.mkdir()
    captured = []
    records = []

    def reflect(exp_id, hypothesis, results, context, **kwargs):
        persisted = configs / f"trial_config_{exp_id}.json"
        config = TrialConfig.model_validate_json(persisted.read_text())
        provenance = kwargs["execution_provenance"]
        prompt = get_reflector_user_prompt(
            exp_id,
            hypothesis,
            results,
            context,
            metric_spec=kwargs.get("metric_spec"),
            training_diagnosis=kwargs.get("training_diagnosis"),
            execution_provenance=provenance,
        )
        captured.append((config, provenance, deepcopy(context), prompt))
        return deepcopy(FAKE_REFLECT_RESPONSE)

    with (
        patch("nodes.ml_hyperparameter_tune_agent.LLMBridge") as bridge,
        patch("nodes.ml_hyperparameter_tune_agent.TidmadSandbox") as sandbox,
        patch("nodes.ml_hyperparameter_tune_agent.runtime._run_skill", side_effect=_mock_run_skill),
        patch("nodes.ml_hyperparameter_tune_agent.load_anchor_map") as anchor,
        patch(
            "nodes.ml_hyperparameter_tune_agent.load_reference_scores",
            return_value=_synth_reference(),
        ),
        patch("os.path.exists", return_value=True),
    ):
        brain = bridge.return_value
        brain.plan.side_effect = lambda *args, **kwargs: deepcopy(plan)
        brain.reflect.side_effect = reflect
        anchor.return_value = {"anchors": {}, "s_max": 1.0}
        box = sandbox.return_value
        box.get_summary.side_effect = lambda: list(records)
        box.save_record.side_effect = records.append
        box.dirs = {"configs": str(configs), "data": str(configs)}
        stub_scoring(box, [1.0] * 20, 1.5)
        options = {
            "planner_strategy": "native-timing-v1",
            "model_type": "punet",
            "file_index": 6,
            "max_rounds": 2,
            "is_trial": True,
            "formal_round_strategy": "independent",
            "expert_advice": "",
            "llm_provider": "gemini",
            "llm_model_id": "test-model",
            "storage": StorageConfig(
                backend="local",
                local=LocalStorageConfig(workspace=str(tmp_path), run_name="scope_witness"),
            ),
            "progress_bar": False,
            **settings,
        }
        inp = HyperparamTuningInput(**options)
        HyperparamTuningAgent().run(inp)
    assert plan == original
    assert captured, "the real run must reach reflection, not fail before the witness"
    assert len(list(Path(configs).glob("trial_config_*.json"))) == len(captured)
    return captured


def _only_mode(captured, mode):
    selected = [row for row in captured if row[0].mode == mode]
    assert len(selected) == 1, f"expected one genuine {mode} attempt"
    return selected[0]


@pytest.mark.parametrize("authored_portion", [0.5, 0.2])
def test_formal_provenance_follows_final_config_instead_of_intermediate_trial_lock(
    tmp_path, authored_portion
):
    config, provenance, context, prompt = _only_mode(
        _run_real_route(
            tmp_path,
            authored={"trial_portion": authored_portion},
            plan_overrides={"trial_portion": 0.25},
            formal_portion=0.5,
        ),
        "formal",
    )
    assert config.trial_portion == 0.5
    assert context["trial_portion"] == config.trial_portion
    events = {event.field_path: event for event in provenance.events}
    if authored_portion == config.trial_portion:
        assert "trial_portion" not in events, "restoring the authored value is not a disagreement"
    else:
        assert events["trial_portion"].proposed == repr(authored_portion)
        assert events["trial_portion"].executed == repr(config.trial_portion)
        assert events["trial_portion"].authority == "resolved_round_workload"
    portion_lines = [line for line in prompt.splitlines() if "trial_portion: proposed" in line]
    assert all("-> EXECUTED 0.25" not in line for line in portion_lines)
    checkpoint = {event.field_path: event for event in provenance.plan_resolution_events}
    assert checkpoint["trial_portion"].proposed == repr(authored_portion)
    assert checkpoint["trial_portion"].executed == "0.25"
    assert checkpoint["trial_portion"].authority == "operator_plan_overrides"


def test_agent_owned_formal_training_and_operator_owned_evaluation_are_distinct(tmp_path):
    config, provenance, context, _ = _only_mode(
        _run_real_route(
            tmp_path,
            authored={
                "trial_portion": 0.37,
                "train_portion": 0.61,
                "eval_portion": 0.29,
                "eval_strategy": "target",
                "target_files": [6],
            },
            formal_training_scope_source="agent",
            formal_strategy="anchors",
            formal_portion=0.83,
            formal_train_portion=0.79,
            formal_eval_portion=0.43,
        ),
        "formal",
    )
    assert (config.trial_strategy, config.trial_portion, config.train_portion) == (
        "snapshot",
        0.37,
        0.61,
    )
    assert (config.eval_strategy, config.eval_portion, config.target_files) == (
        "snapshot",
        0.43,
        [],
    )
    events = {event.field_path: event for event in provenance.events}
    assert not {"trial_strategy", "trial_portion", "train_portion"} & events.keys()
    for field in ("eval_strategy", "eval_portion", "target_files"):
        assert events[field].executed == repr(getattr(config, field))
        assert events[field].authority == "resolved_round_workload"
    assert context["eval_portion"] == config.eval_portion


def test_validation_ceiling_reports_actual_all_three_portions_in_both_modes(tmp_path):
    captured = _run_real_route(
        tmp_path,
        authored={"trial_portion": 0.67, "train_portion": 0.71, "eval_portion": 0.79},
        formal_portion=0.83,
        formal_train_portion=0.89,
        formal_eval_portion=0.97,
        validation_max_portion=0.19,
    )
    for mode in ("trial", "formal"):
        config, provenance, context, _ = _only_mode(captured, mode)
        events = {event.field_path: event for event in provenance.events}
        for field in ("trial_portion", "train_portion", "eval_portion"):
            assert getattr(config, field) == 0.19
            assert events[field].executed == repr(getattr(config, field))
            assert events[field].authority == "resolved_round_workload"
        assert context["trial_portion"] == config.trial_portion
        assert context["eval_portion"] == config.eval_portion


def test_single_file_execution_defaults_do_not_repeat_planned_strategies(tmp_path):
    config, provenance, _, _ = _only_mode(
        _run_real_route(
            tmp_path,
            authored={
                "trial_strategy": "target",
                "eval_strategy": "target",
                "target_files": [6],
                "trial_portion": 0.37,
                "train_portion": 0.61,
            },
            is_trial=False,
            max_rounds=1,
        ),
        "single_file",
    )
    assert config.file_index == 6
    assert (config.trial_portion, config.train_portion) == (0.37, 0.61)
    assert (config.trial_strategy, config.eval_strategy, config.eval_portion) == (
        "snapshot",
        "snapshot",
        1.0,
    )
    events = {event.field_path: event for event in provenance.events}
    for field in ("trial_strategy", "eval_strategy", "eval_portion", "target_files"):
        assert events[field].executed == repr(getattr(config, field))
        assert events[field].authority == "resolved_round_workload"


pytestmark = pytest.mark.usefixtures("synthetic_run_authorities")
