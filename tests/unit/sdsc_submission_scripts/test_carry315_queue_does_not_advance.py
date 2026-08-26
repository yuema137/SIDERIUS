"""Carry-home witness (#315) — a failed chain must not advance the queue.

F-SCANB-1's damage has two halves. The chain half — a chain whose iterations
failed must not exit 0 — is witnessed by
``test_failure_honesty_chain_exit_status.py``. **This is the other half.**

The reason it needs its own witness: in the authored suite the queue appears
exactly once, in a docstring —

    "`v19_queue_runner.sh` read `EXIT=0`, resolved `DISPOSITION=complete`"

— as a *claim about a consequence*, never an assertion. So the branch could
fix the chain's exit status and still leave unproven the thing that made the
defect expensive: that a non-zero chain actually stops the wave. A prose
sentence about a downstream consumer is not evidence about that consumer.

What is driven here is production: ``v19_queue_runner.sh`` is sourced behind
its own source-safe guard (``V19_QUEUE_NO_MAIN=1``), and ``wait_and_record``
— the real function whose verdict becomes ``DISPOSITION`` — is called against
real marker files in the shape ``marker_exit`` reads. Nothing is launched, no
screen, no GPU.

The consequence chain this pins, from ``main()``:

    wait_and_record -> DISPOSITION=complete -> "both chains EXIT=0 — proceeding"
    wait_and_record -> DISPOSITION=failed   -> "QUEUE STOPPED before the next wave"; exit 1
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
QUEUE_RUNNER = REPO_ROOT / "sdsc_submission_scripts" / "v19_queue_runner.sh"


def _drive_wait_and_record(
    tmp_path: Path,
    markers: dict[str, str],
    *,
    unwritten: tuple[str, ...] = (),
) -> subprocess.CompletedProcess:
    """Call the REAL ``wait_and_record`` against real marker files.

    ``markers`` maps a run name to the ``EXIT=`` value its marker carries;
    ``unwritten`` names runs passed to the function for which NO marker file
    exists — a chain that died before recording anything.
    ``chain_screen_alive`` is stubbed false so the wait loop exits at once —
    that is the only stub, and it stands in for "the chains have finished",
    which is the state the function is written to be called in.
    """
    exit_dir = tmp_path / "exits"
    exit_dir.mkdir()
    for run, code in markers.items():
        (exit_dir / f"{run}.exit").write_text(f"EXIT={code}\n", encoding="utf-8")

    runs = " ".join(f"'{r}'" for r in (*markers, *unwritten))
    script = tmp_path / "drive.sh"
    script.write_text(
        "#!/bin/bash\n"
        "export V19_QUEUE_NO_MAIN=1\n"
        f"source '{QUEUE_RUNNER}'\n"
        f"EXIT_DIR='{exit_dir}'\n"
        f"WAVE_STATE_FILE='{tmp_path}/wave_state.jsonl'\n"
        f"QUEUE_STOP_FILE='{tmp_path}/QSTOP'\n"
        "chain_screen_alive() { return 1; }\n"
        "chain_pid() { echo 0; }\n"
        "record_chain() { :; }\n"
        'log() { echo "$*"; }\n'
        "rc=0\n"
        f"wait_and_record 1 '2026-01-01T00:00:00' {runs} || rc=$?\n"
        'echo "WAIT_RC=$rc"\n',
        encoding="utf-8",
    )
    return subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, timeout=60, check=False
    )


def _rc(result: subprocess.CompletedProcess) -> int:
    for line in result.stdout.splitlines():
        if line.startswith("WAIT_RC="):
            return int(line.split("=")[1])
    raise AssertionError(f"driver never reported its result:\n{result.stdout}\n{result.stderr}")


class TestAFailedChainStopsTheWave:
    @pytest.mark.parametrize("code", ["1", "2", "3"])
    def test_a_non_zero_chain_yields_a_failed_disposition(self, tmp_path, code):
        """The half that was only a docstring.

        Every exit code the chain fix can now produce — the ordinary failure
        (1), the launch refusal (2) and the infrastructure halt (3) — must
        make ``wait_and_record`` fail, which is what ``main()`` turns into
        ``DISPOSITION=failed`` and a stopped queue.
        """
        result = _drive_wait_and_record(tmp_path, {"arch_run": code, "loss_run": "0"})
        assert _rc(result) != 0, (
            f"a chain exited {code} and the wave still resolved complete -- "
            "the queue would launch the next wave over a failed one"
        )

    def test_one_failure_among_several_is_enough(self, tmp_path):
        """`all_ok` must be a conjunction. A wave is not complete because
        *most* of it succeeded."""
        result = _drive_wait_and_record(tmp_path, {"arch_run": "0", "loss_run": "2"})
        assert _rc(result) != 0

    def test_a_missing_marker_is_not_read_as_success(self, tmp_path):
        """A chain that never wrote a marker has not reported success.

        `marker_exit` returns the string "missing", which is not "0" —
        pinned because treating an absent record as a pass is the same
        existence-is-not-a-verdict defect F-Q4-1 fixes one layer down.
        """
        result = _drive_wait_and_record(tmp_path, {"arch_run": "0"}, unwritten=("loss_run",))
        assert _rc(result) != 0, (
            "a chain that recorded nothing was counted as a success -- absence read as a pass"
        )


class TestTheWitnessIsNotVacuous:
    def test_an_all_clean_wave_still_advances(self, tmp_path):
        """The guard must not manufacture failures it did not observe — and
        without this, every assertion above would pass on a function that
        always failed."""
        result = _drive_wait_and_record(tmp_path, {"arch_run": "0", "loss_run": "0"})
        assert _rc(result) == 0

    def test_the_production_function_was_actually_reached(self, tmp_path):
        """Reachability. If the source or the call silently no-opped, every
        `!= 0` assertion above would still pass — on nothing."""
        result = _drive_wait_and_record(tmp_path, {"arch_run": "2", "loss_run": "0"})
        combined = result.stdout + result.stderr
        assert "chain arch_run finished: EXIT=2" in combined, (
            "wait_and_record's own logging is absent -- the witness did not "
            f"reach the production function:\n{combined}"
        )
