"""C5 — the PR-scoped lifecycle, enforced rather than described.

Test N of the required matrix, plus the branch-mismatch guard that makes
"a new PR does not inherit the old handoff" a mechanical fact.

The lifecycle this file pins:

    new PR authorized -> fresh contract -> fresh handoff -> implementation
      -> zero or more compact/resume cycles (SAME PR)
      -> READY FOR OPERATOR REVIEW -> CONTEXT STATE: CLOSED
      -> operator merge -> post-merge sync -> NEXT PR starts a NEW context
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.claude_hooks import context_state as cs
from tools.claude_hooks import init_pr_handoff

from .conftest import git


@pytest.fixture(autouse=True)
def _point_hooks_at_the_fixture_repo(repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.chdir(repo)


class TestFreshInitialization:
    """N — the template can represent ANY PR, carrying nothing forward."""

    def test_a_new_pr_inherits_no_identity_from_the_previous_one(self):
        first = cs.initialize_handoff(
            project="Alpha PR",
            primary_design="docs/alpha.md",
            base="a" * 40,
            branch="feat/alpha",
        )
        second = cs.initialize_handoff(
            project="Beta PR",
            primary_design="docs/beta.md",
            base="b" * 40,
            branch="feat/beta",
        )
        assert "Alpha PR" not in second
        assert "docs/alpha.md" not in second
        assert "feat/alpha" not in second
        assert "a" * 40 not in second
        assert "Beta PR" in second and "Alpha PR" in first

    def test_initialization_fills_identity_and_leaves_the_narrative_blank(self):
        """The agent must write its own objective. Pre-filling it would
        be the hook fabricating semantic content."""
        text = cs.initialize_handoff(
            project="Gamma PR", primary_design="docs/g.md", base="c" * 40, branch="feat/g"
        )
        handoff = cs.semantic_handoff(text)
        assert cs.read_field(handoff, cs.FIELD_PROJECT) == "Gamma PR"
        assert cs.context_state(handoff) == cs.STATE_ACTIVE
        assert "TODO" in cs.section_body(handoff, "## Current Objective")

    def test_a_fresh_handoff_is_not_yet_safe_to_compact(self, repo: Path):
        """Initialisation must not hand out a green light. The placeholders
        are unresolved, and the guard has to say so."""
        cs.atomic_write(
            cs.memory_path(repo),
            cs.initialize_handoff(
                project="Delta PR", primary_design="DESIGN.md", base="d" * 40, branch="feat/d"
            ),
        )
        problems = cs.validate(repo, cs.memory_path(repo).read_text(encoding="utf-8"))
        assert problems, "a template with unresolved placeholders must not validate"
        assert any(cs.FIELD_SAFE in p for p in problems)


class TestBranchMismatchGuard:
    """The carry-over failure, caught by state rather than by discipline."""

    def test_a_handoff_from_another_branch_is_rejected(self, repo: Path, handoff_factory):
        """THE lifecycle pin.

        Switching to a new PR's branch while the previous PR's handoff is
        still the active one is exactly how a new PR inherits old
        checkpoints and stop conditions. Nothing else in the validator
        notices: HEAD and fingerprint can both be perfectly current.
        """
        handoff_factory(FIELD_BRANCH="feat/the-previous-pr")
        problems = cs.validate(repo, cs.memory_path(repo).read_text(encoding="utf-8"))
        assert any("belongs to a different PR" in p for p in problems), problems
        assert any("init_pr_handoff" in p for p in problems), "the fix must be named"

    def test_the_matching_branch_passes(self, repo: Path, handoff_factory):
        handoff_factory(FIELD_BRANCH=cs.branch_name(repo))
        assert cs.validate(repo, cs.memory_path(repo).read_text(encoding="utf-8")) == []

    def test_a_detached_head_does_not_fire_it(self, repo: Path, handoff_factory):
        """Detached HEAD is a normal state during bisect or review; it is
        not evidence that the handoff belongs elsewhere."""
        handoff_factory(FIELD_BRANCH="feat/whatever")
        git(repo, "checkout", "-q", "--detach")
        problems = cs.validate(repo, cs.memory_path(repo).read_text(encoding="utf-8"))
        assert not any("belongs to a different PR" in p for p in problems)


class TestInitCommand:
    def test_it_refuses_to_clobber_an_active_handoff(self, repo: Path, handoff_factory, capsys):
        """Overwriting a live handoff destroys the state the whole system
        protects, and the usual reason for wanting to is having forgotten
        the previous PR is still open."""
        handoff_factory(FIELD_PROJECT="Still Running PR")
        code = init_pr_handoff.main(["--project", "New PR", "--design", "DESIGN.md"])
        assert code == 1
        err = capsys.readouterr().err
        assert "Still Running PR" in err and "still ACTIVE" in err

    def test_a_closed_context_is_told_that_force_is_appropriate(
        self, repo: Path, handoff_factory, capsys
    ):
        handoff_factory(FIELD_CONTEXT_STATE="CLOSED / AWAITING OPERATOR ACTION")
        assert init_pr_handoff.main(["--project", "New PR", "--design", "DESIGN.md"]) == 1
        assert "--force" in capsys.readouterr().err

    def test_force_replaces_the_handoff_with_the_new_pr_identity(
        self, repo: Path, handoff_factory, capsys
    ):
        handoff_factory(FIELD_PROJECT="Old PR")
        code = init_pr_handoff.main(["--project", "New PR", "--design", "DESIGN.md", "--force"])
        assert code == 0
        text = cs.memory_path(repo).read_text(encoding="utf-8")
        assert "New PR" in text and "Old PR" not in text

    def test_it_refuses_a_design_doc_that_does_not_exist(self, repo: Path, capsys):
        """The PRIMARY DESIGN DOC is the semantic authority. Initialising
        against a path that is not there produces a handoff pointing at
        nothing."""
        assert init_pr_handoff.main(["--project", "P", "--design", "docs/missing.md"]) == 1
        assert "does not exist" in capsys.readouterr().err

    def test_it_defaults_base_and_branch_to_the_checkout(self, repo: Path, capsys):
        (repo / "DESIGN.md").write_text("# design\n", encoding="utf-8")
        assert init_pr_handoff.main(["--project", "P", "--design", "DESIGN.md"]) == 0
        handoff = cs.semantic_handoff(cs.memory_path(repo).read_text(encoding="utf-8"))
        assert cs.read_field(handoff, cs.FIELD_BASE) == cs.head_sha(repo)
        assert cs.read_field(handoff, cs.FIELD_BRANCH) == cs.branch_name(repo)


class TestClosedContextIsTerminal:
    def test_closing_a_context_does_not_make_it_invalid(self, repo: Path, handoff_factory):
        """A CLOSED handoff must still validate: the operator may need to
        compact while waiting for a merge, and blocking then would be the
        same deadlock in a different costume."""
        handoff_factory(FIELD_CONTEXT_STATE="CLOSED / AWAITING OPERATOR ACTION")
        assert cs.validate(repo, cs.memory_path(repo).read_text(encoding="utf-8")) == []

    def test_an_unrecognised_state_is_reported(self, repo: Path, handoff_factory):
        handoff_factory(FIELD_CONTEXT_STATE="in progress-ish")
        problems = cs.validate(repo, cs.memory_path(repo).read_text(encoding="utf-8"))
        assert any(cs.FIELD_CONTEXT_STATE in p for p in problems)
