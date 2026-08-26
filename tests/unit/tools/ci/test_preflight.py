"""Execution-root preflight — the checks that stop invalid evidence.

Each test names a defect only it can catch. The preflight's whole value is
that it refuses BEFORE ~13,000 tests run, so the defects worth guarding are
the ones that would let an invalid root through silently.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools.ci import preflight as pf


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A committed git checkout with no machine config and no .venv."""
    root = tmp_path / "root"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "tracked.txt").write_text("x\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


class TestSatisfied:
    def test_unknown_does_not_count_as_satisfied(self):
        """An unevaluated precondition is not a met one.

        If `satisfied` only rejected VIOLATION, a check that could not run —
        git missing, interpreter unprobeable — would be indistinguishable from
        a passing one, and the harness would launch on a root it never
        verified. Fails as: satisfied becomes True for an UNKNOWN-only report.
        """
        report = pf.PreflightReport(
            root=Path("/x"),
            checks=[pf.CheckResult(name="c", outcome=pf.Outcome.UNKNOWN, detail="d")],
        )
        assert report.satisfied is False
        assert [c.name for c in report.failures()] == ["c"]


class TestVenvCheck:
    def test_a_venv_path_that_exists_but_cannot_execute_is_a_violation(self, repo: Path):
        """Existence is not the contract; running is.

        A dangling symlink or a truncated file at .venv/bin/python satisfies
        `exists()` while every test that executes the interpreter fails with a
        product-looking error. Fails as: outcome OK for a non-executable path.
        """
        python = pf.venv_python(repo)
        python.parent.mkdir(parents=True)
        python.write_text("not an interpreter\n", encoding="utf-8")
        python.chmod(0o755)
        result = pf.check_venv(repo, require=True)
        assert result.outcome is pf.Outcome.VIOLATION
        assert "failed to execute" in result.detail

    def test_missing_venv_names_the_bootstrap_command(self, repo: Path):
        """The remedy must be actionable, because this is THE common failure.

        PR-12d lost a debugging cycle to an unbootstrapped worktree. A report
        saying only "venv missing" reproduces that cost. Fails as: remedy does
        not name `uv sync`.
        """
        result = pf.check_venv(repo, require=True)
        assert result.outcome is pf.Outcome.VIOLATION
        assert "uv sync --group dev --frozen" in result.remedy


class TestTreeClean:
    def test_untracked_files_are_not_a_violation(self, repo: Path):
        """Untracked pollution is reported as provenance, never a blocker.

        Conflating the two would make every run with a stray log file refuse,
        and the pressure would be to add a broad .gitignore — which is exactly
        how pollution becomes invisible. Fails as: an untracked file trips the
        clean check.
        """
        (repo / "stray.log").write_text("noise\n", encoding="utf-8")
        assert pf.check_tree_clean(repo, expect_clean=True).outcome is pf.Outcome.OK

    def test_a_modified_tracked_file_is_a_violation(self, repo: Path):
        """A mutating tree invalidates every shard reading it.

        Fails as: modified tracked files pass, and shards run against a source
        that changes underneath them.
        """
        (repo / "tracked.txt").write_text("mutated\n", encoding="utf-8")
        result = pf.check_tree_clean(repo, expect_clean=True)
        assert result.outcome is pf.Outcome.VIOLATION
        assert "tracked.txt" in result.detail


class TestMachineConfigs:
    def test_a_present_machine_config_is_a_violation(self, repo: Path):
        """Presence changes observable behaviour, so it cannot be ignored.

        `tidmad_data_config.yaml` suppresses an import-time UserWarning that a
        golden stderr comparison counted; its presence is why a green developer
        machine produced a red CI run. Fails as: a present config reports OK.
        """
        (repo / "tidmad_data_config.yaml").write_text("tidmad_data_dir: /x\n", encoding="utf-8")
        result = pf.check_machine_configs(repo, expect_absent=pf.MACHINE_CONFIG_FILES)
        assert result.outcome is pf.Outcome.VIOLATION
        assert "tidmad_data_config.yaml" in result.detail

    def test_the_tracked_template_is_not_treated_as_machine_config(self, repo: Path):
        """The committed template must never trip the absence contract.

        `data_paths` deliberately falls back to `tidmad_data_config.example.yaml`
        so a fresh clone imports; flagging it would make every clean checkout
        fail preflight. Fails as: the example template counts as machine config.
        """
        (repo / "tidmad_data_config.example.yaml").write_text(
            "tidmad_data_dir: /p\n", encoding="utf-8"
        )
        assert (
            pf.check_machine_configs(repo, expect_absent=pf.MACHINE_CONFIG_FILES).outcome
            is pf.Outcome.OK
        )


class TestNodeForPyright:
    def test_an_old_node_is_a_violation_that_forbids_moving_pyright(self, monkeypatch):
        """The remedy must point at Node, not at the pinned pyright version.

        pyright is fixed by uv.lock; "upgrade pyright" would change the
        repository's typecheck authority to repair one developer box. Fails as:
        an old Node passes, or the remedy suggests changing pyright.
        """
        monkeypatch.setattr(pf, "node_major", lambda executable="node": 10)
        result = pf.check_node_for_pyright(require=True)
        assert result.outcome is pf.Outcome.VIOLATION
        assert "NOT VALID EVIDENCE" in result.detail
        assert "do NOT change the pinned pyright version" in result.remedy

    def test_absent_node_is_a_violation_not_a_pass(self, monkeypatch):
        """A missing tool is an unmet precondition, never an implicit skip.

        Fails as: node absent reports OK and the run claims a local type check.
        """
        monkeypatch.setattr(pf, "node_major", lambda executable="node": None)
        assert pf.check_node_for_pyright(require=True).outcome is pf.Outcome.VIOLATION


class TestTmpdir:
    def test_unset_tmpdir_is_a_violation(self, monkeypatch):
        """Shards sharing the system temp collide non-deterministically.

        Fails as: an unset TMPDIR passes and concurrent shards interfere.
        """
        monkeypatch.delenv("TMPDIR", raising=False)
        assert pf.check_tmpdir().outcome is pf.Outcome.VIOLATION

    def test_tmpdir_pointing_at_a_nonexistent_directory_is_a_violation(self, monkeypatch, tmp_path):
        """A set-but-wrong TMPDIR is worse than unset: it looks configured.

        Fails as: a dangling TMPDIR passes.
        """
        monkeypatch.setenv("TMPDIR", str(tmp_path / "nope"))
        assert pf.check_tmpdir().outcome is pf.Outcome.VIOLATION


class TestRunPreflight:
    def test_every_check_is_evaluated_not_short_circuited(self, repo: Path, monkeypatch):
        """The report must list ALL violations, not the first one.

        Stopping at the first failure recreates the fix-one/rerun loop this
        lane exists to remove. Fails as: a root with several violations reports
        only one.
        """
        monkeypatch.delenv("TMPDIR", raising=False)
        (repo / ".env").write_text("K=v\n", encoding="utf-8")
        report = pf.run_preflight(pf.ExecutionRoot(path=repo, require_venv=True))
        failed = {c.name for c in report.failures()}
        assert {"venv", "machine_configs_absent", "tmpdir"} <= failed

    def test_a_non_git_directory_reports_unknown_sha_and_refuses(self, tmp_path: Path):
        """Results must be attributable to an exact commit.

        A run whose SHA is unknown cannot be compared against CI or a base
        control, so it is not usable evidence. Fails as: a non-git directory
        preflights clean.
        """
        report = pf.run_preflight(pf.ExecutionRoot(path=tmp_path, require_venv=False))
        assert report.sha is None
        assert report.satisfied is False

    def test_render_names_both_the_condition_and_the_remedy(self, repo: Path):
        """An operator-facing failure without a remedy costs a debugging cycle.

        Fails as: render() prints the violation but drops the fix.
        """
        text = pf.run_preflight(pf.ExecutionRoot(path=repo, require_venv=True)).render()
        assert text.startswith("HARNESS PREFLIGHT FAILURE")
        assert "uv sync --group dev --frozen" in text


class TestTmpdirRequirementIsDeclared:
    def test_bulk_style_roots_do_not_demand_a_parent_tmpdir(self, monkeypatch):
        """The harness assigns TMPDIR per shard, so demanding one is friction.

        Found by running the harness: the first real bulk invocation was refused
        for an unset TMPDIR even though `run_shard` sets one for every shard.
        Fails as: require_tmpdir=False still reports a violation, and every
        bulk run needs a meaningless environment variable.
        """
        monkeypatch.delenv("TMPDIR", raising=False)
        assert pf.check_tmpdir(require=False).outcome is pf.Outcome.OK

    def test_a_bare_preflight_still_demands_it(self, monkeypatch):
        """A human about to run pytest directly has nothing else to set it.

        Fails as: the relaxation leaks into standalone preflight and shards
        launched by hand share the system temp.
        """
        monkeypatch.delenv("TMPDIR", raising=False)
        assert pf.check_tmpdir(require=True).outcome is pf.Outcome.VIOLATION


class TestExternalResources:
    """CP-8: absence and misconfiguration are DIFFERENT states."""

    def _res(self, tmp_path):
        return (
            pf.ExternalResource(
                name="thing", default_path=tmp_path / "nope", env_var="X_THING", gates_skips=7
            ),
        )

    def test_a_misconfigured_override_is_a_violation_not_an_absence(self, monkeypatch, tmp_path):
        """Set-but-invalid must never be silently treated as 'not available'.

        The tests themselves refuse a set-but-invalid path loudly — I proved
        that by mis-simulating CI and getting 4 hard errors instead of skips.
        A harness that called it 'absent' would disagree with the suite it runs.
        Fails as: a dangling override reports OK.
        """
        monkeypatch.setenv("X_THING", str(tmp_path / "missing"))
        r = pf.check_external_resources(expect_absent=True, resources=self._res(tmp_path))
        assert r.outcome is pf.Outcome.VIOLATION
        assert "not a directory" in r.detail

    def test_misconfiguration_violates_even_when_presence_is_allowed(self, monkeypatch, tmp_path):
        """Misconfigured is neither present nor absent, so no claim excuses it.

        Fails as: expect_absent=False lets a broken override through.
        """
        monkeypatch.setenv("X_THING", str(tmp_path / "missing"))
        assert (
            pf.check_external_resources(expect_absent=False, resources=self._res(tmp_path)).outcome
            is pf.Outcome.VIOLATION
        )

    def test_a_present_resource_violates_a_ci_parity_claim(self, monkeypatch, tmp_path):
        """Presence silently changes 43 test outcomes — it cannot be implicit.

        This is CP-8 itself: two environments both called themselves parity
        while 43 tests differed. Fails as: a run claims CI parity with the
        datasets mounted and nobody is told.
        """
        real = tmp_path / "real"
        real.mkdir()
        monkeypatch.setenv("X_THING", str(real))
        r = pf.check_external_resources(expect_absent=True, resources=self._res(tmp_path))
        assert r.outcome is pf.Outcome.VIOLATION
        assert "~7 tests would RUN here that SKIP on CI" in r.detail

    def test_absence_is_legitimate_when_parity_is_claimed(self, monkeypatch, tmp_path):
        """Absence is the CI-parity default and must not be an error.

        Fails as: a correct parity root is refused for lacking the datasets.
        """
        monkeypatch.delenv("X_THING", raising=False)
        r = pf.check_external_resources(expect_absent=True, resources=self._res(tmp_path))
        assert r.outcome is pf.Outcome.OK
        assert "thing=absent" in r.detail

    def test_the_declared_resources_carry_measured_skip_counts(self):
        """The counts are CP-8's evidence; an unmeasured entry is a guess.

        Fails as: a resource is declared without the measurement that justifies
        listing it, and the contract drifts back to assertion.
        """
        assert sum(r.gates_skips for r in pf.DECLARED_RESOURCES) == 40
        assert all(r.gates_skips > 0 for r in pf.DECLARED_RESOURCES)


class TestManagedNodeStrategy:
    def test_a_managed_node_makes_the_host_version_irrelevant(self, monkeypatch):
        """Refusing a working root because the HOST node is old is a false negative.

        With PYRIGHT_PYTHON_GLOBAL_NODE=false the wheel provisions its own node
        (measured: v26.7.0) and runs the locked pyright 1.1.409, so the system
        node is never consulted. Fails as: a correctly-configured parity root is
        refused for a v10 system node it does not use.
        """
        monkeypatch.setenv("PYRIGHT_PYTHON_GLOBAL_NODE", "false")
        monkeypatch.setattr(pf, "node_major", lambda executable="node": 10)
        r = pf.check_node_for_pyright(require=True)
        assert r.outcome is pf.Outcome.OK
        assert "managed node" in r.detail

    def test_without_the_managed_strategy_an_old_host_node_still_fails(self, monkeypatch):
        """The relaxation must not leak into the default path.

        Fails as: an old system node passes even when pyright would actually use
        it, and the run claims typecheck evidence it does not have.
        """
        monkeypatch.delenv("PYRIGHT_PYTHON_GLOBAL_NODE", raising=False)
        monkeypatch.setattr(pf, "node_major", lambda executable="node": 10)
        assert pf.check_node_for_pyright(require=True).outcome is pf.Outcome.VIOLATION
