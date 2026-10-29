"""The CSV task template through the console route its README teaches.

Copy the template to ``siderius_workspace/tasks/<id>/``, put CSV files in
``data/<id>/``, register it with ``add-task`` and read the Task summary.
"""

import importlib
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.helpers.csv_template_dataset import (
    TRAIN_ROWS,
    VALIDATION_ROWS,
    copy_template,
    write_csv_dataset,
)
from tools.candidate_console.app import create_app
from tools.candidate_console.workspace import init_workspace
from tools.workspace_sandbox.runner import ExecutionResult

REPO = Path(__file__).resolve().parents[4]


def _main(monkeypatch, capsys, *argv):
    from tools.candidate_console.__main__ import main

    monkeypatch.setattr(sys, "argv", ["candidate_console", *argv])
    code = main()
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_a_copied_template_registers_and_check_passes(tmp_path, monkeypatch, capsys):
    """Defect: the template's folder layout or package-relative references do
    not satisfy add-task's package mount, so the README's registration step
    fails, or check refuses a referenced file outside the mounted folder."""
    parent = tmp_path / "project"
    parent.mkdir(mode=0o700)
    config = init_workspace(str(parent))
    workspace = config.parent.parent
    manifest = copy_template(workspace / "tasks" / "iris")
    write_csv_dataset(workspace / "data" / "iris")

    code, out, err = _main(
        monkeypatch, capsys, "add-task", "--config", str(config), "--manifest", str(manifest)
    )
    assert code == 0, out + err
    assert "Added task iris" in out
    assert _main(monkeypatch, capsys, "check", "--config", str(config))[0] == 0


@pytest.fixture
def unsandboxed_child(monkeypatch):
    """The real composition child process, without bubblewrap (unavailable in CI)."""

    def offline(profile, argv):
        result = subprocess.run(argv, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stderr
        return ExecutionResult(status="completed", returncode=0, elapsed_seconds=0.0)

    monkeypatch.setattr(
        importlib.import_module("tools.setup_review.composition_check"), "run", offline
    )
    monkeypatch.setattr("tools.candidate_console.task_summary._start_thread", lambda work: work())


def test_task_summary_shows_score_health_lock_and_split_sizes(
    console_config, unsandboxed_child, tmp_path
):
    """Defect: the Task tab cannot show what the template declares. Fails if
    the main score, either Health gate with its declared role, the batch-size
    lock, the declared per-file volume or the counted split sizes are missing."""
    manifest = copy_template(tmp_path / "tasks" / "iris")
    task = console_config.tasks[0]
    write_csv_dataset(Path(task.data_root))
    config = console_config.model_copy(
        update={
            "tasks": (
                task.model_copy(
                    update={
                        "task_manifest": str(manifest),
                        "task_read_only": (str(manifest.parent),),
                        # The child resolves the profile's planner strategy, as the editor does.
                        "llm_config_file": str(REPO / "configs/llm/openai_tiered_pro.json"),
                    }
                ),
            )
        }
    )
    client = TestClient(create_app(config), base_url=config.browser_origin)
    client.headers.update(
        {
            "Authorization": "Bearer " + Path(config.auth_token_file).read_text(),
            "Origin": config.browser_origin,
        }
    )
    view = client.get("/api/tasks/synthetic/summary?count_samples=1").json()
    assert view["state"] == "ready", view
    package = view["package"]
    assert package["main_score"]["metric_id"] == "balanced_accuracy"
    assert package["main_score"]["direction"] == "higher"
    gates = {gate["gate_id"]: gate["role"] for gate in package["health"]["gates"]}
    assert package["health"]["declaration"] == "declared"
    assert gates == {
        "predicts_more_than_one_class": "blocking",
        "dominant_class_fraction": "observational",
    }
    assert [
        (lock["path"], lock["rule"], lock["value"]) for lock in package["locked_parameters"]
    ] == [("train_config.batch_size", "exact", 32)]
    assert package["scopes"]["state"] == "declared"
    assert package["scopes"]["evaluation"]["file_count"] == 1
    counts = package["sample_counts"]
    assert (counts["state"], counts["training"], counts["evaluation"]) == (
        "counted",
        TRAIN_ROWS,
        VALIDATION_ROWS,
    )
