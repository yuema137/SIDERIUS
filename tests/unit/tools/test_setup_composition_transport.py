"""Fixed-path task-check transport refuses special files and stale identities."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from tools.setup_review.composition_models import (
    CHILD_RESULT_NAME,
    CompositionJob,
    CompositionResult,
    TaskCheckSettings,
)
from tools.setup_review.composition_transport import manifest_digest, read_composition_result


@pytest.fixture
def job(tmp_path):
    manifest = tmp_path / "task.yaml"
    manifest.write_text("synthetic: true\n")
    return CompositionJob(
        manifest=str(manifest),
        manifest_sha256=manifest_digest(str(manifest)),
        planner_strategy="native-timing-v1",
        scratch=str(tmp_path),
        settings=TaskCheckSettings(timeout_seconds=1),
    )


def test_exact_limit_and_explicit_override(job, tmp_path):
    initial = CompositionResult.failed(job, "composition", ValueError("fixture failure"))
    size = len(initial.model_dump_json().encode())
    exact = job.model_copy(
        update={"settings": TaskCheckSettings(timeout_seconds=1, result_max_bytes=size)}
    )
    result = CompositionResult.failed(exact, "composition", ValueError("fixture failure"))
    assert len(result.model_dump_json().encode()) == size
    path = tmp_path / CHILD_RESULT_NAME
    path.write_text(result.model_dump_json())
    assert read_composition_result(exact) == result
    smaller = job.model_copy(
        update={"settings": TaskCheckSettings(timeout_seconds=1, result_max_bytes=size - 1)}
    )
    with pytest.raises(ValueError, match=f"result_max_bytes={size - 1}.*--result-max-bytes"):
        read_composition_result(smaller)
    # An explicit larger setting changes request identity as well as the bound.
    larger = job.model_copy(
        update={"settings": TaskCheckSettings(timeout_seconds=1, result_max_bytes=size + 100)}
    )
    path.write_text(
        CompositionResult.failed(
            larger, "composition", ValueError("fixture failure")
        ).model_dump_json()
    )
    assert read_composition_result(larger).outcome == "failed"


def test_symlink_and_malformed_or_mismatched_results_refuse(job, tmp_path):
    path = tmp_path / CHILD_RESULT_NAME
    path.symlink_to(job.manifest)
    with pytest.raises(OSError):
        read_composition_result(job)
    path.unlink()
    path.write_text("not JSON")
    with pytest.raises(ValueError):
        read_composition_result(job)
    result = CompositionResult.failed(job, "composition", ValueError("fixture"))
    path.write_text(result.model_copy(update={"request_sha256": "0" * 64}).model_dump_json())
    with pytest.raises(ValueError, match="does not match"):
        read_composition_result(job)
    path.unlink()
    path.mkdir()
    with pytest.raises(IsADirectoryError):
        read_composition_result(job)


def test_fifo_refuses_without_waiting_for_a_writer_after_child_deadline(job, tmp_path):
    os.mkfifo(tmp_path / CHILD_RESULT_NAME)
    code = """
import sys
from core.file_identity import FileIdentityError
from tools.setup_review.composition_models import CompositionJob
from tools.setup_review.composition_transport import read_composition_result
try:
    read_composition_result(CompositionJob.model_validate_json(sys.argv[1]))
except FileIdentityError as error:
    assert error.reason == 'not_regular'
else:
    raise AssertionError('FIFO accepted')
"""
    result = subprocess.run(
        [sys.executable, "-c", code, job.model_dump_json()],
        timeout=5,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_result_path_replacement_during_read_refuses(job, tmp_path, monkeypatch):
    from tools.setup_review import composition_transport as transport

    result = CompositionResult.failed(job, "composition", ValueError("fixture"))
    path = tmp_path / CHILD_RESULT_NAME
    path.write_text(result.model_dump_json())
    replacement = tmp_path / "replacement"
    replacement.write_text(result.model_dump_json())
    original = transport.regular_file_snapshot
    calls = 0

    def snapshot(handle):
        nonlocal calls
        calls += 1
        if calls == 2:
            os.replace(replacement, path)
        return original(handle)

    monkeypatch.setattr(transport, "regular_file_snapshot", snapshot)
    with pytest.raises(ValueError, match="changed while being read"):
        read_composition_result(job)


def test_passed_result_requires_task_and_planner_facts(job):
    with pytest.raises(ValueError, match="requires task and planner"):
        CompositionResult(
            request_sha256=job.digest, manifest_sha256=job.manifest_sha256, outcome="passed"
        )
