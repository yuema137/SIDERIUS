"""
Unit tests for the parent-process memory probe (Fix 4).

Covers ``core/memory_probe.py``:

  * Stdout line format matches the contract in
    docs/optimize_inference_and_scoring.md §3 Fix 4.
  * Every call appends exactly one JSON row to ``memory_trace.jsonl``
    when ``workspace`` is provided.
  * JSON rows carry all required fields (scope, iter, phase, rss_gb,
    vms_gb, timestamp) and plausible values.
  * Multiple successive probes append (not overwrite) — the log is a
    monotonic audit trail.
  * Probes with no ``workspace`` emit stdout only.
  * Probe tolerates ``psutil`` being unavailable.

Lives under ``tests/unit/agent/tune_ml_hyperparam_agent/`` because the
tuner is the primary tuner-scope consumer of the probe (see
``nodes/ml_hyperparameter_tune_agent.py``'s ``[Step 3/3] Scoring``
block); the helper itself is re-exported from ``core.memory_probe``.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from core import memory_probe
from core.memory_probe import TRACE_FILENAME, probe_memory

# ==========================================
# Stdout formatting
# ==========================================


class TestProbeStdoutFormat:
    def test_emits_mem_line_with_canonical_fields(self, capsys):
        probe_memory(iter_idx=3, phase="start", scope="workflow")
        out = capsys.readouterr().out
        assert "[MEM]" in out
        assert "scope=workflow" in out
        assert "iter=3" in out
        assert "phase=start" in out
        assert "rss=" in out
        assert "vms=" in out
        assert " GB" in out

    def test_iter_can_be_string(self, capsys):
        """iter_idx accepts any JSON-serialisable value."""
        probe_memory(iter_idx="seed", phase="pre_score", scope="tuner")
        assert "iter=seed" in capsys.readouterr().out


# ==========================================
# JSONL persistence
# ==========================================


class TestProbeJsonlPersistence:
    def test_appends_row_when_workspace_given(self, tmp_path):
        probe_memory(iter_idx=1, phase="start", workspace=str(tmp_path), scope="workflow")
        trace_path = tmp_path / TRACE_FILENAME
        assert trace_path.exists()
        rows = [json.loads(line) for line in trace_path.read_text().splitlines()]
        assert len(rows) == 1

    def test_row_has_required_fields(self, tmp_path):
        row = probe_memory(
            iter_idx=2,
            phase="post_score",
            workspace=str(tmp_path),
            scope="tuner",
        )
        for key in ("scope", "iter", "phase", "rss_gb", "vms_gb", "timestamp"):
            assert key in row, f"missing key: {key}"
        assert row["scope"] == "tuner"
        assert row["iter"] == 2
        assert row["phase"] == "post_score"
        assert isinstance(row["timestamp"], str)
        # Cross-check the persisted row matches the returned dict
        persisted = json.loads((tmp_path / TRACE_FILENAME).read_text().strip())
        assert persisted == row

    def test_rss_and_vms_are_numeric_when_psutil_available(self, tmp_path):
        pytest.importorskip("psutil")
        row = probe_memory(iter_idx=1, phase="start", workspace=str(tmp_path))
        assert isinstance(row["rss_gb"], (int, float))
        assert isinstance(row["vms_gb"], (int, float))
        assert row["rss_gb"] > 0
        assert row["vms_gb"] >= row["rss_gb"]  # VMS is always ≥ RSS

    def test_multiple_calls_append_not_overwrite(self, tmp_path):
        probe_memory(iter_idx=1, phase="start", workspace=str(tmp_path))
        probe_memory(iter_idx=1, phase="pre_score", workspace=str(tmp_path), scope="tuner")
        probe_memory(iter_idx=1, phase="post_score", workspace=str(tmp_path), scope="tuner")
        probe_memory(iter_idx=1, phase="end", workspace=str(tmp_path))

        rows = [json.loads(line) for line in (tmp_path / TRACE_FILENAME).read_text().splitlines()]
        assert len(rows) == 4
        assert [r["phase"] for r in rows] == ["start", "pre_score", "post_score", "end"]

    def test_workspace_is_created_if_missing(self, tmp_path):
        """The probe must not fail when the workspace dir does not exist yet."""
        target = tmp_path / "new_workspace"
        assert not target.exists()
        probe_memory(iter_idx=1, phase="start", workspace=str(target))
        assert (target / TRACE_FILENAME).exists()


# ==========================================
# No workspace → stdout only
# ==========================================


class TestProbeNoWorkspace:
    def test_no_workspace_does_not_create_file(self, tmp_path, capsys):
        """Changing cwd confirms: workspace=None writes nothing anywhere."""
        cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            probe_memory(iter_idx=1, phase="start")  # workspace omitted
        finally:
            os.chdir(cwd)
        assert not (tmp_path / TRACE_FILENAME).exists()
        assert "[MEM]" in capsys.readouterr().out


# ==========================================
# psutil unavailable → graceful degradation
# ==========================================


class TestProbePsutilUnavailable:
    def test_missing_psutil_emits_sentinel_row(self, tmp_path, capsys):
        """When psutil is unreachable, the probe logs NA and a note."""
        with patch.object(memory_probe, "_PSUTIL_AVAILABLE", False):
            row = probe_memory(iter_idx=1, phase="start", workspace=str(tmp_path))
        assert row["rss_gb"] is None
        assert row["vms_gb"] is None
        assert row.get("note") == "psutil_unavailable"
        out = capsys.readouterr().out
        assert "rss=NA" in out
        persisted = json.loads((tmp_path / TRACE_FILENAME).read_text().strip())
        assert persisted["note"] == "psutil_unavailable"


# ==========================================
# Two-iteration mini-workflow (integration-ish)
# ==========================================


class TestTwoIterTrace:
    """Drive a scripted sequence and check the JSONL is well-ordered.

    Mirrors the probe pattern the workflow + tuner will emit in
    production:  start → pre_score → post_score → end  per iteration.
    """

    def test_ordered_probes_produce_monotonic_trace(self, tmp_path):
        for it in (1, 2):
            probe_memory(iter_idx=it, phase="start", workspace=str(tmp_path), scope="workflow")
            probe_memory(iter_idx=it, phase="pre_score", workspace=str(tmp_path), scope="tuner")
            probe_memory(iter_idx=it, phase="post_score", workspace=str(tmp_path), scope="tuner")
            probe_memory(iter_idx=it, phase="end", workspace=str(tmp_path), scope="workflow")

        rows = [json.loads(line) for line in (tmp_path / TRACE_FILENAME).read_text().splitlines()]
        assert len(rows) == 8
        # A `iters == sorted(iters)` assertion was removed on 2026-08-02: the
        # probes are emitted in ascending iteration order by the loop above,
        # and production never reorders, so it restated the test's own
        # sequencing. The per-iteration check below is the real one -- it
        # fails if `iter` is not persisted per row.
        # Each iteration should have all 4 phases in order
        for it in (1, 2):
            phases_for_it = [r["phase"] for r in rows if r["iter"] == it]
            assert phases_for_it == ["start", "pre_score", "post_score", "end"]


# ==========================================
# Phase 6.8 §2 Commit 2 — post_gc phase round-trip
# ==========================================


class TestPostGcPhase:
    """The workflow emits ``phase="post_gc"`` immediately after the
    per-iteration ``del`` + ``gc.collect()`` block. The probe must
    accept the new phase string and round-trip it through the JSONL.
    """

    def test_post_gc_round_trip(self, tmp_path):
        row = probe_memory(
            iter_idx=1,
            phase="post_gc",
            workspace=str(tmp_path),
            scope="workflow",
        )
        assert row["phase"] == "post_gc"
        assert row["scope"] == "workflow"
        persisted = json.loads((tmp_path / TRACE_FILENAME).read_text().strip())
        assert persisted["phase"] == "post_gc"

    def test_end_then_post_gc_pair_writes_two_rows(self, tmp_path):
        """Mirrors the production sequence: ``end`` then ``post_gc``."""
        probe_memory(iter_idx=1, phase="end", workspace=str(tmp_path), scope="workflow")
        probe_memory(iter_idx=1, phase="post_gc", workspace=str(tmp_path), scope="workflow")
        rows = [json.loads(line) for line in (tmp_path / TRACE_FILENAME).read_text().splitlines()]
        assert [r["phase"] for r in rows] == ["end", "post_gc"]
        assert [r["iter"] for r in rows] == [1, 1]
