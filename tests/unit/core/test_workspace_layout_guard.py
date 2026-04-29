"""Unit tests for validate_workspace_layout (Phase 6.8 Commit 11 §3.9).

Validates:
  - Empty / non-existent workspace passes cleanly
  - Legacy pattern 1: {workspace}/*/iteration_001/ → ResumeError
  - Legacy pattern 2: workflow_*.json → ResumeError
  - Legacy pattern 3: memory_trace.jsonl without iter_001/ → ResumeError
  - memory_trace.jsonl WITH iter_001/ (chain workspace) passes cleanly
  - Clean chain layout (iter_001/, iter_002/) passes cleanly
"""
from __future__ import annotations

import os

import pytest

from core.resume import ResumeError, validate_workspace_layout


@pytest.fixture
def ws(tmp_path):
    """Return a fresh temporary workspace directory."""
    d = tmp_path / "workspace"
    d.mkdir()
    return str(d)


def test_nonexistent_workspace_passes(tmp_path):
    validate_workspace_layout(str(tmp_path / "does_not_exist"))


def test_empty_workspace_passes(ws):
    validate_workspace_layout(ws)


def test_clean_chain_layout_passes(ws):
    os.makedirs(os.path.join(ws, "iter_001", "iteration_001", "some_model"))
    os.makedirs(os.path.join(ws, "iter_002", "iteration_001", "some_model"))
    validate_workspace_layout(ws)


def test_legacy_pattern1_iteration_subtree(ws):
    os.makedirs(os.path.join(ws, "some_run", "iteration_001"))
    with pytest.raises(ResumeError, match="Legacy workspace layout"):
        validate_workspace_layout(ws)


def test_legacy_pattern2_workflow_json(ws):
    with open(os.path.join(ws, "workflow_summary.json"), "w") as f:
        f.write("{}")
    with pytest.raises(ResumeError, match="Legacy workspace layout"):
        validate_workspace_layout(ws)


def test_legacy_pattern3_trace_without_iter_001(ws):
    with open(os.path.join(ws, "memory_trace.jsonl"), "w") as f:
        f.write("")
    with pytest.raises(ResumeError, match="Legacy workspace layout"):
        validate_workspace_layout(ws)


def test_trace_with_iter_001_passes(ws):
    """memory_trace.jsonl is NOT legacy if iter_001/ also exists (chain workspace
    that also wrote a trace — perfectly valid)."""
    os.makedirs(os.path.join(ws, "iter_001"))
    with open(os.path.join(ws, "memory_trace.jsonl"), "w") as f:
        f.write("")
    validate_workspace_layout(ws)


def test_error_message_contains_migration_hint(ws):
    os.makedirs(os.path.join(ws, "some_run", "iteration_001"))
    with pytest.raises(ResumeError, match="migrate_workspace"):
        validate_workspace_layout(ws)
