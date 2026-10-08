"""Review projection must be the actual object handed to the workflow."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.helpers.launcher_bindings import workflow_call_bindings
from workflows import launch_identity, run_one_iteration, standard_launch
from workflows.llm_config import resolve_standard_llm_config
from workflows.standard_cli import build_parser, normalize_args


def test_imports_do_not_launch_or_change_environment(tmp_path):
    script = """
import os
import socket
import sys
from pathlib import Path
import dotenv

def forbidden(*args, **kwargs):
    raise AssertionError('configuration import attempted launch effects')

dotenv.load_dotenv = forbidden
socket.socket.connect = forbidden
socket.create_connection = forbidden
before_files = set(Path.cwd().iterdir())
before_environment = dict(os.environ)
from workflows import launch_identity, standard_launch
from workflows.llm_config import resolve_standard_llm_config
assert 'workflows.run_one_iteration' not in sys.modules
assert 'workflows.model_exploration' not in sys.modules
assert set(Path.cwd().iterdir()) == before_files
assert dict(os.environ) == before_environment
"""
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    environment.pop("PYTHONPATH", None)
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def test_production_passes_shared_projection_to_workflow(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[3]
    routing = tmp_path / "llm.json"
    routing.write_text(json.dumps({"tune": {"planner_strategy": "native-timing-v1"}}))
    dataset = tmp_path / "data"
    dataset.mkdir()
    projected = []
    expected_locks = []
    original_invariants = run_one_iteration.compute_expected_invariants

    def capture_invariants(*args, **kwargs):
        result = original_invariants(*args, **kwargs)
        expected_locks.append(result)
        return result

    monkeypatch.setattr(run_one_iteration, "compute_expected_invariants", capture_invariants)

    def capture(*args, **kwargs):
        value = standard_launch.build_standard_launch_config(*args, **kwargs)
        projected.append(value)
        return value

    monkeypatch.setattr(run_one_iteration, "build_standard_launch_config", capture)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_one_iteration",
            "--workspace",
            str(tmp_path / "run"),
            "--run_name",
            "projection",
            "--start_iteration",
            "1",
            "--healthgate_mode",
            "blocking",
            "--result_authority",
            "scientific",
            "--task_composition",
            str(repo / "configs/task_composition/quickstart.yaml"),
            "--data_dir",
            str(dataset),
            "--llm_config",
            str(routing),
            "--runtime_completion_policy",
            "verified-prediction-v1",
            "--max_rounds",
            "7",
            "--trial_time_budget_minutes",
            "1.5",
            "--formal_time_budget_minutes",
            "9",
            "--validation_max_samples",
            "137",
        ],
    )
    with patch("workflows.model_exploration.run_workflow", side_effect=SystemExit(0)) as run:
        with pytest.raises(SystemExit) as exit_info:
            run_one_iteration.main()
    assert exit_info.value.code == 0
    assert len(projected) == 1
    assert run.call_args.kwargs["launch"] is projected[0]
    assert projected[0].data_dir == str(dataset.resolve())
    assert projected[0].runtime_completion_policy == "verified-prediction-v1"
    assert expected_locks[0].runtime_completion_policy == "verified-prediction-v1"
    assert projected[0].max_rounds == 7
    assert projected[0].trial_time_budget_minutes == 1.5
    assert projected[0].formal_time_budget_minutes == 9
    assert projected[0].validation_max_samples == 137
    assert run_one_iteration.resolve_launch_identity is launch_identity.resolve_launch_identity
    assert (
        run_one_iteration.parse_allowed_output_types is standard_launch.parse_allowed_output_types
    )


def test_forwarding_census_requires_reachable_projection():
    live = "run_workflow(launch=build_standard_launch_config(args, identity))"
    dead = "build_standard_launch_config(args, identity)\nrun_workflow(launch=other)"
    assert "formal_time_budget_minutes" in workflow_call_bindings(live)
    assert "formal_time_budget_minutes" not in workflow_call_bindings(dead)
    assigned = "cfg = build_standard_launch_config(args, identity)\nrun_workflow(launch=cfg)"
    rebound = (
        "cfg = build_standard_launch_config(args, identity)\ncfg = other\nrun_workflow(launch=cfg)"
    )
    assert "formal_time_budget_minutes" in workflow_call_bindings(assigned)
    assert "formal_time_budget_minutes" not in workflow_call_bindings(rebound)


@pytest.mark.parametrize(
    "flags, provider, model",
    [
        ([], "gemini", "gemini-2.5-flash"),
        (["--reflect_provider", "openai"], "openai", "gemini-3.1-pro-preview"),
        (["--reflect_model_id", "custom-model"], "gemini", "custom-model"),
    ],
)
def test_legacy_reflector_selection(flags, provider, model):
    args = normalize_args(
        build_parser().parse_args(
            [
                "--workspace",
                "run",
                "--run_name",
                "review",
                "--start_iteration",
                "1",
                "--task_composition",
                "task.yaml",
                "--data_dir",
                "data",
                *flags,
            ]
        )
    )
    config = resolve_standard_llm_config(args)
    assert config.get("tune")["reflect_provider"] == provider
    assert config.get("tune")["reflect_model_id"] == model


def test_json_routing_supersedes_legacy_model_without_filling_node_defaults(tmp_path):
    routing = tmp_path / "llm.json"
    routing.write_text(json.dumps({"interpret": {"provider": "openai", "model_id": "chosen"}}))
    args = normalize_args(
        build_parser().parse_args(
            [
                "--workspace",
                "run",
                "--run_name",
                "review",
                "--start_iteration",
                "1",
                "--task_composition",
                "task.yaml",
                "--data_dir",
                "data",
                "--llm_config",
                str(routing),
                "--llm_model",
                "ignored",
            ]
        )
    )
    config = resolve_standard_llm_config(args)
    assert config.get("interpret") == {"provider": "openai", "model_id": "chosen"}
    assert config.get("tune") == {}
