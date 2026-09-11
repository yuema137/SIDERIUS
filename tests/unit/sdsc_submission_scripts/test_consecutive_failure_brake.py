"""Stage 4 / Commit 4.6 — fixture-driven tests for the manifest-based
consecutive-failure brake.

The brake is a Python-side preflight in ``run_one_iteration.main()`` that
scans the workspace's ``iter_NNN/manifest.json`` files in descending iter
order. If the most recent ``max_failed`` iters all carry
``status="failed"``, the chain halts. This file pins the streak-scan
logic against the 6 representative scenarios from the T5 matrix in the
design doc.

The helpers are pure (workspace path + max_failed in; iter list or None
out). No main() integration is exercised here — that's Commit 2's job.

T5 matrix recap:
  1. 3 consecutive failed → halt
  2. 2 failed + most recent completed → continue
  3. 3 failed but most recent no_records → continue (no_records ≠ failed)
  4. mixed failed / no_records / completed → continue
  5. empty workspace → continue
  6. --max_failed_iterations=1 + 1 failed → halt (boundary)

Plus 2 fail-open guards (T7 — the brake must never halt on its own flaky
reads) for missing manifest.json and malformed JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pytest

from workflows.run_one_iteration import (
    _check_consecutive_failure_brake,
    _check_halt_marker,
)


def _write_manifest(workspace: Path, iter_num: int, status: str) -> None:
    """Plant a minimal manifest.json under ``{workspace}/iter_NNN/``.

    Status taxonomy matches ``write_manifest`` in run_one_iteration.py:
    ``completed`` / ``no_records`` / ``failed`` — the only three values
    the production runner ever writes.
    """
    iter_dir = workspace / f"iter_{iter_num:03d}"
    iter_dir.mkdir(parents=True, exist_ok=True)
    (iter_dir / "manifest.json").write_text(
        json.dumps(
            {
                "status": status,
                "iteration_dir": str(iter_dir),
                "output_path": None,
                "model_name": None,
                "best_score": None,
            }
        )
    )


# ---------------------------------------------------------------------
# T5 case 1 — 3 consecutive failed → halt
# ---------------------------------------------------------------------
def test_three_consecutive_failed_trips_brake(tmp_path: Path) -> None:
    for n in (1, 2, 3):
        _write_manifest(tmp_path, n, "failed")
    result = _check_consecutive_failure_brake(str(tmp_path), max_failed=3)
    assert result == [3, 2, 1], (
        "Three consecutive failed iters must trip the brake and return "
        "the failing iter numbers in descending order."
    )


# ---------------------------------------------------------------------
# T5 case 2 — 2 failed + recent completed → continue
# ---------------------------------------------------------------------
def test_recent_completed_breaks_failure_streak(tmp_path: Path) -> None:
    _write_manifest(tmp_path, 1, "failed")
    _write_manifest(tmp_path, 2, "failed")
    _write_manifest(tmp_path, 3, "completed")
    result = _check_consecutive_failure_brake(str(tmp_path), max_failed=3)
    assert result is None, (
        "A single completed iter at the top of the window must break "
        "the streak — operational value of the brake depends on this."
    )


# ---------------------------------------------------------------------
# T5 case 3 — 3 failed but recent no_records → continue
# ---------------------------------------------------------------------
def test_recent_no_records_does_not_count_as_failure(tmp_path: Path) -> None:
    _write_manifest(tmp_path, 1, "failed")
    _write_manifest(tmp_path, 2, "failed")
    _write_manifest(tmp_path, 3, "failed")
    _write_manifest(tmp_path, 4, "no_records")
    result = _check_consecutive_failure_brake(str(tmp_path), max_failed=3)
    assert result is None, (
        "no_records is a graceful 'no model passed gates' signal, not a "
        "failure. It must not trip the brake — chains with iters that "
        "skip cleanly should keep running."
    )


# ---------------------------------------------------------------------
# T5 case 4 — mixed sequence → continue
# ---------------------------------------------------------------------
def test_mixed_statuses_do_not_trip_brake(tmp_path: Path) -> None:
    _write_manifest(tmp_path, 1, "failed")
    _write_manifest(tmp_path, 2, "no_records")
    _write_manifest(tmp_path, 3, "failed")
    _write_manifest(tmp_path, 4, "completed")
    result = _check_consecutive_failure_brake(str(tmp_path), max_failed=3)
    assert result is None, (
        "A streak must be contiguous; interleaved non-failed iters "
        "anywhere in the window must keep the chain alive."
    )


# ---------------------------------------------------------------------
# T5 case 5 — empty workspace → continue
# ---------------------------------------------------------------------
def test_empty_workspace_does_not_trip_brake(tmp_path: Path) -> None:
    result = _check_consecutive_failure_brake(str(tmp_path), max_failed=3)
    assert result is None, (
        "A fresh workspace (no iter dirs yet, e.g. iter 1) must never "
        "trip the brake — there is no history to streak across."
    )


# ---------------------------------------------------------------------
# T5 case 6 — boundary: max_failed=1 + 1 failed → halt
# ---------------------------------------------------------------------
def test_single_failure_with_max_failed_one_trips_brake(tmp_path: Path) -> None:
    _write_manifest(tmp_path, 1, "failed")
    result = _check_consecutive_failure_brake(str(tmp_path), max_failed=1)
    assert result == [1], (
        "When max_failed=1, a single failed iter must trip the brake. "
        "This is the boundary case operators choose for zero-tolerance "
        "chains (e.g., 'halt on any failure')."
    )


# ---------------------------------------------------------------------
# Fail-open guard #1 — missing manifest.json breaks the streak
# ---------------------------------------------------------------------
def test_missing_manifest_treated_as_not_failed(tmp_path: Path) -> None:
    # iter_001 is the streak-breaker: dir exists but manifest.json does not.
    (tmp_path / "iter_001").mkdir()
    _write_manifest(tmp_path, 2, "failed")
    _write_manifest(tmp_path, 3, "failed")
    result = _check_consecutive_failure_brake(str(tmp_path), max_failed=3)
    assert result is None, (
        "Missing manifest.json must be treated as 'not failed' (fail-open). "
        "A safety brake that halts on its own flaky reads is worse than "
        "no brake at all."
    )


# ---------------------------------------------------------------------
# Fail-open guard #2 — malformed JSON breaks the streak
# ---------------------------------------------------------------------
def test_malformed_manifest_treated_as_not_failed(tmp_path: Path) -> None:
    (tmp_path / "iter_001").mkdir()
    (tmp_path / "iter_001" / "manifest.json").write_text("{not valid json")
    _write_manifest(tmp_path, 2, "failed")
    _write_manifest(tmp_path, 3, "failed")
    result = _check_consecutive_failure_brake(str(tmp_path), max_failed=3)
    assert result is None, (
        "A JSON decode error must break the streak the same way a "
        "missing file does — both are I/O-level signals that the brake "
        "cannot trust its read."
    )


# ---------------------------------------------------------------------
# Halt-marker helper — present / absent
# ---------------------------------------------------------------------
def test_halt_marker_absent(tmp_path: Path) -> None:
    assert _check_halt_marker(str(tmp_path)) is False


def test_halt_marker_present(tmp_path: Path) -> None:
    (tmp_path / ".chain_halted").write_text("halted")
    assert _check_halt_marker(str(tmp_path)) is True
