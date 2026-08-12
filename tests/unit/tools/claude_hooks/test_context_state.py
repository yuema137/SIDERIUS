"""C1 — the tracked continuity foundation.

Each test names a defect only it can catch. The three that carry the most
weight are the fingerprint-scope pair (a mechanism that cannot see its own
source is blind, and one that sees its own bookkeeping deadlocks) and the
fresh-checkout template lookup (the audited §1.7 defect: the guard treats
an unreadable template as a hard block, and all of `.claude/` is
gitignored).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tools.claude_hooks import context_state as cs

from .conftest import git


class TestFingerprintScope:
    """§10 of the authorization — the fingerprint's blind spots are chosen."""

    def test_clean_tree_is_the_empty_digest_at_every_commit(self, repo: Path):
        """A clean tree yields ONE constant, independent of HEAD.

        Documented rather than incidental: it is why HEAD comparison is a
        separate check. A guard relying on the fingerprint alone would
        call two different clean commits identical.
        """
        first = cs.working_tree_fingerprint(repo)
        (repo / "another.md").write_text("x\n", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "second")
        assert cs.working_tree_fingerprint(repo) == first
        assert cs.head_sha(repo) != ""

    def test_tracked_hook_source_edits_change_the_fingerprint(self, repo: Path):
        """THE anti-blindness pin (mutation M-C9).

        If `tools/claude_hooks/**` were excluded, the continuity system
        could rewrite its own behaviour without ever invalidating a
        handoff — the exact blindness this system exists to remove.
        """
        before = cs.working_tree_fingerprint(repo)
        target = repo / "tools" / "claude_hooks" / "context_state.py"
        target.parent.mkdir(parents=True)
        target.write_text("# tracked hook source\n", encoding="utf-8")
        assert cs.working_tree_fingerprint(repo) != before

    def test_runtime_state_does_not_invalidate_the_handoff(self, repo: Path):
        """The self-reference contract.

        Writing the handoff, or dropping an emergency snapshot, must not
        change the fingerprint the handoff records — otherwise the guard
        could never be satisfied and every session would deadlock.
        """
        before = cs.working_tree_fingerprint(repo)
        cs.atomic_write(cs.memory_path(repo), "# handoff\n")
        cs.atomic_write(cs.rescue_path(repo), "# snapshot\n")
        assert cs.working_tree_fingerprint(repo) == before

    def test_exclusion_holds_without_gitignore_rules(self, repo: Path):
        """The exclusion lives in the algorithm, not in `.gitignore`.

        A checkout that does not ignore `.claude/` must not deadlock, so
        the skip cannot rely on the path being absent from git's listing.
        """
        (repo / ".gitignore").write_text("", encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "stop ignoring .claude")
        before = cs.working_tree_fingerprint(repo)
        cs.atomic_write(cs.rescue_path(repo), "# snapshot\n")
        assert cs.working_tree_fingerprint(repo) == before


class TestTemplateLookup:
    """§1.7 — the audited fresh-checkout defect must not come back."""

    def test_template_resolves_beside_the_module_not_under_dot_claude(self):
        path = cs.template_path()
        assert path.is_file(), f"canonical template missing at {path}"
        assert ".claude" not in path.parts, (
            "the canonical template resolved into .claude/, which is gitignored — "
            "a fresh checkout would get the guard without its template and every "
            "compaction would block (mutation M-C8)"
        )
        assert path.parent.name == cs.TEMPLATE_DIRNAME
        assert path.parent.parent.name == "claude_hooks"

    def test_guard_functions_in_a_checkout_with_no_dot_claude(self, tmp_path: Path):
        """Test Q — the fresh-checkout proof.

        Copies the tracked implementation into a bare tree containing NO
        `.claude/` at all and proves the first-principles comparison still
        resolves its template.
        """
        fresh = tmp_path / "fresh"
        (fresh / "tools").mkdir(parents=True)
        shutil.copytree(Path(cs.__file__).resolve().parent, fresh / "tools" / "claude_hooks")
        assert not (fresh / ".claude").exists()

        template = cs.template_path().read_text(encoding="utf-8")
        ok, detail = cs.first_principles_match_template(template)
        assert ok, detail

    def test_template_carries_the_markers_a_handoff_needs(self):
        text = cs.template_path().read_text(encoding="utf-8")
        for marker in (
            cs.FIRST_PRINCIPLES_BEGIN,
            cs.FIRST_PRINCIPLES_END,
            cs.SEMANTIC_BEGIN,
            cs.SEMANTIC_END,
            cs.GENERATED_BEGIN,
            cs.GENERATED_END,
        ):
            assert marker in text, f"template is missing {marker}"

    def test_template_declares_every_required_field(self):
        """A template that cannot satisfy the validator is a trap: the
        agent fills it in faithfully and the guard still blocks."""
        handoff = cs.semantic_handoff(cs.template_path().read_text(encoding="utf-8"))
        for field in cs.REQUIRED_FIELDS:
            assert cs.read_field(handoff, field) is not None, f"template omits '{field}:'"
        for heading in cs.REQUIRED_HEADINGS:
            assert heading in handoff, f"template omits '{heading}'"


