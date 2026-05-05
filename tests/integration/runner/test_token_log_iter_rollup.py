"""Integration tests for Phase 1 Commit 4 — runner integration & rollup.

Per §8 Commit 4 of ``docs/audit_and_optimize_token_usage_and_growth.md``,
this file exercises three contracts:

1. **Run-ID format** — ``_generate_run_id`` produces the documented
   ``{run_name}-{utc_ts}-{pid}`` shape (§1.4.1). The string is the
   immutable owner of ``token_usage.jsonl`` for the chain's lifetime,
   so its shape is part of the public contract — the v12 baseline
   report parses it.
2. **Per-iter rollup** — ``_emit_token_iter_rollup`` reads a real-shape
   ``token_usage.jsonl``, filters rows by ``iter``, groups totals by
   ``label`` prefix, prints one ``[TOKEN_ITER]`` line, and carries the
   cumulative total across calls (§1.6).
3. **Subprocess fail-fast** — when a chain runner is pointed at a
   workspace whose ``token_usage.jsonl`` is owned by a *different*
   ``run_id``, the bridge's first-row check (§1.4.1) raises
   :class:`LLMBridgeContextError`, the runner's top-level handler
   translates it into ``sys.exit(2)``, and ``[FATAL]`` lands on
   stderr (§1.4.2). Q4 confirmed: real subprocess, not monkey-patch.
"""
from __future__ import annotations

import io
import json
import re
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from run_exploration_adaptive import (
    _emit_token_iter_rollup,
    _generate_run_id,
)


# ---------------------------------------------------------------------------
# 1. Run-ID format
# ---------------------------------------------------------------------------

def test_generate_run_id_matches_documented_format():
    """``{run_name}-{utc_ts}-{pid}`` with utc_ts as YYYYMMDDTHHMMSS."""
    rid = _generate_run_id("explore_v12_0504")
    # The pid is the *current* process id — match any positive integer.
    assert re.match(r"^explore_v12_0504-\d{8}T\d{6}-\d+$", rid), rid


def test_generate_run_id_different_run_names_produce_distinct_ids():
    """Two different run names produce two different run_ids."""
    a = _generate_run_id("foo")
    b = _generate_run_id("bar")
    # Even when called within the same UTC second, the run_name prefix
    # differs, so the strings cannot collide.
    assert a != b
    assert a.startswith("foo-")
    assert b.startswith("bar-")


# ---------------------------------------------------------------------------
# 2. Per-iter rollup emission
# ---------------------------------------------------------------------------

def _seed_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_emit_rollup_aggregates_by_node_prefix(tmp_path):
    """Rows are grouped by ``label.split('.')[0]`` and summed."""
    rows = [
        {"iter": 1, "label": "proposer.comparison", "tokens": {"total": 100}},
        {"iter": 1, "label": "proposer.proposing",  "tokens": {"total": 200}},
        {"iter": 1, "label": "tuner.planner",       "tokens": {"total": 50}},
        {"iter": 1, "label": "interpretation.synthesis",
                                                    "tokens": {"total": 30}},
        # _iter_flush is the synthetic boundary marker — must be skipped.
        {"iter": 1, "label": "_iter_flush",          "tokens": {"total": 0}},
        # iter=2 must not bleed into the iter=1 rollup.
        {"iter": 2, "label": "proposer.comparison", "tokens": {"total": 999}},
    ]
    _seed_jsonl(tmp_path / "token_usage.jsonl", rows)

    buf = io.StringIO()
    with redirect_stdout(buf):
        new_total = _emit_token_iter_rollup(
            workspace=str(tmp_path), iteration=1, cumulative_total_in=0,
        )
    out = buf.getvalue()

    assert new_total == 100 + 200 + 50 + 30, new_total
    assert "[TOKEN_ITER] iter=01" in out
    assert "calls=4" in out
    assert "total_tok=380" in out
    # Per-node sums (sorted alphabetically by node key in the emitter):
    assert "interpretation=30" in out
    assert "proposer=300" in out
    assert "tuner=50" in out
    assert "cumulative_total=380" in out


