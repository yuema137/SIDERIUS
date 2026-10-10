"""Watchdog selection survives launch, persistence and resume boundaries."""

from __future__ import annotations

import json

import pytest

from core.run_invariants import (
    RunInvariants,
    RunInvariantsViolation,
    ensure_run_invariants,
)
from core.runtime_control.launch_argv import runtime_control_argv
from core.runtime_control.session import RuntimeControlPolicy
from nodes.ml_hyperparameter_tune_agent.cli import build_agent_input, build_parser
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import _lock_launch_identity
from nodes.ml_hyperparameter_tune_agent.runtime import _build_runtime_policy


@pytest.mark.parametrize("selection", ["budget-ceiling-v1", "forecast-tightening-v1"])
@pytest.mark.parametrize("admission_source", ["forecast", "measured"])
def test_node_cli_policy_saved_for_child(tmp_path, selection, admission_source):
    parser = build_parser()
    args = parser.parse_args(
        [
            "--data_dir",
            str(tmp_path),
            "--task_composition",
            "unused.yaml",
            "--planner_strategy",
            "native-timing-v1",
            "--runtime_watchdog",
            "--runtime_watchdog_deadline_policy",
            selection,
            "--trial_time_budget_minutes",
            "13.25",
            "--formal_time_budget_minutes",
            "47.5",
            "--trial_time_admission_source",
            admission_source,
            "--formal_time_admission_source",
            admission_source,
        ]
    )
    inp = build_agent_input(args, parser)
    assert _lock_launch_identity(inp).runtime_watchdog_deadline_policy == selection
    for is_trial, minutes in [(True, 13.25), (False, 47.5)]:
        policy = RuntimeControlPolicy.model_validate(
            _build_runtime_policy(
                inp,
                chosen_time_budget=minutes,
                admission_source=admission_source,
                is_trial=is_trial,
                base_dir=str(tmp_path),
            )
        )
        argv = runtime_control_argv(
            configs_dir=str(tmp_path),
            exp_id=str(is_trial),
            observation_out=str(tmp_path / "observation.json"),
            policy=policy,
            drop_stale_observation=False,
        )
        with open(argv[argv.index("--runtime_policy_json") + 1]) as handle:
            saved = json.load(handle)
        reloaded = RuntimeControlPolicy.model_validate(saved)
        assert reloaded.watchdog.deadline_policy == selection
        assert reloaded.operator_budget_seconds == (
            minutes * 60 if admission_source == "measured" else None
        )
        assert reloaded.watchdog.budget_seconds == (
            minutes * 60 if selection == "budget-ceiling-v1" else None
        )
        if selection == "forecast-tightening-v1":
            assert "budget_seconds" not in saved["watchdog"]


def test_disabled_selection_is_not_an_active_lock_or_watchdog_budget(tmp_path):
    parser = build_parser()
    inp = build_agent_input(
        parser.parse_args(
            [
                "--data_dir",
                str(tmp_path),
                "--task_composition",
                "unused.yaml",
                "--planner_strategy",
                "native-timing-v1",
            ]
        ),
        parser,
    )
    assert _lock_launch_identity(inp).runtime_watchdog_deadline_policy is None
    policy = RuntimeControlPolicy.model_validate(
        _build_runtime_policy(
            inp,
            chosen_time_budget=13.25,
            admission_source="forecast",
            is_trial=True,
            base_dir=str(tmp_path),
        )
    )
    assert not policy.watchdog.enabled
    assert policy.watchdog.budget_seconds is None
    assert (
        "runtime_watchdog_deadline_policy"
        not in RunInvariants(
            resolved_data_scope=[0],
            health_gate_enabled=False,
            health_config_sha256=None,
        ).model_dump()
    )


@pytest.mark.parametrize("old", [None, "budget-ceiling-v1", "forecast-tightening-v1"])
@pytest.mark.parametrize("new", [None, "budget-ceiling-v1", "forecast-tightening-v1"])
def test_resume_compares_effective_policy(tmp_path, old, new):
    def lock(selection):
        return RunInvariants(
            resolved_data_scope=[0],
            health_gate_enabled=False,
            health_config_sha256=None,
            runtime_watchdog_deadline_policy=selection,
        )

    ensure_run_invariants(str(tmp_path), lock(old))
    if old == new:
        ensure_run_invariants(str(tmp_path), lock(new))
    else:
        with pytest.raises(RunInvariantsViolation, match="runtime_watchdog_deadline_policy"):
            ensure_run_invariants(str(tmp_path), lock(new))


@pytest.mark.parametrize("selection", [None, "budget-ceiling-v1", "forecast-tightening-v1"])
def test_chain_forwards_selection_to_native_parser(selection):
    import subprocess
    from pathlib import Path

    from workflows.standard_cli import build_parser as standard_parser

    root = Path(__file__).resolve().parents[3]
    script = """
source scripts/launch/_chain_common.sh
parse_chain_args --workspace /tmp/unused-watchdog --run_name test --mode lilab "$@"
build_app_args 1
printf '%s\\0' "${APP_ARGS[@]}"
"""
    selected_args = [] if selection is None else ["--runtime_watchdog_deadline_policy", selection]
    result = subprocess.run(
        ["bash", "-c", script, "watchdog-transport", *selected_args],
        cwd=root,
        capture_output=True,
        check=True,
    )
    argv = result.stdout.decode().split("\0")[:-1]
    if selection is None:
        assert "--runtime_watchdog_deadline_policy" not in argv
    else:
        assert argv[argv.index("--runtime_watchdog_deadline_policy") + 1] == selection
    parsed = standard_parser().parse_args(
        [*argv, "--task_composition", "unused.yaml", "--data_dir", "/unused"]
    )
    assert parsed.runtime_watchdog_deadline_policy == (selection or "budget-ceiling-v1")
