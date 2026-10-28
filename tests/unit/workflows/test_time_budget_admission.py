"""#828: one owner refuses malformed operator time budgets on every launch path.

Before the fix a zero budget launched: forecast admission later clamped it to
~6e-8 s, measured admission later failed ``RuntimeControlPolicy`` and the
proposer preflight raised after its paid call. Each test here reached startup
(or produced a report) instead of refusing.
"""

from __future__ import annotations

import sys

import pytest

from workflows import model_exploration, run_one_iteration
from workflows.run_config import WorkflowLaunchConfig


class _StartupReached(Exception):
    """A valid configuration may reach startup; this test must not execute it."""


def _stop_startup(*args, **kwargs):
    raise _StartupReached


MALFORMED = ("0", "-5", "inf", "nan")
BUDGETS = (
    "trial_time_budget_minutes",
    "formal_time_budget_minutes",
    "bypass_formal_time_budget_minutes",
)


@pytest.mark.parametrize("field", BUDGETS)
@pytest.mark.parametrize("value", [*MALFORMED, "5"])
def test_iteration_cli_refuses_malformed_budget_before_workspace_binding(
    tmp_path, monkeypatch, capsys, field, value
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
            f"--{field}",
            value,
        ],
    )
    if value in MALFORMED:
        with pytest.raises(SystemExit) as error:
            run_one_iteration.main()
        assert error.value.code == 2
        message = capsys.readouterr().err
        assert field in message and "finite positive" in message
    else:
        with pytest.raises(_StartupReached):
            run_one_iteration.main()
    assert not workspace.exists()


@pytest.mark.parametrize("field", BUDGETS)
# 1e308 minutes is finite but overflows to inf seconds once consumers multiply by 60.
@pytest.mark.parametrize("value", [0.0, -5.0, float("inf"), float("nan"), 1e308])
def test_direct_workflow_refuses_malformed_budget_before_composition(
    tmp_path, monkeypatch, field, value
):
    workspace = tmp_path / "uncreated-run"
    monkeypatch.setattr(model_exploration, "verify_composition_is_bound", _stop_startup)
    with pytest.raises(ValueError, match=f"{field} must be a finite positive"):
        model_exploration.run_workflow(
            workspace=str(workspace),
            run_name="preflight",
            launch=WorkflowLaunchConfig(**{field: value}),
        )
    assert not workspace.exists()
