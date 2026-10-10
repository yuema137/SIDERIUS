"""Persistence extraction preserves bytes, errors and its real planning position."""

from importlib import import_module

import pytest

from agent.schemas.hyperparam_tuning import TrialConfig
from tests.unit.agent.tune_ml_hyperparam_agent.test_execution_provenance_scope import (
    _run_real_route,
)

planning = import_module("nodes.ml_hyperparameter_tune_agent.planning")

# Captured from the pre-extraction writer at b9ae7f40. No trailing newline.
TRIAL_CONFIG_BYTES = b"""{
  "is_trial": true,
  "mode": "trial",
  "trial_strategy": "snapshot",
  "trial_portion": 0.25,
  "train_portion": 0.75,
  "target_files": [
    7,
    2
  ],
  "eval_strategy": "snapshot",
  "eval_portion": 0.5,
  "train_validation_align": false,
  "file_index": null,
  "resolved_order_strategy": "sequential",
  "resolved_file_order": [
    7,
    2
  ],
  "train_sampling_seed": 19,
  "eval_sampling_seed": 29,
  "train_base_seed": 23
}"""


def test_persistence_preserves_exact_filename_and_overwrite_bytes(tmp_path):
    config = TrialConfig.model_validate_json(TRIAL_CONFIG_BYTES)
    destination = tmp_path / "trial_config_attempt_003.json"
    destination.write_bytes(b"stale content" * 100)
    planning._persist_trial_config(str(tmp_path), "attempt_003", config)
    assert destination.read_bytes() == TRIAL_CONFIG_BYTES
    assert list(tmp_path.iterdir()) == [destination]


def test_persistence_propagates_filesystem_error_without_creating_parent(tmp_path):
    config = TrialConfig.model_validate_json(TRIAL_CONFIG_BYTES)
    missing = tmp_path / "missing"
    with pytest.raises(FileNotFoundError) as caught:
        planning._persist_trial_config(str(missing), "attempt_003", config)
    assert caught.value.filename == str(missing / "trial_config_attempt_003.json")
    assert not missing.exists()


@pytest.mark.usefixtures("synthetic_run_authorities")
def test_real_planning_persists_each_scope_before_provenance(tmp_path, monkeypatch):
    persisted = []
    finalized = []
    original_write = planning._persist_trial_config
    original_finish = planning.ResolutionTracker.finish_with_model

    def write(configs_dir, exp_id, trial_config):
        original_write(configs_dir, exp_id, trial_config)
        from pathlib import Path

        saved = Path(configs_dir) / f"trial_config_{exp_id}.json"
        assert TrialConfig.model_validate_json(saved.read_bytes()) == trial_config
        persisted.append(trial_config)

    def finish(tracker, plan, *, executed_model_type, trial_config):
        assert len(persisted) == len(finalized) + 1
        assert persisted[-1] is trial_config
        finalized.append(trial_config.mode)
        return original_finish(
            tracker, plan, executed_model_type=executed_model_type, trial_config=trial_config
        )

    monkeypatch.setattr(planning, "_persist_trial_config", write)
    monkeypatch.setattr(planning.ResolutionTracker, "finish_with_model", finish)
    _run_real_route(tmp_path)
    assert finalized == ["trial", "formal"]