def test_emit_rollup_handles_missing_file(tmp_path):
    """No ``token_usage.jsonl`` → no error, cumulative is unchanged."""
    new_total = _emit_token_iter_rollup(
        workspace=str(tmp_path), iteration=1, cumulative_total_in=42,
    )
    assert new_total == 42


def test_emit_rollup_carries_cumulative_across_calls(tmp_path):
    """Two iters → cumulative tracks the running sum."""
    _seed_jsonl(tmp_path / "token_usage.jsonl", [
        {"iter": 1, "label": "proposer.x", "tokens": {"total": 50}},
        {"iter": 2, "label": "proposer.y", "tokens": {"total": 70}},
    ])
    buf = io.StringIO()
    with redirect_stdout(buf):
        after_1 = _emit_token_iter_rollup(
            workspace=str(tmp_path), iteration=1, cumulative_total_in=1000,
        )
        after_2 = _emit_token_iter_rollup(
            workspace=str(tmp_path), iteration=2, cumulative_total_in=after_1,
        )
    assert after_1 == 1050
    assert after_2 == 1120
    out = buf.getvalue()
    # The two emitted lines must mention each cumulative checkpoint.
    assert "cumulative_total=1050" in out
    assert "cumulative_total=1120" in out


def test_emit_rollup_skips_malformed_jsonl_rows(tmp_path):
    """A garbage line in the middle of the file does not crash the rollup."""
    path = tmp_path / "token_usage.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(
            {"iter": 1, "label": "proposer.x", "tokens": {"total": 10}}
        ) + "\n")
        f.write("THIS IS NOT JSON\n")
        f.write(json.dumps(
            {"iter": 1, "label": "proposer.y", "tokens": {"total": 20}}
        ) + "\n")
    new_total = _emit_token_iter_rollup(
        workspace=str(tmp_path), iteration=1, cumulative_total_in=0,
    )
    assert new_total == 30  # malformed row skipped, both valid ones counted


# ---------------------------------------------------------------------------
# 3. Subprocess negative test — Q4: real subprocess, real exit code
# ---------------------------------------------------------------------------

_HARNESS = Path(__file__).resolve().parent / "_runid_mismatch_harness.py"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_VENV_PYTHON = _REPO_ROOT / ".venv" / "bin" / "python"


@pytest.mark.skipif(
    not _VENV_PYTHON.exists(),
    reason="project virtualenv not found at .venv/bin/python",
)
def test_runner_aborts_on_runid_mismatch(tmp_path):
    """End-to-end §1.4.2 contract — bridge raises → handler exits with 2."""
    # Pre-seed token_usage.jsonl with an *earlier* run_id. The bridge's
    # first-row check should refuse to write into a file already owned
    # by someone else.
    seeded_row = {
        "ts": "2026-05-04T15:00:00.000Z",
        "run_name": "PRIOR_RUN",
        "iter": 1,
        "label": "proposer.comparison",
        "model": "gpt-4o-mini",
        "provider": "openai",
        "tokens": {"prompt": 1, "completion": 0, "total": 1},
        "chars": {"system": 0, "user": 0, "total": 0},
        "components": {},
        "extra": {},
        "run_id": "PRIOR-RUN-ID-DIFFERENT",
    }
    _seed_jsonl(tmp_path / "token_usage.jsonl", [seeded_row])

    proc = subprocess.run(
        [str(_VENV_PYTHON), str(_HARNESS), str(tmp_path), "FRESH-RUN-ID"],
        capture_output=True, text=True, timeout=30,
    )

    assert proc.returncode == 2, (
        f"expected exit code 2 (LLMBridgeContextError), got {proc.returncode}\n"
        f"--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}\n"
    )
    assert "[FATAL]" in proc.stderr
    assert "LLMBridgeContextError" in proc.stderr
    assert "aborting run to prevent telemetry corruption" in proc.stderr
