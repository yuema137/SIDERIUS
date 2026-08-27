"""Pytest wrapper for the P3-L2p zero-LLM launch preflight (protocol §3.3).

Asserts every launch invariant across all six scenario x arm cells with
mocked LLMs — pipeline mode, placeholder resolution, exact treatment
isolation, fixture-hash stability. ZERO real LLM calls.
"""

import subprocess

import pytest

from scripts.pr3_l2_calibration import preflight as preflight_module
from scripts.pr3_l2_calibration.preflight import main as preflight_main


class TestTheCleanTreeGuardFailsClosed:
    """F-M2-2 — check 10 must not PASS because it could not look.

    ``no_production_file_modified`` shells out to ``git diff --name-only``. The
    call had no ``check=True`` and no returncode inspection, so ANY git failure
    produced empty stdout, an empty offender list, and a PASS verdict.

    CLAUDE.md carries "production untouched at launch" as a binding
    precondition of the PR3-L2 calibration protocol, so a silent green here
    lets a calibration run start from a dirty tree with its central
    precondition unverified — the guard reporting success precisely when it
    has failed. Same fail-open family as F2, where an empty HealthGate list
    meant "nothing ran" and read as "nothing fired".
    """

    def _run_with_git_exiting(self, monkeypatch, returncode: int, stderr: str = "boom"):
        real_run = subprocess.run

        def _fake_run(cmd, *args, **kwargs):
            if list(cmd[:3]) == ["git", "diff", "--name-only"]:
                return subprocess.CompletedProcess(cmd, returncode, stdout="", stderr=stderr)
            return real_run(cmd, *args, **kwargs)

        # Patched on the stdlib module itself: preflight does `import
        # subprocess` INSIDE the function, so there is no module-level
        # attribute to intercept.
        monkeypatch.setattr(subprocess, "run", _fake_run)
        return preflight_module.rev3_vocab_and_tee_checks

    def test_a_failing_git_makes_the_check_fail_not_pass(self, monkeypatch):
        """Fails as: no AssertionError raised — i.e. the guard reported PASS
        while git had exited non-zero and it had inspected nothing."""
        checks_fn = self._run_with_git_exiting(monkeypatch, returncode=129)

        with pytest.raises(AssertionError) as excinfo:
            checks_fn()

        assert "no_production_file_modified" in str(excinfo.value)
        assert "UNVERIFIABLE" in str(excinfo.value)

    def test_the_reason_names_git_rather_than_blaming_a_file(self, monkeypatch):
        """ "Could not look" and "looked and found offenders" are different
        facts, and the operator must be able to tell which one happened."""
        checks_fn = self._run_with_git_exiting(
            monkeypatch, returncode=129, stderr="not a git repository"
        )

        with pytest.raises(AssertionError) as excinfo:
            checks_fn()

        message = str(excinfo.value)
        assert "exit 129" in message
        assert "not a git repository" in message


def test_preflight_all_invariants():
    results = preflight_main()  # raises AssertionError on any violation
    # Treatment isolation summarized: block present iff T.
    for scenario in ("S1", "S2"):
        assert results[f"{scenario}_T"]["proposer_block_present"] is True
        assert results[f"{scenario}_C"]["proposer_block_present"] is False
        assert results[f"{scenario}_D"]["proposer_block_present"] is False
        assert results[f"{scenario}_treatment_token_increase"] > 0
    assert results["fixture_hashes"]["S1"] != results["fixture_hashes"]["S2"]
