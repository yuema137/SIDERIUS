"""Composing ci_selection — the wrapper must not weaken its fail-closed contract."""

from __future__ import annotations

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
        s = sel.resolve_selection(REPO, ["core/x.py"])
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
        s = sel.resolve_selection(REPO, ["core/x.py"])
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
