"""C13 — an operator stop must terminate the CHAIN LOOP, not one child.

The confirmed defect (V19 wave-1 stop, design doc §15): killing the
iteration Python ended that iteration, and `run_chain` then walked
straight on and respawned iteration 2 with `--start_iteration 2`.

Every test here drives the REAL `run_chain` loop from
`_chain_common.sh` in a bash subprocess, with `submit_iteration`
replaced by a stub that records which iterations were entered. Nothing
is launched, no GPU or Python iteration is involved, so the stop
guarantee is proved directly rather than described.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
COMMON = REPO_ROOT / "sdsc_submission_scripts" / "_chain_common.sh"

#: A stub iteration that appends its number to a trace file. `STUB_BEHAVIOUR`
#: lets a single test decide what the "child" does on a chosen iteration.
STUB = r"""
submit_iteration() {
    echo "$1" >> "$TRACE"
    if [ -n "${STOP_AFTER_ITER:-}" ] && [ "$1" = "$STOP_AFTER_ITER" ]; then
        touch "$(chain_stop_file)"
    fi
    if [ -n "${FAIL_ITER:-}" ] && [ "$1" = "$FAIL_ITER" ]; then
        return "${FAIL_CODE:-1}"
    fi
    return 0
}
"""


def _run_chain(tmp_path: Path, *, iterations: int = 4, **env) -> tuple[int, list[int], Path]:
    """Drive the real loop; return (exit code, iterations entered, workspace)."""
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    trace = tmp_path / "trace"
    # Everything is set AFTER the source: `_chain_common.sh` assigns the
    # chain defaults at load time, so anything set before it is wiped.
    script = f"""
