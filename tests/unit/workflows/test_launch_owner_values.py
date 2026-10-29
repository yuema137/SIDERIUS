"""#1045: timeouts, safety factors and the degenerate penalty refuse inf/NaN.

Their tuner owners declared only ``gt``/``ge`` bounds, which accept ``inf``
(and the penalty accepted any float), so an infinite timeout silently removed
its bound and an infinite safety factor made every forecast infeasible. The
direct workflow also never checked these values before composition, and the
candidate ingress accepted them.
"""

from __future__ import annotations

import pytest

from workflows import model_exploration
from workflows.candidate_training_settings import CandidateTrainingSettings
from workflows.run_config import WorkflowLaunchConfig

INF = float("inf")
NAN = float("nan")
REFUSED = [
    ("vram_probe_step_timeout_seconds", INF),
    ("vram_preflight_total_timeout_seconds", INF),
    ("vram_preflight_host_memory_limit_gb", INF),
    ("runtime_safety_factor", INF),
    ("runtime_trial_safety_factor", INF),
    ("runtime_formal_safety_factor", INF),
    ("runtime_watchdog_safety_factor", INF),
    ("runtime_watchdog_floor_seconds", INF),
    ("runtime_verification_max_wall_seconds", INF),
    ("validation_max_phase_seconds", INF),
    ("degenerate_penalty_score", -INF),
    ("degenerate_penalty_score", INF),
    ("degenerate_penalty_score", NAN),
]


class _StartupReached(Exception):
    pass


def _stop_startup(*args, **kwargs):
    raise _StartupReached


@pytest.mark.parametrize("field,value", REFUSED)
def test_direct_workflow_refuses_nonfinite_owner_value_before_composition(
    tmp_path, monkeypatch, field, value
):
    monkeypatch.setattr(model_exploration, "verify_composition_is_bound", _stop_startup)
    launch = WorkflowLaunchConfig(**{field: value})
    if field == "validation_max_phase_seconds":
        # Its owner also requires the watchdog that enforces it.
        launch = WorkflowLaunchConfig(**{field: value, "runtime_watchdog_enabled": True})
    with pytest.raises(ValueError, match=f"is refused by HyperparamTuningInput.{field}"):
        model_exploration.run_workflow(
            workspace=str(tmp_path / "uncreated-run"), run_name="preflight", launch=launch
        )
    assert not (tmp_path / "uncreated-run").exists()


@pytest.mark.parametrize("field,value", REFUSED)
def test_candidate_ingress_refuses_the_same_values(field, value):
    extra = {"runtime_watchdog_enabled": True} if field == "validation_max_phase_seconds" else {}
    with pytest.raises(ValueError, match=f"HyperparamTuningInput.{field}"):
        CandidateTrainingSettings(launch=WorkflowLaunchConfig(**{field: value}, **extra))


@pytest.mark.parametrize(
    "field,value,owner",
    [
        ("target_score", NAN, "WorkflowLaunchConfig"),
        ("minimum_boldness", NAN, "ResearchPolicy"),
        ("minimum_boldness", INF, "ResearchPolicy"),
    ],
)
def test_launch_only_floats_are_checked_by_their_owners(tmp_path, monkeypatch, field, value, owner):
    """#1045 review: these have no tuner owner, so the launch check skipped them.
    A NaN target_score makes every early-stop comparison False."""
    monkeypatch.setattr(model_exploration, "verify_composition_is_bound", _stop_startup)
    with pytest.raises(ValueError, match=rf"is refused by {owner}\.{field}"):
        model_exploration.run_workflow(
            workspace=str(tmp_path / "uncreated-run"),
            run_name="preflight",
            launch=WorkflowLaunchConfig(**{field: value}),
        )


def test_refusal_says_how_to_omit_only_when_none_is_admissible():
    """#1045 review: the budget-specific "omit it (None)" guidance was lost."""
    from workflows.run_config import validate_launch_admission

    with pytest.raises(ValueError) as optional:
        validate_launch_admission(WorkflowLaunchConfig(trial_time_budget_minutes=0.0))
    assert "Omit it (None)" in str(optional.value)
    with pytest.raises(ValueError) as required:
        validate_launch_admission(WorkflowLaunchConfig(runtime_safety_factor=INF))
    assert "Omit it (None)" not in str(required.value)


@pytest.mark.parametrize(
    "flag,value",
    [
        ("--vram_probe_step_timeout_seconds", "inf"),
        ("--degenerate_penalty_score", "nan"),
        ("--runtime_watchdog_floor_seconds", "inf"),
        ("--minimum_boldness", "nan"),
    ],
)
def test_iteration_cli_exits_2_before_workspace_binding(tmp_path, monkeypatch, capsys, flag, value):
    """#1045 review: main()'s early check covered only schedule and budget
    fields, so these reached workspace binding and failed later in run_workflow."""
    import sys

    from core import generated_library
    from workflows import run_one_iteration

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
            flag,
            value,
        ],
    )
    with pytest.raises(SystemExit) as error:
        run_one_iteration.main()
    assert error.value.code == 2
    assert f"{flag[2:]}={value}" in capsys.readouterr().err
    assert not workspace.exists()
