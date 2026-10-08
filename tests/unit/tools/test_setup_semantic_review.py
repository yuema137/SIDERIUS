"""Optional review binds a snapshot without importing or launching its task."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.setup_review.inspection import inspect_declaration
from tools.setup_review.models import SetupReviewRequest
from tools.setup_review.review import main
from tools.setup_review.semantic_models import SemanticReviewRequest, SetupJudgement
from tools.setup_review.semantic_review import review_snapshot


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "task.yaml").write_text("not executable task source")
    request = SetupReviewRequest(
        working_directory=str(tmp_path),
        argv=[
            "--workspace",
            "run",
            "--run_name",
            "sample",
            "--start_iteration",
            "1",
            "--task_composition",
            "task.yaml",
            "--data_dir",
            "data",
            "--max_rounds",
            "4",
        ],
    )
    report = inspect_declaration(request, tmp_path / "preview")
    report = report.model_copy(update={"declared_llm_config": {"api_key": "PRIVATE_EXTRA"}})
    payload = report.model_dump_json().encode()
    source = tmp_path / "report.json"
    source.write_bytes(payload)
    return source, payload


def operation(snapshot, tmp_path, kind="skip", **updates):
    source, payload = snapshot
    values = dict(
        kind=kind,
        report=str(source),
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        output=str(tmp_path / "review"),
        input_max_bytes=1024 * 1024,
    )
    if kind == "skip":
        values["reason"] = "I will inspect this snapshot myself."
    else:
        values.update(
            llm={"provider": "openai", "model_id": "synthetic-reviewer", "max_retries": 1},
            total_review_seconds=10,
            request_timeout_seconds=5,
        )
    values.update(updates)
    return SemanticReviewRequest.model_validate({"operation": values})


def judgement():
    return SetupJudgement(
        summary="<script>not approval</script>",
        findings=[],
        uncovered_checks=["Verify actual data and hardware"],
    )


def install_gateway(monkeypatch, *, constructor=None, generate=None):
    captured = {}

    class FakeBridge:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs
            if constructor:
                constructor()

        def set_run_context(self, **kwargs):
            captured["context"] = kwargs

        def generate(self, system, user, **kwargs):
            captured["system"] = system
            captured["user"] = user
            captured["label"] = kwargs["label"]
            if generate:
                return generate()
            return judgement().model_dump()

    monkeypatch.setitem(sys.modules, "agent.llm_bridge", SimpleNamespace(LLMBridge=FakeBridge))
    return captured


def test_review_uses_public_gateway_and_saved_exact_packet(snapshot, tmp_path, monkeypatch):
    captured = install_gateway(monkeypatch)
    receipt = review_snapshot(operation(snapshot, tmp_path, "review"))
    assert receipt.outcome == "reviewed"
    assert captured["kwargs"] == {
        "provider": "openai",
        "model_id": "synthetic-reviewer",
        "max_retries": 1,
        "request_timeout": 5,
    }
    assert captured["label"] == "setup_review.judge"
    assert captured["context"]["workspace"] == tmp_path / "review"
    assert captured["context"]["iter"] == 0
    assert captured["user"] == (tmp_path / "review/user.txt").read_text()
    assert captured["system"] == (tmp_path / "review/system.txt").read_text()
    assert receipt.user_sha256 == hashlib.sha256(captured["user"].encode()).hexdigest()
    assert "PRIVATE_EXTRA" not in captured["user"]
    assert '"declared_value": 4' in captured["user"]
    page = (tmp_path / "review/index.html").read_text()
    assert "<script>not approval</script>" not in page
    assert "&lt;script&gt;not approval&lt;/script&gt;" in page
    assert snapshot[0].read_bytes() == snapshot[1]
    assert not (tmp_path / "run").exists()


def test_skip_records_choice_and_cli_does_not_upgrade_original(snapshot, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("skip called a provider")

    install_gateway(monkeypatch, constructor=forbidden)
    request = operation(snapshot, tmp_path, reason="<b>Manual review</b>")
    request_file = tmp_path / "skip.json"
    request_file.write_text(request.model_dump_json())
    assert main(["--request", str(request_file)]) == 0
    saved = json.loads((tmp_path / "review/receipt.json").read_text())
    assert saved["outcome"] == "skipped"
    assert saved["skip_reason"] == "<b>Manual review</b>"
    assert saved["reviewer"] is None and saved["budget"] is None
    assert not (tmp_path / "review/system.txt").exists()
    assert json.loads(snapshot[0].read_bytes())["llm_review"] == "not_performed"
    assert "&lt;b&gt;Manual review&lt;/b&gt;" in (tmp_path / "review/index.html").read_text()


@pytest.mark.parametrize("case", ["digest", "oversized", "fifo", "symlink", "schema", "conflict"])
def test_bad_snapshot_refused_before_gateway(snapshot, tmp_path, monkeypatch, case):
    captured = install_gateway(monkeypatch)
    source, payload = snapshot
    kwargs = {}
    if case == "digest":
        kwargs["expected_sha256"] = "0" * 64
    elif case == "oversized":
        kwargs["input_max_bytes"] = 2
    elif case == "fifo":
        source.unlink()
        os.mkfifo(source)
    elif case == "symlink":
        target = tmp_path / "target.json"
        source.rename(target)
        source.symlink_to(target)
    elif case == "schema":
        payload = b'{"schema_version":"unknown"}'
        source.write_bytes(payload)
        kwargs["expected_sha256"] = hashlib.sha256(payload).hexdigest()
    else:
        (tmp_path / "review").mkdir()
        (tmp_path / "review/keep").write_text("existing")
    with pytest.raises((OSError, ValueError)):
        review_snapshot(operation(snapshot, tmp_path, "review", **kwargs))
    assert not captured
    if case == "conflict":
        assert (tmp_path / "review/keep").read_text() == "existing"


@pytest.mark.parametrize("failure", ["transport", "schema"])
def test_failure_is_not_reviewed_and_exception_text_not_saved(
    snapshot, tmp_path, monkeypatch, failure
):
    def fail():
        if failure == "transport":
            raise RuntimeError("PRIVATE_PROVIDER_ERROR")
        return {"unknown": "PRIVATE_MODEL_FIELD"}

    install_gateway(monkeypatch, generate=fail)
    request = operation(snapshot, tmp_path, "review")
    path = tmp_path / "operation.json"
    path.write_text(request.model_dump_json())
    assert main(["--request", str(path)]) == 2
    raw = (tmp_path / "review/receipt.json").read_text()
    assert json.loads(raw)["outcome"] == "failed"
    assert "PRIVATE_PROVIDER_ERROR" not in raw and "PRIVATE_MODEL_FIELD" not in raw


@pytest.mark.parametrize("phase", ["read", "constructor", "response", "validation"])
def test_one_deadline_includes_preparation_and_gateway(snapshot, tmp_path, monkeypatch, phase):
    import core.execution_deadline as clock
    import tools.setup_review.semantic_review as review

    now = [10.0]
    monkeypatch.setattr(clock.time, "monotonic", lambda: now[0])

    def expire():
        now[0] = 25.0

    if phase == "read":
        original = review._read_snapshot

        def delayed(*args):
            result = original(*args)
            expire()
            return result

        monkeypatch.setattr(review, "_read_snapshot", delayed)
    if phase == "validation":
        original_validate = SetupJudgement.model_validate

        def delayed_validation(value):
            result = original_validate(value)
            expire()
            return result

        monkeypatch.setattr(SetupJudgement, "model_validate", delayed_validation)
    captured = install_gateway(
        monkeypatch,
        constructor=expire if phase == "constructor" else None,
        generate=(lambda: (expire(), judgement().model_dump())[1]) if phase == "response" else None,
    )
    request = operation(snapshot, tmp_path, "review")
    if phase == "read":
        with pytest.raises(clock.ExecutionDeadlineExceeded):
            review_snapshot(request)
        assert not captured and not (tmp_path / "review").exists()
    else:
        receipt = review_snapshot(request)
        assert receipt.outcome == "failed" and receipt.failure_category == "deadline_exceeded"
        assert receipt.budget.elapsed_seconds == 15
        if phase == "constructor":
            assert "user" not in captured


def test_failed_composition_remains_failure_in_packet(snapshot, tmp_path, monkeypatch):
    from tools.setup_review.composition_models import (
        CompositionJob,
        CompositionResult,
        TaskCheckReport,
        TaskCheckRequest,
        TaskCheckSettings,
        TaskCompositionSummary,
    )
    from tools.setup_review.models import SetupDeclarationReport
    from tools.workspace_sandbox.profile import SandboxProfile

    declaration = SetupDeclarationReport.model_validate_json(snapshot[1])
    (tmp_path / "scratch").mkdir()
    settings = TaskCheckSettings(timeout_seconds=1)
    job = CompositionJob(
        manifest=declaration.task_manifest,
        manifest_sha256="a" * 64,
        planner_strategy=None,
        scratch=str(tmp_path / "scratch"),
        settings=settings,
    )
    report = TaskCheckReport(
        declaration=declaration,
        request=TaskCheckRequest(
            setup=declaration.request,
            scratch=tmp_path / "scratch",
            output=tmp_path / "check",
            read_only=(),
            settings=settings,
        ),
        job=job,
        sandbox=SandboxProfile(workspace=tmp_path / "scratch", network=False, timeout_seconds=1),
        runtime_read_only_roots=(),
        execution=None,
        result=CompositionResult.failed(
            job,
            "planner_strategy",
            ValueError("PRIVATE_PATH_DETAIL"),
            task=TaskCompositionSummary(
                semantic_fingerprint="b" * 64,
                task_data_path_id="synthetic",
                task_config={
                    "task_description": "Classify small images",
                    "api_key": "PRIVATE_TASK",
                    "forward_contract": {
                        "num_classes": 10,
                        "input_shape": "(B,1,H,W)",
                        "extra": "PRIVATE_FORWARD",
                    },
                },
                dataset_profile={"partition_count": 2, "extra": "PRIVATE_DATASET"},
                primary_metric={
                    "id": "accuracy",
                    "direction": "maximize",
                    "extra": "PRIVATE_METRIC",
                },
                secondary_metrics=[],
                parameter_rules={
                    "rules": {"train_config.epochs": {"exact": 1, "extra": "PRIVATE_RULE"}}
                },
                inference_preflight={"mode": "static_only", "max_batches": 2},
                source_paths={},
                plugins=[],
                code_package_identity=None,
                prompt_renderer_identity=None,
                preflight_estimator_identity={},
                data_analysis_identity=None,
                task_health_declaration="disabled",
            ),
        ),
        limitations=("No hardware check",),
    )
    payload = report.model_dump_json().encode()
    snapshot[0].write_bytes(payload)
    captured = install_gateway(monkeypatch)
    receipt = review_snapshot(operation((snapshot[0], payload), tmp_path, "review"))
    assert receipt.outcome == "reviewed" and receipt.deterministic_outcome == "failed"
    assert '"deterministic_outcome": "failed"' in captured["user"]
    assert "PRIVATE_PATH_DETAIL" not in captured["user"]
    assert "No hardware check" in captured["user"]
    packet = json.loads(captured["user"])
    assert packet["task"]["primary_metric"]["id"] == "accuracy"
    assert packet["task"]["parameter_rules"] == [{"path": "train_config.epochs", "exact": 1}]
    assert packet["forward_contract"]["num_classes"] == 10
    assert "PRIVATE_" not in captured["user"]
    assert "<strong>failed</strong>" in (tmp_path / "review/index.html").read_text()


def test_skip_cold_process_has_no_provider_task_or_credential_access(snapshot, tmp_path):
    request = operation(snapshot, tmp_path)
    path = tmp_path / "skip.json"
    path.write_text(request.model_dump_json())
    script = """
