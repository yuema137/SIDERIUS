"""Read-only Task summary: real composition facts, fail-soft states, cache identity."""

import importlib
import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tools.candidate_console.app import create_app
from tools.candidate_console.task_summary import TaskSummaries, walk_data_root
from tools.setup_review.composition_models import CompositionJob, CompositionObservation
from tools.workspace_sandbox.command import SandboxUnavailable
from tools.workspace_sandbox.runner import ExecutionResult
from workflows.definition import TaskBinding

REPO = Path(__file__).resolve().parents[4]
SECRET = "sk-test-secret-value-never-shown"


def _client(config):
    client = TestClient(
        create_app(config), base_url=config.browser_origin, raise_server_exceptions=False
    )
    client.headers.update(
        {
            "Authorization": "Bearer " + Path(config.auth_token_file).read_text(),
            "Origin": config.browser_origin,
        }
    )
    return client


@pytest.fixture
def synchronous(monkeypatch):
    """Observation runs inline so a single GET returns its terminal state."""
    monkeypatch.setattr("tools.candidate_console.task_summary._start_thread", lambda work: work())


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


def _quickstart_data(root: Path) -> None:
    import sys

    sys.path.insert(0, str(REPO / "examples/quickstart/plugins"))
    try:
        from _quickstart_task import write_data_dir
    finally:
        sys.path.remove(str(REPO / "examples/quickstart/plugins"))
    write_data_dir(root)


def test_quickstart_summary_projects_owner_facts_and_counts_only_on_request(
    console_config, synchronous, unsandboxed_child, monkeypatch
):
    """Defects: a fact read from the wrong owner (metric, plugin role, objective), a
    task without ``storage_read_scope`` shown as 0 bytes, samples counted without an
    explicit request, or a credential value leaking into the view."""
    task = console_config.tasks[0]
    _quickstart_data(Path(task.data_root))
    credentials = Path(task.data_root).parent / "credentials.json"
    credentials.write_text(json.dumps({"OPENAI_API_KEY": SECRET}))
    credentials.chmod(0o600)
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    config = console_config.model_copy(
        update={
            "credential_file": str(credentials),
            "tasks": (
                task.model_copy(
                    update={
                        "candidate_environment_names": ("OPENAI_API_KEY",),
                        # The child resolves the profile's planner strategy, as the editor does.
                        "llm_config_file": str(REPO / "configs/llm/openai_tiered_pro.json"),
                    }
                ),
            ),
        }
    )
    client = _client(config)

    plain = client.get("/api/tasks/synthetic/summary")
    assert plain.status_code == 200, plain.text
    view = plain.json()
    assert view["state"] == "ready", view
    package = view["package"]
    assert package["main_score"] == {
        "metric_id": "accuracy",
        "direction": "higher",
        "aggregation": "fraction_correct_over_eval_rows",
    }
    assert package["health"] == {"declaration": "explicit_none", "gates": []}
    assert package["objective_source"] == "task"
    assert {p["symbol"]: p["roles"] for p in package["plugins"]} == {
        "QuickstartTaskDataPath": ["task_data_path"],
        "QuickstartAccuracyMetric": ["primary_metric"],
        "quickstart_reference_mlp": ["model_plugin"],
    }
    assert package["scopes"]["state"] == "not_declared"
    assert package["scopes"]["training"] is None and package["scopes"]["evaluation"] is None
    assert package["sample_counts"] is None
    assert view["data_volume"] == {
        "files": 4,
        "bytes": view["data_volume"]["bytes"],
        "complete": True,
        "entry_cap": 100_000,
    }
    assert view["run_policy"]["candidate_environment_names"] == ["OPENAI_API_KEY"]

    counted = client.get("/api/tasks/synthetic/summary?count_samples=1").json()
    assert counted["package"]["sample_counts"]["state"] == "counted"
    counts = counted["package"]["sample_counts"]
    assert (counts["training"], counts["evaluation"]) == (128, 64)

    for body in (plain.text, json.dumps(counted)):
        assert SECRET not in body


@pytest.mark.parametrize("missing", ["sandbox", "data_root"])
def test_unavailable_prerequisites_return_a_state_with_a_hint_not_a_500(
    console_config, synchronous, monkeypatch, missing
):
    """Defect: a host without bubblewrap or a deleted data folder surfaces as an HTTP
    500 or a generic failure instead of a named, fixable ``unavailable`` reason."""

    def no_sandbox(profile, argv):
        raise SandboxUnavailable("install bubblewrap (bwrap) and enable user namespaces")

    monkeypatch.setattr(
        importlib.import_module("tools.setup_review.composition_check"), "run", no_sandbox
    )
    client = _client(console_config)
    if missing == "data_root":
        # Startup requires the folder; it can disappear while the console runs.
        data = Path(console_config.tasks[0].data_root)
        data.rename(data.with_name("moved-aside"))
    response = client.get("/api/tasks/synthetic/summary")
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["state"] == "unavailable"
    assert view["unavailable"]["reason"] == f"{missing}_missing"
    assert view["unavailable"]["hint"]


