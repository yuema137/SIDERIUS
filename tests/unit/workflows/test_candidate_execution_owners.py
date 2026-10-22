"""Parity witnesses for storage/context extraction from merged 23e71d10."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from workflows.attempt_storage import impl_attempt_storage
from workflows.run_context import bind_agent_run_context


def test_attempt_storage_matches_captured_pre_extraction_outputs():
    # Captured by invoking model_exploration.impl_attempt_storage BEFORE moving
    # it, at 23e71d109ed4fef1e3586e924d8af1ad8b5abc02. Pure synthetic paths;
    # no filesystem reads/writes occur at those locations.
    baseline = json.loads(
        (Path(__file__).parents[2] / "fixtures/workflow_attempt_storage.json").read_text()
    )
    for index, expected in baseline.items():
        actual = impl_attempt_storage(
            "/tmp/candidate/iteration_001/attempt_001", "candidate", int(index)
        )
        assert {
            "impl_dir": actual.impl_dir,
            "storage": actual.storage.model_dump(mode="json"),
            "plugin_dir": actual.plugin_dir,
            "test_dir": actual.test_dir,
            "loss_dir": actual.loss_dir,
        } == expected


@pytest.mark.parametrize("run_name,run_id", [(None, "id"), ("name", None), (None, None)])
def test_missing_identity_leaves_agent_and_bridge_untouched(tmp_path, run_name, run_id):
    agent = SimpleNamespace(set_run_context=Mock(), bridge=Mock())
    bind_agent_run_context(agent, workspace=tmp_path, iteration=4, run_name=run_name, run_id=run_id)
    agent.set_run_context.assert_not_called()
    agent.bridge.set_run_context.assert_not_called()


def test_eager_bridge_receives_current_iteration_and_path(tmp_path):
    bridge = Mock()
    agent = SimpleNamespace(bridge=bridge)
    for iteration in (1, 7):
        bind_agent_run_context(
            agent, workspace=str(tmp_path), iteration=iteration, run_name="chain", run_id="id"
        )
        bridge.set_run_context.assert_called_with(
            workspace=tmp_path, iter=iteration, run_name="chain", run_id="id"
        )
    assert bridge.set_run_context.call_count == 2


@pytest.mark.parametrize("agent", [SimpleNamespace(), SimpleNamespace(bridge=None)])
def test_agents_without_accounting_hook_remain_supported(tmp_path, agent):
    bind_agent_run_context(agent, workspace=tmp_path, iteration=1, run_name="chain", run_id="id")


def test_accounting_binding_errors_are_not_swallowed(tmp_path):
    agent = SimpleNamespace(set_run_context=Mock(side_effect=ValueError("identity changed")))
    with pytest.raises(ValueError, match="identity changed"):
        bind_agent_run_context(
            agent, workspace=tmp_path, iteration=2, run_name="chain", run_id="id"
        )
