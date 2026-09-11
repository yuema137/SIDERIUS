"""Composing ci_selection — the wrapper must not weaken its fail-closed contract."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import ClassVar

import pytest

from tools.ci import selection as sel

REPO = Path(__file__).resolve().parents[4]


class TestFailClosed:
    def test_no_changed_input_is_the_full_suite(self):
        """Absent diff information must never narrow.

        Fails as: a run with no diff silently executes a subset and reports
        green over tests it never ran.
        """
        s = sel.resolve_selection(REPO, None)
        assert s.full_suite and len(s.files) > 600

    def test_a_selector_crash_falls_back_to_the_full_suite(self, monkeypatch):
        """A crashing selector must make CI run MORE, never less.

        This mirrors tools/ci_selection/__main__.py, which catches BaseException
        for the same reason. Fails as: the exception propagates and the run dies,
        or worse, narrows.
        """
        import tools.ci_selection.resolver as resolver

        monkeypatch.setattr(
            resolver, "select", lambda changed: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        s = sel.resolve_selection(REPO, ["src/core/x.py"])
        assert s.full_suite and "failing closed" in s.reason

    def test_a_selection_expanding_to_zero_files_fails_closed(self, monkeypatch):
        """ "Run nothing" is the one answer worse than having no selector.

        A narrowed selection whose modules match no real test file would produce
        a confident green over an empty run. Fails as: files is empty and
        full_suite is False.
        """
        import tools.ci_selection.resolver as resolver

        class _R:
            full_suite: ClassVar[bool] = False
            modules: ClassVar[set[str]] = {"tests/unit/does_not_exist/"}

            def describe(self) -> str:
                return ""

        monkeypatch.setattr(resolver, "select", lambda changed: _R())
        s = sel.resolve_selection(REPO, ["src/core/x.py"])
        assert s.full_suite and s.files


class TestExpansion:
    def test_a_selected_directory_expands_to_its_test_files(self):
        """The planner needs files; the selector may answer with directories.

        Fails as: a directory is passed to the planner as a single unit, which
        would put a whole subtree in one shard.
        """
        universe = ["tests/unit/a/test_x.py", "tests/unit/a/test_y.py", "tests/unit/b/test_z.py"]
        assert sel._expand(REPO, ["tests/unit/a"], universe) == [
            "tests/unit/a/test_x.py",
            "tests/unit/a/test_y.py",
        ]

    def test_expansion_never_invents_a_file_outside_the_universe(self):
        """Only tracked test files may be scheduled.

        Fails as: a selected module names an untracked or deleted path and the
        harness tries to run it.
        """
        assert sel._expand(REPO, ["tests/unit/ghost/test_q.py"], ["tests/unit/a/test_x.py"]) == []

    def test_wrapper_preserves_the_resolvers_full_suite_reason(self):
        """A FULL verdict must still say which shared owner forced it.

        Fails as: the harness replaces causal selector evidence with a generic
        'full suite' summary, leaving CI operators unable to audit the choice.
        """
        result = sel.resolve_selection(REPO, ["src/agent/schemas/hyperparam_tuning.py"])
        assert result.full_suite
        assert "declared hub (src/agent/schemas/)" in result.reason


class TestChangedPathTransport:
    def test_json_handoff_preserves_rename_before_and_after_paths(self, tmp_path):
        """The harness must consume both sides of a rename.

        Fails as: JSON transport drops the deleted before-path and qualifies a
        rename only from its destination.
        """
        path = tmp_path / "changed.json"
        path.write_text('["old/name.py", "new/name.py", "old/name.py"]', encoding="utf-8")
        assert sel.load_changed_paths(path) == ["old/name.py", "new/name.py"]

    def test_legacy_newline_handoff_remains_readable(self, tmp_path):
        path = tmp_path / "changed.txt"
        ordinary = "docs/arch" + "itecture.md"
        path.write_text(f"README.md\n{ordinary}\n", encoding="utf-8")
        assert sel.load_changed_paths(path) == ["README.md", ordinary]

    def test_real_cli_and_wrapper_agree_on_named_readme_owners(self, tmp_path):
        """Exercise the actual subprocess boundary, not only helper functions.

        Fails as: the CLI parses a different changed set than the harness or
        either boundary drops a named document reader.
        """
        import json
        import os

        output = tmp_path / "github_output"
        changed = tmp_path / "changed.json"
        env = {**os.environ, "GITHUB_OUTPUT": str(output)}
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.ci_selection",
                "--name-status-z",
                "--write-paths-json",
                str(changed),
            ],
            cwd=REPO,
            env=env,
            input=b"M\0README.md\0",
            capture_output=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr.decode()
        assert json.loads(changed.read_text(encoding="utf-8")) == ["README.md"]
        cli_output = output.read_text(encoding="utf-8")
        wrapper = sel.resolve_selection(REPO, sel.load_changed_paths(changed))
        for owner in (
            "tests/unit/tools/test_md_links.py",
            "tests/unit/tools/test_user_contract_docs_census.py",
        ):
            assert owner in cli_output
            assert owner in wrapper.files
        assert not wrapper.full_suite
        assert "README.md:" in wrapper.reason

    def test_malformed_cli_input_emits_full_without_a_partial_handoff(self, tmp_path):
        """A truncated rename record must increase coverage, not crash CI."""
        import os

        output = tmp_path / "github_output"
        changed = tmp_path / "changed.json"
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.ci_selection",
                "--name-status-z",
                "--write-paths-json",
                str(changed),
            ],
            cwd=REPO,
            env={**os.environ, "GITHUB_OUTPUT": str(output)},
            input=b"R100\0old.py\0",
            capture_output=True,
            check=False,
        )
        assert proc.returncode == 0
        assert "full_suite=true" in output.read_text(encoding="utf-8")
        assert "failing closed" in proc.stderr.decode()
        assert not changed.exists()

    def test_harness_invalid_json_runs_the_full_plan(self, tmp_path):
        """The execution seam must fail closed when its handoff is corrupt."""
        import json

        changed = tmp_path / "changed.json"
        changed.write_text("[not-json", encoding="utf-8")
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.ci",
                "plan",
                "--root",
                str(REPO),
                "--changed-from",
                str(changed),
                "--by-count",
                "--shards",
                "1",
            ],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout)["full_suite"] is True
        assert "changed-file input raised" in proc.stderr


class TestOneAuthority:
    def test_the_wrapper_holds_no_mapping_of_its_own(self):
        """A second changed-files->tests mapping would be the P7 violation.

        This module must delegate every selection decision. Fails as: someone
        adds a path->test table here, and the repository has two selectors that
        can disagree.
        """
        src = Path(sel.__file__).read_text(encoding="utf-8")
        assert "from tools.ci_selection.resolver import select" in src
        for token in ("MANIFEST", "PATH_MAP", "HUBS", "OWNERS"):
            assert token not in src, f"{token} suggests a second selection authority"


@pytest.mark.parametrize("changed", [[], None])
def test_empty_and_none_both_mean_full_suite(changed):
    """An empty list must not be mistaken for a valid narrow selection.

    Fails as: `[]` is treated as "nothing changed, run nothing".
    """
    assert sel.resolve_selection(REPO, changed).full_suite
