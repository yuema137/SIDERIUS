"""A chain must never report success while its iterations failed.

The defect (F8, found by a fresh-user onboarding witness against
v0.1.0-rc.1). `run_chain` captured each child's exit status, tested it
ONLY for `>= 128`, and then returned 0 unconditionally. Every other
failure was discarded:

    iteration crashes (exit 1)      -> chain returns 0
    iteration demands a halt (3)    -> chain returns 0, loop keeps going
    manifest missing at the end     -> printed, then exit 0

The summary block in `run_chain.sh` even printed
`iter N -> MISSING (this should not happen on a clean run)` and then ran
off the end of the script, which in bash is exit 0. The text was honest;
the status automation gates on was not. The formal campaign launches
through this script, so a fleet gating on `$?` recorded a failed chain as
a pass.

What these tests pin, and what they deliberately do NOT:

    pinned      the chain's TERMINAL STATUS and the artifacts it is
                derived from
    NOT pinned  whether an ordinary failed iteration stops the chain.
                It does not, by design -- the no-respawn rule is scoped
                to an OPERATOR-DIRECTED stop, and a later iteration can
                still make progress from an earlier seed. That frozen
                continuation behaviour has its own test below, because a
                "fix" that silently halted the chain on any failure would
                be a science regression wearing a bug fix's clothes.

These drive the REAL `run_chain` and `report_chain_outcome` by sourcing
`_chain_common.sh`, which is the route its own header documents for unit
tests. Nothing here executes a launcher: `submit_iteration` is a stub
that returns the exit code under test, which is what makes a controlled
failure witness possible at all.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHAIN_LIB = REPO_ROOT / "sdsc_submission_scripts" / "_chain_common.sh"
ENTRY_SCRIPT = REPO_ROOT / "sdsc_submission_scripts" / "run_chain.sh"


def _drive(tmp_path: Path, body: str, *, iterations: int = 2) -> subprocess.CompletedProcess:
    """Source the chain library in a throwaway script and run `body`.

    The workspace is under `tmp_path`, so nothing here can touch a real
    run's state.
    """
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    script = tmp_path / "drive.sh"
    script.write_text(
        "#!/bin/bash\n"
        f"source '{CHAIN_LIB}'\n"
        f"WORKSPACE='{workspace}'\n"
        f"NUM_ITERATIONS={iterations}\n"
        "START_ITER=1\n"
        "DRY_RUN=0\n"
        "RUN_NAME=honesty_witness\n"
        f"CHAIN_STOP_FILE='{workspace}/STOP'\n"
        "build_source_paths() { SOURCE_PATHS=(); }\n"
        "build_app_args()     { APP_ARGS=(); }\n"
        "SPAWNED=0\n" + body,
        encoding="utf-8",
    )
    return subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, timeout=60, check=False
    )


def _stub_child(exit_code: int) -> str:
    """A `submit_iteration` that fails the way the case under test needs."""
    return (
        "submit_iteration() { SPAWNED=$((SPAWNED+1)); "
        f"return {exit_code}; }}\n"
        "rc=0\n"
        "run_chain || rc=$?\n"
        'echo "RC=$rc SPAWNED=$SPAWNED"\n'
    )


def _write_manifest(workspace: Path, iteration: int, status: str) -> Path:
    """A REAL iteration manifest, in the shape `run_one_iteration.py` writes.

    Not `"{}"`. The status field is the whole point: a fixture without one
    can only ever certify that the reader checked for the file's existence,
    which is exactly how F-Q4-1 survived the first version of this suite.
    """
    d = workspace / f"iter_{iteration:03d}"
    d.mkdir(parents=True, exist_ok=True)
    path = d / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "status": status,
                "iteration_dir": str(d),
                "output_path": str(d / "run_output.json") if status == "completed" else None,
                "model_name": "wavenet" if status == "completed" else None,
                "best_score": 11.96875 if status == "completed" else None,
            }
        ),
        encoding="utf-8",
    )
    return path


def _parse(out: str) -> tuple[int, int]:
    for line in out.splitlines():
        if line.startswith("RC="):
            rc, spawned = line.split()
            return int(rc.split("=")[1]), int(spawned.split("=")[1])
    raise AssertionError(f"driver never reported its result:\n{out}")


class TestTerminalStatusReflectsChildFailure:
    def test_a_crashed_iteration_makes_the_chain_report_failure(self, tmp_path):
        """THE witness. Before the fix this returned 0 with both children dead."""
        result = _drive(tmp_path, _stub_child(1))
        rc, spawned = _parse(result.stdout)
        assert spawned == 2, "the witness never ran the iterations it claims to test"
        assert rc != 0, (
            "every iteration crashed and the chain still reported success -- "
            "this is exactly F8, and fleet automation gating on $? would "
            "record this run as a pass"
        )

    def test_the_failure_is_attributed_to_its_iteration(self, tmp_path):
        """A status is only actionable if it says WHICH iteration died."""
        result = _drive(tmp_path, _stub_child(1))
        combined = result.stdout + result.stderr
        assert "iteration 1 FAILED (exit 1)" in combined
        assert "iteration 2 FAILED (exit 1)" in combined

    def test_a_clean_chain_still_reports_success(self, tmp_path):
        """The guard must not manufacture failures it did not observe."""
        result = _drive(tmp_path, _stub_child(0))
        rc, spawned = _parse(result.stdout)
        assert (rc, spawned) == (0, 2)


class TestTheHealthGateRefusalIsNotSwallowed:
    """Carry-home addition (#315). The authored suite drove exit 0, 1 and 3.

    **Exit 2 was never exercised**, and exit 2 is what
    ``run_one_iteration.py`` raises to REFUSE a launch — the HealthGate /
    formal-launch refusal, at three production sites. F-SCANB-1 names that
    refusal explicitly as one of the two things the old ``status -ge 128``
    test plus unconditional ``return 0`` swallowed.

    A fix that handles 1 and 3 is not evidence for 2: the swallowing was a
    BOUNDARY defect (``-ge 128``), and boundary defects are exactly what a
    0/1/3 sample cannot see. So the refusal gets its own witness rather than
    an argument that ``status -ne 0`` must surely cover it.
    """

    def test_an_iteration_that_refuses_makes_the_chain_report_failure(self, tmp_path):
        result = _drive(tmp_path, _stub_child(2))
        rc, spawned = _parse(result.stdout)
        assert spawned == 2, "the witness never ran the iterations it claims to test"
        assert rc != 0, (
            "an iteration REFUSED to launch (exit 2) and the chain still "
            "reported success -- the refusal that exists to stop work would "
            "be invisible to anything gating on $?"
        )

    def test_the_refusal_is_attributed_to_its_iteration(self, tmp_path):
        result = _drive(tmp_path, _stub_child(2))
        combined = result.stdout + result.stderr
        assert "iteration 1 FAILED (exit 2)" in combined

    def test_a_refusal_does_not_masquerade_as_a_signal_kill(self, tmp_path):
        """Exit 2 must land in the ordinary-failure path, not the >=128 one.

        Both produce a non-zero chain status, so `rc != 0` alone cannot tell
        them apart -- and mis-classifying a refusal as an external signal
        would record `iteration_terminated_by_signal` in the stop reason and
        send an operator looking for a kill that never happened.
        """
        result = _drive(tmp_path, _stub_child(2))
        combined = result.stdout + result.stderr
        assert "terminated_by_signal" not in combined
        assert "child_signal_" not in combined


class TestFrozenContinuationBehaviour:
    """An ordinary failure must NOT stop the chain -- that is by design."""

    def test_an_ordinary_failure_does_not_stop_the_chain(self, tmp_path):
        """Iteration 1 crashing must still leave iteration 2 to be attempted.

        Fails if a future change turns the honest exit status into an
        early halt: the science relies on a later iteration being able to
        proceed from an earlier seed.
        """
        result = _drive(tmp_path, _stub_child(1), iterations=3)
        _, spawned = _parse(result.stdout)
        assert spawned == 3, (
            "an ordinary failed iteration halted the chain -- the no-respawn "
            "rule is scoped to an OPERATOR-DIRECTED stop, not to any failure"
        )


class TestInfrastructureAbortHalts:
    """Exit 3 is the C9c halt code, and it must actually halt the loop."""

    def test_a_halt_demand_stops_the_loop(self, tmp_path):
        """The `.chain_halted` sentinel was carrying this alone.

        Every later child read the sentinel and refused at startup, so the
        halt was real -- but the loop kept spawning children to be refused
        and the chain still called itself complete.
        """
        result = _drive(tmp_path, _stub_child(3), iterations=3)
        rc, spawned = _parse(result.stdout)
        assert spawned == 1, "the chain kept starting iterations after an abort demand"
        assert rc == 3, f"a halted chain must exit 3, not {rc}"

    def test_the_halt_is_recorded_as_its_own_reason(self, tmp_path):
        """Distinguishable from an operator stop in the state record."""
        result = _drive(tmp_path, _stub_child(3))
        assert "iteration_infrastructure_abort" in result.stdout
        record = tmp_path / "ws" / "chain_stopped.json"
        assert record.exists(), "a halted chain wrote no state record"
        assert "iteration_infrastructure_abort" in record.read_text(encoding="utf-8")


class TestOutcomeIsDerivedFromArtifacts:
    """`report_chain_outcome` reads the manifests, not the log text."""

    def _report(self, tmp_path: Path, manifests: tuple[int, ...], iterations: int = 2):
        workspace = tmp_path / "ws"
        workspace.mkdir(exist_ok=True)
        for i in manifests:
            _write_manifest(workspace, i, "completed")
        return _drive(
            tmp_path,
            "CHAIN_FAILED_ITERATIONS=()\nrc=0\nreport_chain_outcome || rc=$?\n"
            'echo "RC=$rc SPAWNED=0"\n',
            iterations=iterations,
        )

    def test_a_missing_manifest_is_a_failure_not_a_remark(self, tmp_path):
        """Before the fix this printed MISSING and exited 0."""
        result = self._report(tmp_path, manifests=(1,))
        rc, _ = _parse(result.stdout)
        assert "MISSING" in result.stdout
        assert rc != 0, "the chain announced a missing manifest and reported success"

    def test_every_manifest_completed_is_a_clean_chain(self, tmp_path):
        result = self._report(tmp_path, manifests=(1, 2))
        rc, _ = _parse(result.stdout)
        assert rc == 0
        assert "CHAIN COMPLETE" in result.stdout

    def test_the_banner_never_contradicts_the_evidence_below_it(self, tmp_path):
        """A run missing a manifest must not be headlined COMPLETE."""
        result = self._report(tmp_path, manifests=(1,))
        assert "CHAIN INCOMPLETE" in result.stdout
        assert "CHAIN COMPLETE" not in result.stdout


class TestExistenceIsNotAVerdict:
    """F-Q4-1. A manifest's STATUS decides, not the fact that it exists.

    `run_one_iteration.py` writes a `no_records` manifest and DELIBERATELY
    `sys.exit(0)` on gate exhaustion, so the chain may continue and the
    next iteration's LLM can adapt. Neither half of the old clean verdict
    could see that: the file existed, and the child's exit status was 0. A
    chain whose every iteration exhausted its gates trained nothing,
    scored nothing, printed CHAIN COMPLETE and exited 0 -- and
    `v19_queue_runner.sh` read `EXIT=0`, resolved `DISPOSITION=complete`
    and advanced the campaign wave.

    The first version of this suite wrote `"{}"` as its manifest fixture,
    with no status field at all, so it could only ever confirm
    existence-only semantics. That is why the defect survived a suite
    written specifically to catch dishonest chain verdicts, and it is why
    every fixture below is a REAL manifest shape.
    """

    def _report(self, tmp_path: Path, statuses: dict[int, str], iterations: int = 2):
        workspace = tmp_path / "ws"
        workspace.mkdir(exist_ok=True)
        for i, status in statuses.items():
            _write_manifest(workspace, i, status)
        return _drive(
            tmp_path,
            "CHAIN_FAILED_ITERATIONS=()\nrc=0\nreport_chain_outcome || rc=$?\n"
            'echo "RC=$rc SPAWNED=0"\n',
            iterations=iterations,
        )

    def test_an_all_no_records_chain_must_not_exit_zero(self, tmp_path):
        """THE witness -- the exact testpod manifest, reproduced twice."""
        result = self._report(tmp_path, {1: "no_records", 2: "no_records"})
        rc, _ = _parse(result.stdout)
        assert rc != 0, (
            "every iteration exhausted its gates -- nothing trained, nothing "
            "scored -- and the chain reported success, which advances the "
            "campaign wave"
        )
        assert "CHAIN COMPLETE" not in result.stdout

    def test_it_says_no_iteration_was_authoritative(self, tmp_path):
        result = self._report(tmp_path, {1: "no_records", 2: "no_records"})
        assert "produced no authoritative result" in result.stdout

    def test_the_status_is_on_the_per_iteration_line(self, tmp_path):
        """A reader must not have to open the file to learn what happened."""
        result = self._report(tmp_path, {1: "completed", 2: "no_records"})
        assert "[completed]" in result.stdout
        assert "[no_records]" in result.stdout

    def test_a_mixed_chain_may_exit_zero(self, tmp_path):
        """`no_records` is a DESIGNED chainable state, not a failure.

        A chain that produced at least one authoritative result did its
        job; refusing it would break the state the orchestrator relies on.
        """
        result = self._report(tmp_path, {1: "completed", 2: "no_records"})
        rc, _ = _parse(result.stdout)
        assert rc == 0

    def test_a_mixed_chain_still_names_the_barren_iterations(self, tmp_path):
        """Exiting 0 is allowed; staying silent about it is not."""
        result = self._report(tmp_path, {1: "completed", 2: "no_records"})
        assert "2:no_records" in result.stdout

    @pytest.mark.parametrize("status", ["failed", "aborted", "some_future_status"])
    def test_an_unrecognised_status_fails_closed(self, tmp_path, status):
        """Rule 5: never add an unknown status to a success list."""
        result = self._report(tmp_path, {1: status, 2: status})
        rc, _ = _parse(result.stdout)
        assert rc != 0, f"status {status!r} was treated as a success"

    def test_an_unreadable_manifest_is_not_completed(self, tmp_path):
        """A truncated or status-less manifest must not read as success."""
        workspace = tmp_path / "ws"
        workspace.mkdir(exist_ok=True)
        for i in (1, 2):
            d = workspace / f"iter_{i:03d}"
            d.mkdir(parents=True, exist_ok=True)
            (d / "manifest.json").write_text("{}", encoding="utf-8")
        result = _drive(
            tmp_path,
            "CHAIN_FAILED_ITERATIONS=()\nrc=0\nreport_chain_outcome || rc=$?\n"
            'echo "RC=$rc SPAWNED=0"\n',
        )
        rc, _ = _parse(result.stdout)
        assert rc != 0
        assert "[unreadable]" in result.stdout

    def test_an_indented_manifest_parses_the_same(self, tmp_path):
        """Production writes `json.dumps(..., indent=2)`; the testpod
        fixture was compact. Both must read identically."""
        workspace = tmp_path / "ws"
        workspace.mkdir(exist_ok=True)
        for i in (1, 2):
            d = workspace / f"iter_{i:03d}"
            d.mkdir(parents=True, exist_ok=True)
            (d / "manifest.json").write_text(
                json.dumps({"status": "no_records", "output_path": None}, indent=2),
                encoding="utf-8",
            )
        result = _drive(
            tmp_path,
            "CHAIN_FAILED_ITERATIONS=()\nrc=0\nreport_chain_outcome || rc=$?\n"
            'echo "RC=$rc SPAWNED=0"\n',
        )
        rc, _ = _parse(result.stdout)
        assert rc != 0
        assert "[no_records]" in result.stdout


class TestEntryScriptPropagatesTheVerdict:
    """The library can only be honest if the entry script exits with it.

    Static, because executing `run_chain.sh` starts a real chain (see
    `tests/unit/guardrails/test_no_test_executes_a_launcher.py`). The
    behaviour under the verdict is covered above; what is checked here is
    that the verdict reaches the process exit status at all -- the exact
    hop that was missing, since the summary block sat past the script's
    last `exit` and bash then returned 0.
    """

    def test_the_script_exits_with_the_computed_outcome(self):
        source = ENTRY_SCRIPT.read_text(encoding="utf-8")
        assert "report_chain_outcome || CHAIN_OUTCOME=$?" in source
        assert source.rstrip().endswith('exit "$CHAIN_OUTCOME"'), (
            "the chain's verdict must be the script's LAST statement -- "
            "anything after it decides the exit status instead"
        )

    def test_an_iteration_failure_still_reaches_the_summary(self):
        """C2: the summary must not be a success-path courtesy.

        The early exit for a STOPPED chain used to fire on any non-zero
        status, so once an iteration failure became non-zero it swallowed
        the per-iteration summary on exactly the runs that needed it --
        leaving `report_chain_outcome`'s failure branch unreachable from
        production, and 'decide first, announce second' true only when
        nothing went wrong.

        Fails by: the early exit dropping its
        `CHAIN_ITERATION_FAILED_EXIT_CODE` exemption.
        """
        source = ENTRY_SCRIPT.read_text(encoding="utf-8")
        assert (
            '[ "$CHAIN_STATUS" -ne 0 ] && [ "$CHAIN_STATUS" -ne "$CHAIN_ITERATION_FAILED_EXIT_CODE" ]'
            in source
        ), "an iteration failure exits before the summary is printed"

    def test_the_outcome_is_seeded_from_the_loop_status(self):
        """A mode that never calls `report_chain_outcome` (SDSC submits
        rather than runs) must not reset a loop-level failure to 0."""
        source = ENTRY_SCRIPT.read_text(encoding="utf-8")
        assert "CHAIN_OUTCOME=$CHAIN_STATUS" in source

    def test_the_script_is_syntactically_valid(self):
        assert subprocess.run(["bash", "-n", str(ENTRY_SCRIPT)], check=False).returncode == 0

    @pytest.mark.parametrize("script", [CHAIN_LIB, ENTRY_SCRIPT])
    def test_the_shell_sources_parse(self, script):
        assert subprocess.run(["bash", "-n", str(script)], check=False).returncode == 0
