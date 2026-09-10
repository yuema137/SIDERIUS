"""Regression: slow steps need a caller-owned runtime-verification window.

The adaptive verifier historically stopped after its fixed 60-second wall
window. A workload whose first optimizer step took about one minute could
therefore never reach the five timed steps needed to establish steady state.
These tests prove the optional override crosses every typed launch boundary
and changes only the verifier window in the resulting runtime policy.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningInput
from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import local_validated_model
from core.runtime_control.session import RuntimeControlPolicy
from nodes.ml_hyperparameter_tune_agent import _build_runtime_policy
from sdsc_submission_scripts.run_one_iteration import build_parser
from workflows.run_config import WorkflowLaunchConfig

REPO_ROOT = Path(__file__).resolve().parents[3]
FIELD = "runtime_verification_max_wall_seconds"


def _call_keyword_value(path: Path, function_name: str, keyword: str) -> str:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == function_name
        ):
            for item in node.keywords:
                if item.arg == keyword:
                    return ast.unparse(item.value)
    raise AssertionError(f"{function_name}(...) does not pass {keyword}")


def test_override_crosses_the_typed_launch_boundaries() -> None:
    """A dropped field would silently restore the 60-second default."""
    args = build_parser().parse_args(
        [
            "--workspace",
            "/tmp/runtime-window",
            "--run_name",
            "runtime-window",
            "--task_composition",
            "/tmp/task-composition.yaml",
            "--data_dir",
            "/tmp/data",
            "--runtime_verification_max_wall_seconds",
            "420",
        ]
    )
    assert getattr(args, FIELD) == 420.0
    assert WorkflowLaunchConfig.__dataclass_fields__[FIELD].default is None
    assert FIELD in inspect.signature(local_validated_model).parameters
    assert FIELD in HyperparamTuningInput.model_fields

    launcher_value = _call_keyword_value(
        REPO_ROOT / "sdsc_submission_scripts" / "run_one_iteration.py",
        "WorkflowLaunchConfig",
        FIELD,
    )
    assert launcher_value == "args.runtime_verification_max_wall_seconds"

    workflow_value = _call_keyword_value(
        REPO_ROOT / "workflows" / "model_exploration.py",
        "local_validated_model",
        FIELD,
    )
    assert workflow_value == "launch.runtime_verification_max_wall_seconds"


def test_override_changes_only_the_adaptive_verifier_window() -> None:
    """Seconds must become milliseconds at the RuntimeControlPolicy boundary."""
    configured_input = HyperparamTuningInput.model_construct(
        runtime_verification_max_wall_seconds=420.0
    )
    configured = RuntimeControlPolicy.model_validate(
        _build_runtime_policy(
            configured_input,
            chosen_time_budget=10.0,
            is_trial=True,
            base_dir="/tmp/runtime-window",
        )
    )
    assert configured.verification.max_wall_ms == pytest.approx(420_000.0)
    assert configured.operator_budget_seconds == pytest.approx(600.0)

    default_input = HyperparamTuningInput.model_construct()
    default_policy = RuntimeControlPolicy.model_validate(
        _build_runtime_policy(
            default_input,
            chosen_time_budget=10.0,
            is_trial=True,
            base_dir="/tmp/runtime-window-default",
        )
    )
    assert default_policy.verification.max_wall_ms == pytest.approx(60_000.0)
