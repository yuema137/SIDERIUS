"""Run-identity coverage for workflow-owned effective-plan constraints."""

import json
from pathlib import Path

import pytest

from core.run_invariants import (
    RunInvariants,
    RunInvariantsViolation,
    ensure_run_invariants,
    write_run_invariants,
)


def _invariants(rules: dict | None) -> RunInvariants:
    return RunInvariants(
        resolved_data_scope=[0],
        health_gate_enabled=False,
        health_config_sha256=None,
        runtime_estimator_identity="est-1",
        runtime_policy_identity="pol-1",
        workflow_parameter_rules=rules,
    )


def test_changed_workflow_parameter_rules_refuse_workspace_reuse(tmp_path: Path) -> None:
    """Catches two effective-plan treatments sharing one incumbent history."""
    workspace = str(tmp_path / "ws")
    exact = {"model_config.segmentation_size": {"exact": 40_000}}
    allowed = {"model_config.segmentation_size": {"allowed": [20_000, 40_000]}}
    ensure_run_invariants(workspace, _invariants(exact))

    with pytest.raises(RunInvariantsViolation, match="workflow_parameter_rules"):
        ensure_run_invariants(workspace, _invariants(allowed))


def test_unconstrained_rules_keep_the_legacy_lock_shape(tmp_path: Path) -> None:
    """Catches an unused feature rewriting every pre-existing lock."""
    path = write_run_invariants(str(tmp_path / "ws"), _invariants(None))

    payload = json.loads(Path(path).read_text(encoding="utf-8"))

    assert "workflow_parameter_rules" not in payload
