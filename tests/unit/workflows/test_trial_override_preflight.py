"""#382: reject impossible operator overrides before any launch effects."""

from __future__ import annotations

import sys

import pytest

from workflows import model_exploration, run_one_iteration
from workflows.run_config import WorkflowLaunchConfig


class _StartupReached(Exception):
    """A valid configuration may reach startup; this test must not execute it."""


def _stop_startup(*args, **kwargs):
    raise _StartupReached


@pytest.mark.parametrize(
    "flags, invalid",
    [
        (["--trial_portion", "0.1"], True),
        (["--train_portion", "0.1"], True),
        (["--eval_portion", "0.1"], True),
        (["--plan_overrides", '{"trial_strategy":"anchors"}'], True),
        (["--trial_portion", "0.1", "--max_rounds", "2"], False),
        ([], False),
        (["--trial_portion", "0.1", "--no-force_formal_round"], False),
        (["--trial_portion", "0.1", "--no-is_trial"], False),
        (["--trial_portion", "0.1", "--formal_training_scope_source", "agent"], False),
        (["--eval_portion", "0.1", "--formal_training_scope_source", "agent"], True),
    ],
)
def test_iteration_cli_refuses_before_workspace_binding(
    tmp_path, monkeypatch, capsys, flags, invalid
):
    from core import generated_library

    workspace = tmp_path / "uncreated-run"
    monkeypatch.setattr(generated_library, "bind_generated_library_to_workspace", _stop_startup)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_one_iteration.py",
            "--workspace",
            str(workspace),
            "--run_name",
            "preflight",
            "--start_iteration",
            "1",
            "--task_composition",
            str(tmp_path / "must-not-be-opened.yaml"),
            "--data_dir",
            str(tmp_path / "must-not-be-read"),
            "--max_rounds",
            "1",
            "--force_formal_round",
            *flags,
        ],
    )
    if invalid:
        with pytest.raises(SystemExit) as error:
            run_one_iteration.main()
        assert error.value.code == 2
        message = capsys.readouterr().err
        assert "zero rounds" in message
        assert "max_rounds=1" in message
        assert "Remedies:" in message
    else:
        with pytest.raises(_StartupReached):
            run_one_iteration.main()
    assert not workspace.exists()


@pytest.mark.parametrize(
    "settings, invalid",
    [
        ({"trial_portion": 0.1}, True),
        ({"plan_overrides": {"eval_strategy": "anchors"}}, True),
        ({"trial_portion": 0.1, "max_rounds": 2}, False),
        ({}, False),
        ({"train_portion": 0.1, "formal_training_scope_source": "agent"}, False),
        ({"eval_portion": 0.1, "formal_training_scope_source": "agent"}, True),
        ({"trial_portion": 0.1, "plan_overrides": {"trial_portion": 0.2}}, True),
    ],
)
def test_direct_workflow_refuses_before_composition_or_nodes(
    tmp_path, monkeypatch, settings, invalid
):
    workspace = tmp_path / "uncreated-run"
    launch = WorkflowLaunchConfig(**({"is_trial": True, "max_rounds": 1} | settings))
    monkeypatch.setattr(model_exploration, "verify_composition_is_bound", _stop_startup)
    if invalid:
        with pytest.raises(ValueError, match=r"zero rounds|conflict"):
            model_exploration.run_workflow(
                workspace=str(workspace), run_name="preflight", launch=launch
            )
    else:
        with pytest.raises(_StartupReached):
            model_exploration.run_workflow(
                workspace=str(workspace), run_name="preflight", launch=launch
            )
    assert not workspace.exists()
