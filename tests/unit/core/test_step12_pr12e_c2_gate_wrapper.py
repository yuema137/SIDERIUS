"""PR-12e C2 — the recorder's Gate-time call site, proved across real processes.

A provenance recorder with no call site is an F-12bc-6-shaped detector: green
forever, announcing nothing. ``tests/helpers/step12_pr12e_gate_iteration.py``
is that call site, and design §O freezes 12e's expected production write set at
**ZERO**, so it cannot be a line added to ``run_one_iteration.py``.

The property that makes the wrapper honest is narrow and easy to lose: the
identity it records must belong to the interpreter that then executes the
iteration. A wrapper that spawned the runner as a child would record ITSELF —
every iteration's provenance would describe a wrapper, the real runners would
go unrecorded, and two iterations launched from one shell would still look
distinct, so the defect would be invisible in the verdict.

These tests spawn real interpreters. They are cheap (the harness pulls no
production module at import) and they are NOT the Gate: they prove the
wrapper's mechanics, never that a real chain restored real state.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.helpers.step12_pr12e_gate_iteration import DEFAULT_TARGET, REPO_ROOT
from tests.helpers.step12_pr12e_restore_harness import read_process_ledger, same_interpreter

WRAPPER = REPO_ROOT / "tests" / "helpers" / "step12_pr12e_gate_iteration.py"


def _stub_target(tmp_path: Path, body: str) -> Path:
    """A stand-in for ``run_one_iteration.py`` that reports what it saw."""
    target = tmp_path / "stub_target.py"
    target.write_text(
        textwrap.dedent(
            """
            import json
            import pathlib
            import sys

            from tests.helpers.step12_pr12e_restore_harness import record_iteration_process

            _WS = sys.argv[sys.argv.index("--ws") + 1]
            record_iteration_process(_WS, 99, role="target")
            pathlib.Path(_WS, "target_argv.json").write_text(json.dumps(sys.argv))
            """
        )
        + textwrap.dedent(body),
        encoding="utf-8",
    )
    return target


def _wrap(
    workspace: Path, iteration: int, target: Path, target_argv: list[str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(WRAPPER),
            "--provenance-workspace",
            str(workspace),
            "--provenance-iteration",
            str(iteration),
            "--provenance-target",
            str(target),
            "--",
            *target_argv,
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=180,
    )


class TestRecorderAndWorkloadShareOneInterpreter:
    def test_the_recorded_interpreter_is_the_one_that_runs_the_target(self, tmp_path):
        """THE property that makes the wrapper worth having.

        Defect: a wrapper that spawns the runner instead of ``runpy``-ing it.
        Its recorded identity would describe the wrapper, so `G-12e`'s
        provenance would attribute both iterations to processes that ran no
        iteration — and the §K claim would be about the wrong processes
        entirely.

        Fails when ``main`` stops executing the target in-process: the target's
        own entry then carries a different nonce and ``same_interpreter``
        returns False.
        """
        target = _stub_target(tmp_path, "")
        proc = _wrap(tmp_path, 1, target, ["--ws", str(tmp_path)])
        assert proc.returncode == 0, proc.stderr[-3000:]

        entries = read_process_ledger(tmp_path)
        roles = {entry.role: entry.identity for entry in entries}
        assert set(roles) == {"iteration", "target"}
        assert same_interpreter(roles["iteration"], roles["target"]) is True

    def test_two_invocations_are_distinct_interpreters(self, tmp_path):
        """The positive control: without it, a wrapper that recorded one
        constant identity would satisfy the test above and still make every
        real restore look like an in-process continuation.

        Fails if the recorded identity stops varying per launch.
        """
        target = _stub_target(tmp_path, "")
        for iteration in (1, 2):
            proc = _wrap(tmp_path, iteration, target, ["--ws", str(tmp_path)])
            assert proc.returncode == 0, proc.stderr[-3000:]

        iterations = [e.identity for e in read_process_ledger(tmp_path) if e.role == "iteration"]
        assert len(iterations) == 2
        assert same_interpreter(*iterations) is False


class TestTheWrapperDoesNotRewriteTheLaunch:
    def test_target_argv_is_forwarded_verbatim(self, tmp_path):
        """Defect: a wrapper that parses with ``argparse`` claims flags it
        recognises — and ``--workspace`` is spelled the same on both sides. The
        Gate would then execute a different command than the operator wrote,
        while the evidence packet described the command they intended.

        Fails if any element after ``--`` is dropped, reordered or rewritten.
        """
        target = _stub_target(tmp_path, "")
        argv = ["--ws", str(tmp_path), "--workspace", "/not/the/wrappers", "--start_iteration", "2"]
        proc = _wrap(tmp_path, 2, target, argv)
        assert proc.returncode == 0, proc.stderr[-3000:]

        seen = json.loads((tmp_path / "target_argv.json").read_text(encoding="utf-8"))
        assert seen[0] == str(target)
        assert seen[1:] == argv

    def test_a_wrapper_spelling_after_the_separator_belongs_to_the_target(self, tmp_path):
        """Defect: consuming ``--provenance-*`` wherever it appears. Everything
        after ``--`` is the target's, including strings that happen to match a
        wrapper flag; eating one would silently shorten the runner's argv.

        Fails if the split stops being positional.
        """
        target = _stub_target(tmp_path, "")
        argv = ["--ws", str(tmp_path), "--provenance-iteration", "77"]
        proc = _wrap(tmp_path, 1, target, argv)
        assert proc.returncode == 0, proc.stderr[-3000:]

        seen = json.loads((tmp_path / "target_argv.json").read_text(encoding="utf-8"))
        assert seen[1:] == argv
        recorded = [e.iteration for e in read_process_ledger(tmp_path) if e.role == "iteration"]
        assert recorded == [1]

    def test_a_missing_separator_is_refused(self, tmp_path):
        """Defect: guessing where the wrapper's flags end. A wrapper that
        guessed could forward its own flags into the runner, or swallow the
        runner's — either way the executed launch is not the written one.

        Fails if ``_parse`` stops requiring the bare ``--``.
        """
        proc = subprocess.run(
            [sys.executable, str(WRAPPER), "--provenance-workspace", str(tmp_path)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=60,
        )
        assert proc.returncode != 0
        assert "'--' separator" in proc.stderr


class TestProvenanceOutlivesTheWorkload:
    @pytest.mark.parametrize("code", [0, 3])
    def test_the_targets_exit_code_is_the_wrappers(self, tmp_path, code):
        """Defect: a wrapper that swallows the runner's status. The chain
        driver decides whether to continue from that exit code, so a wrapper
        reporting 0 for a failed iteration would let the chain march on — and
        `G-12e`'s "workflow exit 0" criterion (§L.2) would be reading the
        wrapper, not the run.

        Fails when ``SystemExit.code`` stops being propagated.
        """
        target = _stub_target(tmp_path, f"\nraise SystemExit({code})\n")
        proc = _wrap(tmp_path, 1, target, ["--ws", str(tmp_path)])
        assert proc.returncode == code, proc.stderr[-3000:]

    def test_a_crashing_iteration_still_left_its_provenance(self, tmp_path):
        """Defect: recording AFTER the runner returns. The one iteration whose
        provenance matters most is the one that died, and a recorder that runs
        last never records it.

        Fails if ``record_iteration_process`` moves below the ``runpy`` call.
        """
        target = _stub_target(tmp_path, "\nraise RuntimeError('the iteration exploded')\n")
        proc = _wrap(tmp_path, 1, target, ["--ws", str(tmp_path)])
        assert proc.returncode != 0
        assert "the iteration exploded" in proc.stderr

        recorded = [e.iteration for e in read_process_ledger(tmp_path) if e.role == "iteration"]
        assert recorded == [1]


class TestTheDefaultTargetIsThisCheckout:
    def test_it_resolves_to_the_production_runner_beside_this_file(self):
        """Defect: a hardcoded absolute path, or one resolved from the caller's
        cwd. Either would drive a DIFFERENT clone than the one under test —
        the CLAUDE.md portability rule, and the failure mode where a green
        local result says nothing about the checkout it claims to validate.

        Fails if ``DEFAULT_TARGET`` stops being derived from ``__file__``.
        """
        assert DEFAULT_TARGET.is_file()
        assert DEFAULT_TARGET == REPO_ROOT / "sdsc_submission_scripts" / "run_one_iteration.py"
        assert (REPO_ROOT / "tests" / "helpers" / "step12_pr12e_gate_iteration.py").is_file()
