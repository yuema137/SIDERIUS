"""
Deterministic tests for the calibration-runner stop/status fixes
(R-1..R-4, PR 3 audit §13.3). No LLM calls — run_order takes a stubbed
run_sample_fn; the wrapper test uses a stub interpreter.

States covered: completed, protocol_stop (threshold + version drift),
budget_stop (with in-flight abort marker), technical_failure,
external_interruption; always-written run records; ledger precheck;
wrapper exit-status propagation.
"""

import json
import stat
import subprocess
from pathlib import Path

import pytest

from scripts.pr3_l2_calibration.runner import (
    EXIT_CODES,
    OUTCOME_BUDGET_STOP,
    OUTCOME_COMPLETED,
    OUTCOME_EXTERNAL_INTERRUPTION,
    OUTCOME_PROTOCOL_STOP,
    OUTCOME_TECHNICAL_FAILURE,
    BudgetExceeded,
    Ledger,
    VersionDrift,
    mark_aborted_incomplete,
    run_order,
    write_run_records,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

ORDER = [
    {"idx": 0, "scenario": "S1", "arm": "C", "rep": 1},
    {"idx": 1, "scenario": "S1", "arm": "T", "rep": 1},
    {"idx": 2, "scenario": "S1", "arm": "C", "rep": 2},
    {"idx": 3, "scenario": "S1", "arm": "T", "rep": 2},
]


def _ledger(tmp_path, max_calls=100, dollar_cap=100.0):
    return Ledger(max_calls, dollar_cap, tmp_path / "ledger.jsonl")


def _meta(entry, terminal_error=None):
    return {
        "sample_id": f"{entry['scenario']}_{entry['arm']}_{entry['rep']}",
        "terminal_error": terminal_error,
    }


class TestRunOrderStopConditions:
    def test_completed_runs_all_samples(self, tmp_path):
        executed = []

        def fn(entry, run_dir, ledger, first_gate_done):
            executed.append(entry["idx"])
            return _meta(entry)

        outcome, _detail, results = run_order(ORDER, tmp_path, _ledger(tmp_path), 4, fn)
        assert outcome == OUTCOME_COMPLETED
        assert executed == [0, 1, 2, 3]
        assert len(results) == 4

    def test_protocol_stop_fires_at_boundary_and_blocks_next_sample(self, tmp_path):
        """The stop is evaluated immediately after every completed sample:
        with threshold 1 and a terminal first sample, samples 2-4 are NEVER
        launched."""
        executed = []

        def fn(entry, run_dir, ledger, first_gate_done):
            executed.append(entry["idx"])
            return _meta(entry, terminal_error="RuntimeError: citation")

        outcome, detail, _results = run_order(ORDER, tmp_path, _ledger(tmp_path), 1, fn)
        assert outcome == OUTCOME_PROTOCOL_STOP
        assert executed == [0]
        assert "1 >= 1" in detail

    def test_protocol_stop_counts_across_samples(self, tmp_path):
        """Threshold 2 with terminal samples at idx 0 and 2 → stops right
        after idx 2; idx 3 never launches."""
        executed = []

        def fn(entry, run_dir, ledger, first_gate_done):
            executed.append(entry["idx"])
            terminal = "err" if entry["idx"] in (0, 2) else None
            return _meta(entry, terminal_error=terminal)

        outcome, _, results = run_order(ORDER, tmp_path, _ledger(tmp_path), 2, fn)
        assert outcome == OUTCOME_PROTOCOL_STOP
        assert executed == [0, 1, 2]
        assert len(results) == 3

    def test_budget_stop_marks_inflight_sample(self, tmp_path):
        """BudgetExceeded mid-sample → explicit outcome + aborted_incomplete
        marker in the in-flight sample dir; completed results retained."""

        def fn(entry, run_dir, ledger, first_gate_done):
            sid = f"{entry['scenario']}_{entry['arm']}_{entry['rep']}"
            (run_dir / sid).mkdir(parents=True, exist_ok=True)
            if entry["idx"] == 1:
                raise BudgetExceeded("call cap reached: 24/24")
            return _meta(entry)

        outcome, detail, results = run_order(ORDER, tmp_path, _ledger(tmp_path), 4, fn)
        assert outcome == OUTCOME_BUDGET_STOP
        assert "24/24" in detail
        assert len(results) == 1
        marker = tmp_path / "S1_T_1" / "aborted_incomplete.json"
        assert marker.exists()
        assert "BudgetExceeded" in json.loads(marker.read_text())["reason"]

    def test_version_drift_is_protocol_stop(self, tmp_path):
        def fn(entry, run_dir, ledger, first_gate_done):
            raise VersionDrift("pinned='a' got='b'")

        outcome, detail, _ = run_order(ORDER, tmp_path, _ledger(tmp_path), 4, fn)
        assert outcome == OUTCOME_PROTOCOL_STOP
        assert "pinned" in detail

    def test_technical_failure_marks_inflight(self, tmp_path):
        def fn(entry, run_dir, ledger, first_gate_done):
            sid = f"{entry['scenario']}_{entry['arm']}_{entry['rep']}"
            (run_dir / sid).mkdir(parents=True, exist_ok=True)
            raise ValueError("boom")

        outcome, detail, results = run_order(ORDER, tmp_path, _ledger(tmp_path), 4, fn)
        assert outcome == OUTCOME_TECHNICAL_FAILURE
        assert detail == "ValueError: boom"
        assert results == []
        assert (tmp_path / "S1_C_1" / "aborted_incomplete.json").exists()

    def test_external_interruption(self, tmp_path):
        def fn(entry, run_dir, ledger, first_gate_done):
            raise KeyboardInterrupt()

        outcome, _detail, _ = run_order(ORDER, tmp_path, _ledger(tmp_path), 4, fn)
        assert outcome == OUTCOME_EXTERNAL_INTERRUPTION


class TestAbortMarker:
    def test_noop_when_sample_finalized(self, tmp_path):
        d = tmp_path / "S1_C_1"
        d.mkdir()
        (d / "sample_meta.json").write_text("{}")
        mark_aborted_incomplete(d, "reason")
        assert not (d / "aborted_incomplete.json").exists()

    def test_noop_when_no_sample_dir(self, tmp_path):
        mark_aborted_incomplete(None, "reason")
        mark_aborted_incomplete(tmp_path / "missing", "reason")  # must not raise


class TestRunRecords:
    def test_records_always_written_with_outcome(self, tmp_path):
        ledger = _ledger(tmp_path)
        results = [{"sample_id": "S1_C_1", "terminal_error": "err"}]
        write_run_records(tmp_path, ledger, OUTCOME_PROTOCOL_STOP, "why", results)

        summary = json.loads((tmp_path / "run_summary.json").read_text())
        status = json.loads((tmp_path / "run_status.json").read_text())
        assert summary["outcome"] == OUTCOME_PROTOCOL_STOP
        assert status["outcome"] == OUTCOME_PROTOCOL_STOP
        assert status["detail"] == "why"
        assert status["exit_code"] == EXIT_CODES[OUTCOME_PROTOCOL_STOP]
        assert status["samples_completed"] == 1
        assert status["terminal_failures"] == 1

    def test_exit_codes_distinguish_all_states(self):
        assert set(EXIT_CODES) == {
            OUTCOME_COMPLETED,
            OUTCOME_PROTOCOL_STOP,
            OUTCOME_BUDGET_STOP,
            OUTCOME_TECHNICAL_FAILURE,
            OUTCOME_EXTERNAL_INTERRUPTION,
        }
        assert len(set(EXIT_CODES.values())) == len(EXIT_CODES)
        assert EXIT_CODES[OUTCOME_COMPLETED] == 0


class TestLedgerPrecheck:
    def test_precheck_blocks_before_the_call(self, tmp_path):
        """The cap is enforced BEFORE each call: with max_calls=1 the first
        record succeeds and the next precheck raises."""
        ledger = Ledger(1, 100.0, tmp_path / "ledger.jsonl")
        ledger.precheck()
        ledger.record({"prompt_tokens": 10, "completion_tokens": 1, "model": "m-1"})
        with pytest.raises(BudgetExceeded, match="call cap"):
            ledger.precheck()


class TestWrapperExitStatus:
    """The launch wrapper must return the runner's exit status verbatim —
    trailing tee/logging cannot mask a failure (the rev-2/rev-3 defect)."""

    WRAPPER = REPO_ROOT / "scripts" / "pr3_l2_calibration" / "launch_pilot.sh"

    def _stub_python(self, tmp_path, exit_code):
        stub = tmp_path / "stub_python"
        stub.write_text(f'#!/bin/sh\necho "stub-runner-output"\nexit {exit_code}\n')
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
        return stub

    def _run(self, tmp_path, exit_code):
        log = tmp_path / "pilot.log"
        proc = subprocess.run(
            [str(self.WRAPPER), str(log), "--run_id", "x"],
            env={
                "PATH": "/usr/bin:/bin",
                "PILOT_PYTHON": str(self._stub_python(tmp_path, exit_code)),
            },
            capture_output=True,
            text=True,
            cwd=str(tmp_path),  # cwd-independence: wrapper resolves its own repo root
        )
        return proc, log

    def test_nonzero_exit_propagates(self, tmp_path):
        proc, log = self._run(tmp_path, 7)
        assert proc.returncode == 7
        assert "stub-runner-output" in log.read_text()

    def test_zero_exit_propagates(self, tmp_path):
        proc, _ = self._run(tmp_path, 0)
        assert proc.returncode == 0

    def test_missing_log_argument_is_usage_error(self, tmp_path):
        proc = subprocess.run(
            [str(self.WRAPPER)],
            env={"PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 2
        assert "usage" in proc.stderr
