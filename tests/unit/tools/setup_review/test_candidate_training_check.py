"""Native retained-training checks reject only real target incompatibilities."""

import json
from pathlib import Path

import pytest

from execute_tools.task_registration_scope import run_registration_scope
from tools.setup_review.candidate_check import check_candidate
from tools.setup_review.composition_models import CandidateCheckOptions
from workflows.task_composition import compose_run_task_bindings

REPO_ROOT = Path(__file__).resolve().parents[4]


def _composition():
    with run_registration_scope():
        return compose_run_task_bindings(
            str(REPO_ROOT / "configs/task_composition/quickstart.yaml")
        )


def _settings(**updates):
    value = {
        "launch": {"healthgate_mode": "observe_only", "result_authority": "diagnostic"},
        "health_gate_enabled": False,
    }
    value.update(updates)
    return value


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        (
            {
                "launch": {
                    "healthgate_mode": "observe_only",
                    "result_authority": "diagnostic",
                    "data_dir": "old-run-root",
                }
            },
            "data_dir",
        ),
        ({"data_scope": {"file_indices": [4]}}, "out of range"),
        (
            {
                "file_order_override": [0, 1, 2],
                "order_strategy_override": "sequential",
            },
            "permutation",
        ),
        ({"data_scope": {"file_indices": [0]}}, "legacy vocabulary"),
        ({"launch": {}}, "must declare"),
        (
            {"launch": {"healthgate_mode": "observe_only", "result_authority": "scientific"}},
            "contradiction",
        ),
        (
            {
                "launch": {
                    "healthgate_mode": "observe_only",
                    "result_authority": "diagnostic",
                    "workflow_parameter_rules": {"rules": {"loss_config.alpha": {"exact": 1}}},
                }
            },
            "sole owner",
        ),
    ],
)
def test_target_training_check_uses_native_scope_posture_order_and_rule_owners(
    tmp_path, settings, expected
):
    """Actual quickstart composition reaches each native owner and blocks its mismatch."""
    composition = _composition()
    payload = json.dumps(_settings(**settings))
    options = CandidateCheckOptions(allowed_output_types=None, training_settings=payload)
    scratch = tmp_path / "inspection"
    scratch.mkdir()
    with pytest.raises(ValueError, match=expected):
        check_candidate(composition, options, str(scratch))


def test_target_training_check_rejects_empty_health_file_selection(tmp_path):
    """Enabled Health cannot materialize an empty monitored-file roster."""
    from tools.setup_review.candidate_training_check import check_training_settings
    from workflows.candidate_training_settings import CandidateTrainingSettings

    composition = _composition()
    settings = CandidateTrainingSettings.model_validate(
        _settings(health_gate_enabled=True, health_gate_files=[])
    )
    scratch = tmp_path / "inspection"
    scratch.mkdir()
    with pytest.raises(ValueError, match="files must be non-empty"):
        check_training_settings(settings, composition, str(scratch))