def test_unknown_task_is_404_and_list_names_configured_tasks(console_config):
    """Defect: the Task list shows a version the console configuration does not declare,
    or hides the configured ``task_revision`` the Task tab labels each task with, or its
    ``package_id`` the Workflow page bar compares with a workflow's pinned binding."""
    client = _client(console_config)
    assert client.get("/api/tasks/nope/summary").status_code == 404
    assert client.get("/api/tasks").json() == {
        "tasks": [
            {
                "task_id": "synthetic",
                "label": "Synthetic task",
                "revision": None,
                "package_id": None,
            }
        ]
    }
    pin = TaskBinding(
        package_id="synthetic-task",
        revision="r2",
        task_data_path_id="synthetic-data",
        semantic_fingerprint="a" * 64,
    )
    versioned = console_config.model_copy(
        update={"tasks": (console_config.tasks[0].model_copy(update={"task_revision": pin}),)}
    )
    listed = _client(versioned).get("/api/tasks").json()["tasks"][0]
    assert (listed["revision"], listed["package_id"]) == ("r2", "synthetic-task")


def test_data_walk_cap_reports_an_incomplete_volume(tmp_path):
    """Defect: a capped walk reported as the complete data size."""
    (tmp_path / "nested").mkdir()
    for index in range(5):
        (tmp_path / "nested" / f"f{index}").write_bytes(b"x" * 10)
    (tmp_path / "link").symlink_to(tmp_path / "nested")
    assert walk_data_root(tmp_path, cap=3).complete is False
    full = walk_data_root(tmp_path)
    # The symlinked directory is an entry, never followed: 5 files, not 10.
    assert (full.files, full.bytes, full.complete) == (5, 50, True)


def test_cache_reuses_an_observation_until_the_manifest_changes_or_refresh(
    console_config, tmp_path
):
    """Defect: an edited task package keeps showing stale facts, or every GET relaunches
    the sandboxed child."""
    manifest = tmp_path / "copy.yaml"
    manifest.write_text("first\n")
    task = console_config.tasks[0].model_copy(update={"task_manifest": str(manifest)})
    calls: list[CompositionJob] = []

    def observer(job: CompositionJob, _task) -> CompositionObservation:
        calls.append(job)
        raise RuntimeError("observation stub")

    summaries = TaskSummaries((task,), observer=observer, start=lambda work: work())
    assert summaries.summary("synthetic").state == "failed"
    summaries.summary("synthetic")
    assert len(calls) == 1
    manifest.write_text("second\n")
    summaries.summary("synthetic")
    assert len(calls) == 2 and calls[0].manifest_sha256 != calls[1].manifest_sha256
    summaries.summary("synthetic", refresh=True)
    assert len(calls) == 3


def test_locked_parameters_keep_an_exact_null_lock():
    """Defect: ``{"exact": null}`` (a lock to null) is skipped as if no rule existed,
    so the Task panel hides a locked parameter. Input is the owner's real dump."""
    from agent.schemas.parameter_rules import ParameterRules
    from tools.candidate_console.task_summary import _locked

    rules = ParameterRules.model_validate(
        {
            "rules": {
                "train_config.batch_size": {"exact": None},
                "loss_config.reduction": {"allowed": ["mean"]},
            }
        }
    ).model_dump(mode="json")
    assert sorted((item.path, item.rule, item.value) for item in _locked(rules)) == [
        ("loss_config.reduction", "allowed", ["mean"]),
        ("train_config.batch_size", "exact", None),
    ]


def test_console_failure_message_is_bounded(console_config):
    """Defect: an observer exception produces an arbitrarily large console view."""
    from tools.setup_review.composition_models import FAILURE_MESSAGE_MAX_CHARS

    def fail(job, task):
        raise RuntimeError("x" * (FAILURE_MESSAGE_MAX_CHARS + 100))

    summaries = TaskSummaries(console_config.tasks, observer=fail, start=lambda work: work())
    view = summaries.summary("synthetic")
    assert view is not None and view.state == "failed" and view.failure is not None
    assert view.failure.stage == "console"
    assert view.failure.message == ("RuntimeError: " + "x" * 10000)[:FAILURE_MESSAGE_MAX_CHARS]
    assert len(view.failure.message) == FAILURE_MESSAGE_MAX_CHARS


def test_data_walk_deadline_reports_partial_totals(tmp_path, monkeypatch):
    """Defect: entry-limited walks keep running after their wall-time budget expires."""
    import time

    (tmp_path / "first").write_bytes(b"abc")
    (tmp_path / "second").write_bytes(b"def")
    ticks = iter([0.0, 0.0, 0.0, 0.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(ticks, 10.0))
    volume = walk_data_root(tmp_path)
    assert volume.complete is False
    assert (volume.files, volume.bytes) == (1, 3)


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_data_walk_skips_other_devices(tmp_path, monkeypatch, kind):
    """Defect: a mount beneath data_root is traversed and reported as complete."""
    import os
    from types import SimpleNamespace

    from tools.candidate_console import task_summary

    mount = tmp_path / "mount"
    if kind == "directory":
        mount.mkdir()
        (mount / "foreign").write_bytes(b"foreign")
    else:
        mount.write_bytes(b"foreign")
    scandir = os.scandir
    device = tmp_path.stat().st_dev

    class ForeignEntry:
        path = str(mount)

        def stat(self, *, follow_symlinks):
            return SimpleNamespace(st_dev=device + 1, st_size=7)

        def is_dir(self, *, follow_symlinks):
            return kind == "directory"

        def is_file(self, *, follow_symlinks):
            return kind == "file"

    class Listing:
        def __enter__(self):
            return iter([ForeignEntry()])

        def __exit__(self, *args):
            pass

    def listing(path):
        return Listing() if Path(path) == tmp_path else scandir(path)

    monkeypatch.setattr(task_summary.os, "scandir", listing)
    volume = walk_data_root(tmp_path)
    assert volume.complete is False
    assert (volume.files, volume.bytes) == (0, 0)
