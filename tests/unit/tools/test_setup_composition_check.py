"""Parent boundary failures preserve user inputs and never follow child paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.setup_review import composition_check as parent
from tools.setup_review.composition_models import (
    CHILD_REQUEST_NAME,
    CHILD_RESULT_NAME,
    CompositionJob,
    CompositionResult,
    TaskCheckRequest,
    TaskCheckSettings,
    TaskCompositionSummary,
)
from tools.setup_review.models import SetupReviewRequest
from tools.workspace_sandbox.command import SandboxUnavailable
from tools.workspace_sandbox.runner import ExecutionResult


@pytest.fixture
def check_request(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    task = tmp_path / "task"
    task.mkdir()
    (task / "task.yaml").write_text("unexecuted: fixture\n")
    return TaskCheckRequest(
        setup=SetupReviewRequest(
            working_directory=str(tmp_path),
            argv=[
                "--workspace",
                "real-run",
                "--run_name",
                "synthetic",
                "--start_iteration",
                "1",
                "--task_composition",
                "task/task.yaml",
                "--data_dir",
                "data",
            ],
        ),
        scratch=tmp_path / "scratch",
        output=tmp_path / "report",
        read_only=(task,),
        settings=TaskCheckSettings(timeout_seconds=1),
    )


def _failed_child(profile, argv):
    job = CompositionJob.model_validate_json((profile.workspace / CHILD_REQUEST_NAME).read_bytes())
    result = CompositionResult.failed(job, "composition", ValueError("<script>fixture</script>"))
    (profile.workspace / CHILD_RESULT_NAME).write_text(result.model_dump_json())
    return ExecutionResult(status="completed", returncode=0, elapsed_seconds=0.1)


def test_handled_child_failure_is_escaped_and_command_remains_ordinary(check_request, monkeypatch):
    monkeypatch.setattr(parent, "run", _failed_child)
    report = parent.check_task(check_request)
    assert report.result.outcome == "failed"
    assert report.execution.status == "completed"
    assert report.request.settings.result_max_bytes == 1048576
    html = (check_request.output / "index.html").read_text()
    assert "&lt;script&gt;" in html and "<script>" not in html
    assert "settings.html" in html
    assert (
        report.declaration.launch_argv[-len(check_request.setup.argv) :] == check_request.setup.argv
    )
    assert not (Path(check_request.setup.working_directory) / "real-run").exists()


@pytest.mark.parametrize("status,code", [("failed", 7), ("timed_out", 124)])
def test_failed_execution_never_accepts_a_result_file(check_request, monkeypatch, status, code):
    monkeypatch.setattr(
        parent,
        "run",
        lambda *args: ExecutionResult(status=status, returncode=code, elapsed_seconds=0.1),
    )
    monkeypatch.setattr(
        parent,
        "read_composition_result",
        lambda *args: pytest.fail("failed child result was consumed"),
    )
    report = parent.check_task(check_request)
    assert report.result.failure.stage == "sandbox"
    assert report.execution.returncode == code


def test_missing_sandbox_does_not_fall_back_to_host_execution(check_request, monkeypatch):
    def unavailable(*args):
        raise SandboxUnavailable("install bubblewrap")

    monkeypatch.setattr(parent, "run", unavailable)
    report = parent.check_task(check_request)
    assert report.execution is None
    assert report.result.failure.exception_type == "SandboxUnavailable"
    assert "install bubblewrap" in report.result.failure.message
    assert (
        "No sandbox execution result is available."
        in (check_request.output / "index.html").read_text()
    )


def test_manifest_edit_is_stale_even_after_successful_transport(check_request, monkeypatch):
    def mutate(profile, argv):
        result = _failed_child(profile, argv)
        (check_request.read_only[0] / "task.yaml").write_text("edited: fixture\n")
        return result

    monkeypatch.setattr(parent, "run", mutate)
    report = parent.check_task(check_request)
    assert report.result.failure.stage == "stale_manifest"
    assert "changed during" in report.result.failure.message


@pytest.mark.parametrize(
    "kind", ["collision", "nested", "sources", "data", "missing_manifest_mount"]
)
def test_invalid_paths_refuse_before_sandbox_or_scratch_creation(check_request, monkeypatch, kind):
    monkeypatch.setattr(parent, "run", lambda *args: pytest.fail("sandbox must not start"))
    if kind == "collision":
        check_request.output.mkdir()
        (check_request.output / "keep").write_text("untouched")
    elif kind == "nested":
        check_request = check_request.model_copy(
            update={"output": check_request.scratch / "nested"}
        )
    elif kind == "sources":
        check_request = check_request.model_copy(
            update={"scratch": check_request.read_only[0] / "scratch"}
        )
    elif kind == "data":
        argv = list(check_request.setup.argv)
        argv[-1] = "task/data"
        check_request = check_request.model_copy(
            update={"setup": check_request.setup.model_copy(update={"argv": argv})}
        )
    else:
        check_request = check_request.model_copy(update={"read_only": ()})
    with pytest.raises(ValueError):
        parent.check_task(check_request)
    assert not check_request.scratch.exists()
    if kind == "collision":
        assert (check_request.output / "keep").read_text() == "untouched"


def test_partial_publication_preserves_concurrent_file(check_request, monkeypatch):
    monkeypatch.setattr(parent, "run", _failed_child)
    original = parent.publish_bytes_write_once

    def publish(path, payload):
        if Path(path).name == "index.html":
            Path(path).write_text("another writer")
        return original(path, payload)

    monkeypatch.setattr(parent, "publish_bytes_write_once", publish)
    with pytest.raises(FileExistsError):
        parent.check_task(check_request)
    assert (check_request.output / "index.html").read_text() == "another writer"
    assert (check_request.output / "report.json").is_file()


def test_oversized_result_names_actual_limit_and_action(check_request, monkeypatch):
    check_request = check_request.model_copy(
        update={"settings": TaskCheckSettings(timeout_seconds=1, result_max_bytes=16)}
    )
    monkeypatch.setattr(parent, "run", _failed_child)
    report = parent.check_task(check_request)
    assert report.result.failure.stage == "transport"
    assert "result_max_bytes=16" in report.result.failure.message
    assert "--result-max-bytes" in (check_request.output / "index.html").read_text()


def test_child_returned_paths_remain_display_only(check_request, monkeypatch):
    private = check_request.scratch.parent / "private.txt"
    private.write_text("private-content-must-not-be-read")
    task = TaskCompositionSummary(
        semantic_fingerprint="a" * 64,
        task_data_path_id="synthetic",
        task_config={},
        dataset_profile={},
        primary_metric={},
        secondary_metrics=[],
        parameter_rules={},
        inference_preflight={},
        source_paths={"task_description": str(private)},
        plugins=[],
        code_package_identity=None,
        prompt_renderer_identity=None,
        preflight_estimator_identity={},
        data_analysis_identity=None,
        task_health_declaration=str(private),
    )

    def child(profile, argv):
        job = CompositionJob.model_validate_json(
            (profile.workspace / CHILD_REQUEST_NAME).read_bytes()
        )
        result = CompositionResult.failed(job, "planner_strategy", ValueError("fixture"), task=task)
        (profile.workspace / CHILD_RESULT_NAME).write_text(result.model_dump_json())
        return ExecutionResult(status="completed", returncode=0, elapsed_seconds=0.1)

    original_open = Path.open

    def guarded_open(path, *args, **kwargs):
        assert path != private, "parent followed a child-returned source path"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(parent, "run", child)
    monkeypatch.setattr(Path, "open", guarded_open)
    report = parent.check_task(check_request)
    assert report.result.task.source_paths["task_description"] == str(private)
    saved = (check_request.output / "report.json").read_text()
    html = (check_request.output / "index.html").read_text()
    assert str(private) in saved + html
    assert "private-content-must-not-be-read" not in saved + html
