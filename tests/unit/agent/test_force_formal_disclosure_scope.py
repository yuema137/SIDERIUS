"""Issue #1200: launch policy must not masquerade as a current-round mandate."""

from pathlib import Path

import pytest

from agent.prompt_templates.constraints import render_constraint_disclosure
from agent.schemas.hyperparam_tuning import ExperimentPlan, HyperparamTuningInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_hyperparameter_tune_agent.timing_context import build_timing_context
from tests.helpers.llm_boundary_recorder import BoundaryRecorderBridge
from tests.helpers.tuner_prompt_fixtures import planner_kwargs
from workflows.constraint_disclosure import workflow_constraint_context
from workflows.run_config import WorkflowLaunchConfig


@pytest.mark.parametrize("current_round", [1, 9, 10])
def test_launch_flag_is_scoped_at_planner_provider_boundary(tmp_path: Path, current_round: int):
    """Unqualified disclosure fails even when the separate round banner is correct."""
    context = workflow_constraint_context(WorkflowLaunchConfig(force_formal_round=True), None)
    assert context is not None
    inp = HyperparamTuningInput(
        model_type="fixture_model",
        file_index=0,
        force_formal_round=True,
        max_rounds=10,
        storage=StorageConfig(
            backend="local", local=LocalStorageConfig(workspace=str(tmp_path), run_name="scope")
        ),
    )
    timing = build_timing_context(
        inp,
        trial_allowed=True,
        is_formal_round=current_round == 10,
        current_round=current_round,
        trial_winner=None,
        memory_history=[],
        scope_is_partial=False,
    )
    bridge = BoundaryRecorderBridge()
    bridge.plan(
        **(planner_kwargs() | {"current_round": current_round, "max_rounds": 10}),
        timing_context=timing,
        constraint_context=context,
    )
    user = bridge.captures[0][3]
    shared = user.split("[CURRENT RUN EXECUTION CONSTRAINTS]", 1)[1]
    assert (
        "execution.force_formal_round applies only to the final round of each iteration" in shared
    )
    assert "timing.forced_formal states whether THIS round is forced formal" in shared
    assert '"force_formal_round": true' in shared
    assert context.timing is None
    if current_round == 10:
        assert '"forced_formal": true' in shared
        assert "formal mode is MANDATORY" in user
    else:
        assert '"forced_formal": false' in shared
        assert "You may choose trial or formal mode" in user
        assert "formal mode is MANDATORY" not in user


def test_launch_disclosure_without_round_timing_does_not_invent_a_mandate():
    """Upstream agents see a launch snapshot without any current-round facts."""
    context = workflow_constraint_context(WorkflowLaunchConfig(force_formal_round=True), None)
    shared = render_constraint_disclosure(context)
    assert "it does not force earlier rounds to be formal" in shared
    assert "Without timing, the current round's forced-formal status is unknown" in shared


@pytest.mark.parametrize("invalid_targets", [1, 30])
def test_fallback_reports_bounded_error_without_raw_llm_input(
    capsys: pytest.CaptureFixture[str], invalid_targets: int
):
    """A fallback must explain the rejected field without dumping secrets or huge errors."""
    secret = "fixture-secret-do-not-log"
    plan, rejected = ExperimentPlan.parse_with_fallback(
        {
            "hypothesis": secret,
            "trial_portion": 5.0,
            "target_files": [secret] * invalid_targets,
        }
    )
    output = capsys.readouterr().out
    assert "falling back to defaults" in output
    assert "Validation error: " in output
    error = output.split("Validation error: ", 1)[1].rstrip("\n")
    assert "trial_portion" in error
    assert "less_than_equal" in error
    assert len(error) <= 512
    assert secret not in output
    assert "input" not in error
    assert "\n" not in error
    if invalid_targets == 30:
        assert error.endswith("...")
    assert plan.hypothesis == secret
    assert plan.trial_portion == 0.02
    assert rejected is None
