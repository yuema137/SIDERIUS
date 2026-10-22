"""#779: raw workflow names refuse before task/default binding or mkdir."""

from unittest.mock import MagicMock

import pytest

import workflows.model_exploration as workflow


@pytest.mark.parametrize("name", ["../escape", "/absolute", "folder\\escape", "run:name"])
def test_workflow_refuses_before_launch_defaults_without_task_binding(tmp_path, monkeypatch, name):
    defaults = MagicMock(side_effect=AssertionError("launch defaults reached"))
    monkeypatch.setattr(workflow, "WorkflowLaunchConfig", defaults)
    with pytest.raises(ValueError, match=r"run_name.*filesystem component"):
        workflow.run_workflow(workspace=str(tmp_path / "workspace"), run_name=name)
    defaults.assert_not_called()
    assert list(tmp_path.iterdir()) == []