set -u
source '{COMMON}'
WORKSPACE='{workspace}'
NUM_ITERATIONS={iterations}
START_ITER=1
DRY_RUN=0
RUN_NAME='c13_test'
TRACE='{trace}'
build_source_paths() {{ SOURCE_PATHS=(); }}
build_app_args() {{ APP_ARGS=(); }}
{STUB}
run_chain
exit $?
"""
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env=dict(os.environ, **{k: str(v) for k, v in env.items()}),
    )
    entered = [int(line) for line in trace.read_text().split()] if trace.exists() else []
    return result.returncode, entered, workspace


def _stop_record(workspace: Path) -> dict:
    path = workspace / "chain_stopped.json"
    assert path.is_file(), "an operator stop must leave an explicit state record"
    return json.loads(path.read_text())


class TestStopFile:
    def test_a_stop_file_present_up_front_starts_nothing(self, tmp_path):
        (tmp_path / "ws").mkdir()
        (tmp_path / "ws" / "STOP").touch()
        code, entered, ws = _run_chain(tmp_path)
        assert entered == []
        assert code == 99
        assert _stop_record(ws)["reason"] == "operator_stop_requested"

    def test_a_stop_mid_chain_ends_the_loop_with_no_respawn(self, tmp_path):
        """The defect, asserted directly: iteration 3 must never start."""
        code, entered, ws = _run_chain(tmp_path, iterations=4, STOP_AFTER_ITER=2)
        assert entered == [1, 2], "the loop respawned an iteration after the stop"
        assert code == 99
        record = _stop_record(ws)
        assert record["stopped_before_iteration"] == 3
        assert record["respawn"] is False

    def test_the_stop_file_location_is_configurable(self, tmp_path):
        elsewhere = tmp_path / "elsewhere.stop"
        elsewhere.touch()
        code, entered, _ = _run_chain(tmp_path, CHAIN_STOP_FILE=str(elsewhere))
        assert entered == []
        assert code == 99

    def test_no_stop_runs_every_iteration_and_writes_no_record(self, tmp_path):
        code, entered, ws = _run_chain(tmp_path, iterations=4)
        assert entered == [1, 2, 3, 4]
        assert code == 0
        assert not (ws / "chain_stopped.json").exists()


class TestSignalTerminatedIteration:
    """The wave-1 case: the iteration child is killed from outside."""

    @pytest.mark.parametrize("signal_code,signal_number", [(137, 9), (143, 15), (130, 2)])
    def test_a_signalled_child_stops_the_loop(self, tmp_path, signal_code, signal_number):
        code, entered, ws = _run_chain(tmp_path, iterations=4, FAIL_ITER=2, FAIL_CODE=signal_code)
        assert entered == [1, 2], "a signal-killed iteration must not be followed by another"
        assert code == signal_code
        record = _stop_record(ws)
        assert record["reason"] == "iteration_terminated_by_signal"
        assert record["signal"] == f"child_signal_{signal_number}"
        assert record["respawn"] is False

    def test_an_ordinary_failure_keeps_the_frozen_continuation_behaviour(self, tmp_path):
        """No-respawn is scoped to an OPERATOR-DIRECTED stop. A plain
        non-zero iteration is an in-chain outcome and must not silently
        become a new stop condition."""
        code, entered, ws = _run_chain(tmp_path, iterations=4, FAIL_ITER=2, FAIL_CODE=1)
        assert entered == [1, 2, 3, 4]
        assert code == 0
        assert not (ws / "chain_stopped.json").exists()


class TestStopRecordContent:
    def test_the_record_identifies_the_run_and_is_valid_json(self, tmp_path):
        _, _, ws = _run_chain(tmp_path, iterations=3, STOP_AFTER_ITER=1)
        record = _stop_record(ws)
        assert record["stopped"] is True
        assert record["run_name"] == "c13_test"
        assert record["workspace"] == str(ws)
        assert record["iterations_planned"] == 3
        assert isinstance(record["chain_pid"], int)
        assert record["stopped_at"].endswith("Z")
        assert record["detail"]


class TestQueueRunnerStopSemantics:
    RUNNER = REPO_ROOT / "sdsc_submission_scripts" / "v19_queue_runner.sh"

    def _sourced(self, snippet: str, **env) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", "-c", f"V19_QUEUE_NO_MAIN=1 source '{self.RUNNER}'; {snippet}"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env=dict(os.environ, **{k: str(v) for k, v in env.items()}),
        )

    def test_the_queue_sees_a_stop_file(self, tmp_path):
        stop = tmp_path / "STOP"
        result = self._sourced(
            "queue_stop_requested && echo STOP || echo GO", QUEUE_STOP_FILE=str(stop)
        )
        assert result.stdout.strip() == "GO"
        stop.touch()
        result = self._sourced(
            "queue_stop_requested && echo STOP || echo GO", QUEUE_STOP_FILE=str(stop)
        )
        assert result.stdout.strip() == "STOP"

    def test_the_queue_stop_record_is_valid_json(self, tmp_path):
        state = tmp_path / "wave_state.jsonl"
        # LOGF is pinned for the same reason WAVE_STATE always was: this
        # test calls the helper directly, bypassing main(), so nothing has
        # created the directory the default resolves into. In production
        # `log()` is unreachable before campaign admission creates
        # `queue_state/` — asserted by
        # test_campaign_admission.py::test_no_log_call_precedes_admission.
        result = self._sourced(
            f"WAVE_STATE='{state}'; LOGF='{tmp_path}/queue_runner.log'; "
            "record_queue_stop operator_stop_requested 2 'because'",
            WS_ROOT=str(tmp_path),
        )
        assert result.returncode == 0
        record = json.loads(state.read_text().strip())
        assert record["queue_stopped"] is True
        assert record["reason"] == "operator_stop_requested"
        assert record["wave"] == "2"
        assert record["respawn"] is False

    def test_the_wave_wait_is_bounded(self):
        """A wave that never finishes must not hang the queue forever."""
        result = self._sourced("echo $WAVE_WALL_SECONDS")
        assert int(result.stdout.strip()) > 0

    def test_the_wall_cap_is_configurable_and_stops_rather_than_kills(self, tmp_path):
        state = tmp_path / "wave_state.jsonl"
        result = self._sourced(
            f"""
            set +e   # _chain_common.sh sets errexit; we want the return code
            WAVE_STATE='{state}'
            LOGF='{tmp_path}/queue_runner.log'   # see the note above
            chain_screen_alive() {{ return 0; }}   # a chain that never finishes
            sleep() {{ return 0; }}                 # make the bounded wait instant
            wait_and_record 1 start never_finishes; echo "rc=$?"
            """,
            WS_ROOT=str(tmp_path),
            WAVE_WALL_SECONDS=120,
        )
        assert "rc=1" in result.stdout
        record = json.loads(state.read_text().strip().splitlines()[0])
        assert record["reason"] == "wave_wall_cap_exceeded"
        # non-destructive: the cap reports, it does not kill the chains
        assert "kill" not in record["detail"].lower()

    def test_a_chain_stop_exit_code_is_recognised(self):
        result = self._sourced("echo $CHAIN_STOP_EXIT_CODE")
        assert result.stdout.strip() == "99"