import importlib.abc
import os
import runpy
import sys
class Reject(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        forbidden = ('agent.llm_bridge', 'dotenv', 'openai', 'workflows.task_composition',
                     'workflows.run_one_iteration', 'workflows.model_exploration')
        if any(fullname == item or fullname.startswith(item + '.') for item in forbidden):
            raise AssertionError('Effectful import: ' + fullname)
sys.meta_path.insert(0, Reject())
original = type(os.environ).__getitem__
def guarded(self, key):
    if key in ('OPENAI_API_KEY', 'GEMINI_API_KEY', 'DEEPSEEK_API_KEY'):
        raise AssertionError('Credential access')
    return original(self, key)
type(os.environ).__getitem__ = guarded
sys.argv = ['review', '--request', sys.argv[1]]
runpy.run_module('tools.setup_review.review', run_name='__main__')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "Setup review skipped" in result.stdout
    assert not (tmp_path / "run").exists()


def test_partial_publication_never_overwrites_concurrent_page(snapshot, tmp_path, monkeypatch):
    import tools.setup_review.semantic_review as review

    original = review.publish_bytes_write_once

    def publish(path, payload):
        if Path(path).name == "index.html":
            Path(path).write_text("existing concurrent content")
        return original(path, payload)

    monkeypatch.setattr(review, "publish_bytes_write_once", publish)
    with pytest.raises(FileExistsError):
        review_snapshot(operation(snapshot, tmp_path))
    assert (tmp_path / "review/index.html").read_text() == "existing concurrent content"
    assert (tmp_path / "review/receipt.json").is_file()
