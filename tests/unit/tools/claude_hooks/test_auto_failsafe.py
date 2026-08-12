"""C3 — automatic compaction must never deadlock, and never fabricate.

Tests E, F and G of the required matrix.

The pair that matters most: F proves the automatic path ALLOWS while
recording real state, and G proves what it records is evidence rather
than a summary. Either one alone would be satisfiable by a bad
implementation — an auto path that always allows and writes nothing
passes F's exit-code half; a snapshot full of invented prose passes F
entirely.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from tools.claude_hooks import context_state as cs
from tools.claude_hooks import precompact_memory_guard as guard
from tools.claude_hooks import rescue_snapshot


@pytest.fixture(autouse=True)
def _point_hooks_at_the_fixture_repo(repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.chdir(repo)


def run_auto(payload: dict | None = None) -> int:
    stdin = io.StringIO(json.dumps(payload if payload is not None else {"trigger": "auto"}))
    return guard.main(["--mode=auto"], stdin=stdin)


class TestAutoCurrent:
    """E — auto + current handoff -> allow, and no rescue file."""

    def test_allows_without_writing_a_snapshot(self, repo: Path, handoff_factory):
        handoff_factory()
        assert run_auto() == guard.EXIT_ALLOW
        assert not cs.rescue_path(repo).exists(), (
            "a snapshot on a CURRENT handoff would train the reader to ignore "
            "rescue files, which is how the real one gets missed"
        )


class TestAutoStale:
    """F — auto + stale handoff -> allow anyway, with real evidence."""

    def test_stale_handoff_does_not_block(self, repo: Path, handoff_factory):
        """THE central behaviour change (mutation M-C3).

        Blocking here is what left the previous session unable to compact
        and unable to repair, requiring a separate rescue session.
        """
        handoff_factory(FIELD_HEAD="0" * 40)
        assert run_auto() == guard.EXIT_ALLOW

    def test_snapshot_is_written_and_carries_live_repository_state(
        self, repo: Path, handoff_factory
    ):
        """Mutation M-C4 removes the write; this goes red."""
        handoff_factory(FIELD_HEAD="0" * 40)
        (repo / "work_in_progress.py").write_text("x = 1\n", encoding="utf-8")
        run_auto({"trigger": "auto", "session_id": "sess-42", "transcript_path": "/tmp/t.jsonl"})

        text = cs.rescue_path(repo).read_text(encoding="utf-8")
        assert cs.head_sha(repo) in text, "snapshot must record the ACTUAL head"
        assert cs.working_tree_fingerprint(repo) in text
        assert "work_in_progress.py" in text, "snapshot must record uncommitted work"
        assert "sess-42" in text and "/tmp/t.jsonl" in text
        assert "0" * 40 in text, "snapshot must record the handoff's own stale value"

    def test_snapshot_names_the_failing_conditions(self, handoff_factory, repo: Path):
        handoff_factory(FIELD_HEAD="0" * 40)
        run_auto()
        text = cs.rescue_path(repo).read_text(encoding="utf-8")
        assert cs.FIELD_HEAD in text and "different commit" in text

    def test_snapshot_carries_the_active_pr_identity_verbatim(self, handoff_factory, repo: Path):
        """Resume needs to know WHICH PR was interrupted. Copied verbatim
        from the handoff and labelled unverified — never re-derived."""
        handoff_factory(FIELD_HEAD="0" * 40, FIELD_PROJECT="Some Active PR")
        run_auto()
        text = cs.rescue_path(repo).read_text(encoding="utf-8")
        assert "Some Active PR" in text
        assert "unverified" in text.lower()

    def test_missing_handoff_still_allows_and_still_records(self, repo: Path):
        """The worst case — no handoff at all — is exactly when mechanical
        evidence matters most, and exactly when blocking helps least."""
        assert not cs.memory_path(repo).exists()
        assert run_auto() == guard.EXIT_ALLOW
        assert cs.rescue_path(repo).exists()

    def test_malformed_handoff_still_allows_and_still_records(self, repo: Path):
        cs.atomic_write(cs.memory_path(repo), "# not a handoff at all\n")
        assert run_auto() == guard.EXIT_ALLOW
        assert cs.rescue_path(repo).exists()

    def test_snapshot_failure_does_not_convert_into_a_block(
        self, repo: Path, handoff_factory, monkeypatch, capsys
    ):
        """Trading one deadlock for another because a file could not be
        written would defeat the entire fail-safe."""
        handoff_factory(FIELD_HEAD="0" * 40)

        def boom(*_args, **_kwargs):
            raise OSError("disk on fire")

        monkeypatch.setattr(rescue_snapshot, "write", boom)
        assert run_auto() == guard.EXIT_ALLOW
        assert "could not be written" in capsys.readouterr().err


class TestSnapshotHygiene:
    """G — the snapshot is evidence, not memory."""

    def test_it_contains_no_fabricated_narrative_sections(self, repo: Path, handoff_factory):
        """A hook cannot author semantic memory. If a future edit adds a
        'what was in progress' section, this fires."""
        handoff_factory(FIELD_HEAD="0" * 40)
        run_auto()
        text = cs.rescue_path(repo).read_text(encoding="utf-8").lower()
        for forbidden in (
            "## summary",
            "## next steps",
            "## what was in progress",
            "## implementation intent",
            "## diagnosis",
            "## decisions",
        ):
            assert forbidden not in text, f"snapshot fabricated a semantic section: {forbidden}"

    def test_it_says_plainly_that_it_is_not_memory(self, repo: Path, handoff_factory):
        handoff_factory(FIELD_HEAD="0" * 40)
        run_auto()
        text = cs.rescue_path(repo).read_text(encoding="utf-8")
        assert "mechanical evidence only" in text
        assert "Do not infer unfinished implementation semantics" in text

    def test_it_declares_a_schema_version(self, repo: Path, handoff_factory):
        """An unversioned artefact read by a future implementation is a
        guess. This is the one field that makes the rest interpretable."""
        handoff_factory(FIELD_HEAD="0" * 40)
        run_auto()
        assert rescue_snapshot.SCHEMA in cs.rescue_path(repo).read_text(encoding="utf-8")

    def test_writing_it_cannot_invalidate_the_handoff(self, repo: Path, handoff_factory):
        """The snapshot lives under the self-referential exclusion, so
        recording staleness never CREATES staleness."""
        handoff_factory()
        before = cs.working_tree_fingerprint(repo)
        rescue_snapshot.write(repo, event={}, handoff_text=None, problems=[])
        assert cs.working_tree_fingerprint(repo) == before


class TestManualIsUnaffected:
    def test_manual_still_blocks_on_the_same_stale_state(self, repo: Path, handoff_factory):
        """The two paths must not converge. If a refactor made manual
        fail-safe too, the deliberate checkpoint would be gone."""
        handoff_factory(FIELD_HEAD="0" * 40)
        stdin = io.StringIO(json.dumps({"trigger": "manual"}))
        assert guard.main(["--mode=manual"], stdin=stdin) == guard.EXIT_BLOCK
        assert not cs.rescue_path(repo).exists()