class TestPRIdentityParsing:
    """The PR-scoped lifecycle is only enforceable if identity parses."""

    def test_closeout_wording_classifies_as_closed(self):
        """`CLOSED / AWAITING OPERATOR ACTION` is the documented closeout
        wording. A parser that only matched a bare `CLOSED` would treat a
        finished PR as active and invite the next PR to resume it."""
        assert cs.context_state("CONTEXT STATE: CLOSED / AWAITING OPERATOR ACTION") == "CLOSED"
        assert cs.context_state("CONTEXT STATE: ACTIVE") == "ACTIVE"

    def test_unrecognised_state_is_not_silently_active(self):
        assert cs.context_state("CONTEXT STATE: paused") is None
        assert cs.context_state("nothing here") is None

    def test_identity_reports_placeholders_as_absent(self):
        """A template copied but not filled in must not look like a real
        PR identity — otherwise resume points at `TODO`."""
        identity = cs.read_pr_identity(
            "PROJECT / PR: TODO\nPRIMARY DESIGN DOC: docs/x.md\nCONTEXT STATE: ACTIVE\n"
        )
        assert identity.project is None
        assert identity.primary_design == "docs/x.md"
        assert identity.is_active


class TestFieldParsing:
    def test_duplicate_field_is_reported_not_silently_first_wins(self, repo, handoff_factory):
        """`read_field` returns the FIRST match, so a second copy is
        invisible. That is how a stale value survives an edit that
        "fixed" the later one."""
        text = handoff_factory()
        stale = text.replace(
            "## Current Objective",
            f"{cs.FIELD_SAFE}: no\n\n## Current Objective",
            1,
        )
        cs.atomic_write(cs.memory_path(repo), stale)
        problems = cs.validate(repo, stale)
        assert any("declared 2 times" in p for p in problems), problems

    def test_field_must_be_its_own_line(self):
        """Prose mentioning a key must not satisfy the guard."""
        assert cs.read_field("we discuss Safe to compact: maybe in passing", cs.FIELD_SAFE) is None


class TestValidation:
    def test_a_freshly_filled_template_validates(self, repo, handoff_factory):
        """The end-to-end contract: template -> fill -> green.

        If this fails, every new PR's kickoff is blocked on day one.
        """
        text = handoff_factory()
        assert cs.validate(repo, text) == []

    def test_stale_head_is_named(self, repo, handoff_factory):
        text = handoff_factory(FIELD_HEAD="0" * 40)
        problems = cs.validate(repo, cs.memory_path(repo).read_text(encoding="utf-8"))
        assert any(cs.FIELD_HEAD in p and "different commit" in p for p in problems), problems
        assert text  # the factory wrote it

    def test_stale_fingerprint_is_named(self, repo, handoff_factory):
        handoff_factory()
        (repo / "new_work.py").write_text("x = 1\n", encoding="utf-8")
        problems = cs.validate(repo, cs.memory_path(repo).read_text(encoding="utf-8"))
        assert any(cs.FIELD_FINGERPRINT in p and "uncommitted work" in p for p in problems)

    def test_missing_pr_identity_is_a_failure(self, repo, handoff_factory):
        """Without PR identity a handoff cannot belong to one PR, which is
        the whole lifecycle contract."""
        text = handoff_factory()
        stripped = text.replace(f"{cs.FIELD_PROJECT}: ", "PROJECT-ish: ", 1)
        problems = cs.validate(repo, stripped)
        assert any(cs.FIELD_PROJECT in p for p in problems), problems

    def test_design_doc_that_does_not_exist_is_named(self, repo, handoff_factory):
        """A handoff naming a missing design doc points the resumed
        session at nothing — the one authority it must read."""
        handoff_factory(FIELD_PRIMARY_DESIGN="docs/design/nope.md")
        problems = cs.validate(repo, cs.memory_path(repo).read_text(encoding="utf-8"))
        assert any("does not exist in the repository" in p for p in problems), problems

    def test_all_failures_are_reported_together(self, repo, handoff_factory):
        """One problem at a time turns into an infinite block-fix-block
        loop, so the validator must return the full set."""
        handoff_factory(FIELD_HEAD="0" * 40, FIELD_SAFE="no")
        problems = cs.validate(repo, cs.memory_path(repo).read_text(encoding="utf-8"))
        assert len(problems) >= 2

    @pytest.mark.parametrize("marker", [cs.SEMANTIC_BEGIN, cs.GENERATED_BEGIN])
    def test_missing_markers_short_circuit(self, repo, handoff_factory, marker):
        text = handoff_factory().replace(marker, "")
        problems = cs.validate(repo, text)
        assert problems and all("missing" in p for p in problems)


class TestGeneratedRegion:
    def test_only_the_generated_region_is_replaced(self, repo, handoff_factory):
        """The hooks own exactly one region. A writer that touched the
        semantic block would be fabricating memory."""
        text = handoff_factory()
        rendered = cs.render_generated_state(repo, session_id="s", trigger="auto")
        swapped = cs.replace_generated_state(text, rendered)
        assert cs.semantic_handoff(swapped) == cs.semantic_handoff(text)
        assert cs.first_principles(swapped) == cs.first_principles(text)
        assert "head_sha             " in swapped

    def test_generated_state_reports_the_live_tree(self, repo, handoff_factory):
        handoff_factory()
        (repo / "dirty.py").write_text("y = 2\n", encoding="utf-8")
        rendered = cs.render_generated_state(repo)
        assert cs.head_sha(repo) in rendered
        assert cs.working_tree_fingerprint(repo) in rendered
        assert "dirty.py" in rendered
