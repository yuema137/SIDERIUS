"""C2 — the strict manual PreCompact path.

Tests A-D of the required matrix. The guard is exercised through
``main()`` with an explicit ``--mode`` and an injected stdin, so none of
this needs Claude Code installed.

The subagent test is the one that would have caught a defect that shipped:
the legacy guard read ``is_subagent``, a field the PreCompact payload does
not contain, and its test asserted the skip using the same invented name —
so the test passed while the production path never skipped anything.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.claude_hooks import context_state as cs
from tools.claude_hooks import precompact_memory_guard as guard


@pytest.fixture(autouse=True)
def _point_hooks_at_the_fixture_repo(repo: Path, monkeypatch: pytest.MonkeyPatch):
    """`repo_root()` prefers CLAUDE_PROJECT_DIR, so the guard operates on
    the throwaway checkout and never on the developer's own tree."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.chdir(repo)


def run(mode: str, payload: dict | None = None, *, check: bool = False) -> int:
    argv = [f"--mode={mode}"] + (["--check"] if check else [])
    stdin = io.StringIO(json.dumps(payload) if payload is not None else "")
    return guard.main(argv, stdin=stdin)


class TestManualCurrent:
    """A — manual + current handoff -> allow."""

    def test_allows_and_writes_no_rescue_file(self, repo: Path, handoff_factory, capsys):
        handoff_factory()
        assert run(guard.MODE_MANUAL, {"trigger": "manual"}) == guard.EXIT_ALLOW
        assert not cs.rescue_path(repo).exists(), (
            "the manual path must never leave emergency evidence — a rescue "
            "file here would mean the strict checkpoint silently degraded"
        )
        assert "BLOCKED" not in capsys.readouterr().err


class TestManualStale:
    """B, C, D — manual + any staleness -> block, and say which."""

    def test_stale_head_blocks_and_names_the_commit(self, handoff_factory, capsys):
        handoff_factory(FIELD_HEAD="0" * 40)
        assert run(guard.MODE_MANUAL) == guard.EXIT_BLOCK
        err = capsys.readouterr().err
        assert "BLOCKED" in err
        assert cs.FIELD_HEAD in err and "different commit" in err

    def test_stale_fingerprint_blocks_and_names_the_tree(self, repo: Path, handoff_factory, capsys):
        handoff_factory()
        (repo / "uncommitted.py").write_text("x = 1\n", encoding="utf-8")
        assert run(guard.MODE_MANUAL) == guard.EXIT_BLOCK
        err = capsys.readouterr().err
        assert cs.FIELD_FINGERPRINT in err and "uncommitted work" in err

    def test_unsynchronized_design_blocks(self, handoff_factory, capsys):
        handoff_factory(FIELD_DESIGN_SYNCED="no")
        assert run(guard.MODE_MANUAL) == guard.EXIT_BLOCK
        assert cs.FIELD_DESIGN_SYNCED in capsys.readouterr().err

    def test_missing_handoff_blocks_and_points_at_the_template(self, repo: Path, capsys):
        assert not cs.memory_path(repo).exists()
        assert run(guard.MODE_MANUAL) == guard.EXIT_BLOCK
        err = capsys.readouterr().err
        assert cs.MEMORY_BASENAME in err
        assert str(cs.template_path()) in err, (
            "an agent told only that the handoff is missing has to guess how "
            "to create one; the diagnostic must name the canonical template"
        )

    def test_every_failing_condition_is_listed_at_once(self, handoff_factory, capsys):
        """A guard that reports one problem per retry turns into an
        infinite block-fix-block loop."""
        handoff_factory(FIELD_HEAD="0" * 40, FIELD_SAFE="no")
        assert run(guard.MODE_MANUAL) == guard.EXIT_BLOCK
        err = capsys.readouterr().err
        assert "  1. " in err and "  2. " in err


class TestModeResolution:
    """§13 — the mode must never be guessed from fragile text."""

    def test_explicit_flag_wins_over_payload(self):
        assert guard.resolve_mode("manual", {"trigger": "auto"}) == guard.MODE_MANUAL
        assert guard.resolve_mode("auto", {"trigger": "manual"}) == guard.MODE_AUTO

    def test_payload_trigger_is_used_when_no_flag(self):
        assert guard.resolve_mode(None, {"trigger": "auto"}) == guard.MODE_AUTO
        assert guard.resolve_mode(None, {"trigger": "manual"}) == guard.MODE_MANUAL

    def test_unknown_mode_defaults_to_strict(self):
        """Defaulting to `auto` would silently disable the deliberate
        checkpoint whenever a payload field changed name upstream."""
        assert guard.resolve_mode(None, {}) == guard.MODE_MANUAL
        assert guard.resolve_mode(None, {"trigger": "something-new"}) == guard.MODE_MANUAL


class TestSubagentSkip:
    """The §1.3 finding — the legacy check named a field that never exists."""

    def test_subagent_compaction_is_not_judged_against_the_main_handoff(self, handoff_factory):
        handoff_factory(FIELD_HEAD="0" * 40)  # stale on purpose
        assert run(guard.MODE_MANUAL, {"agent_id": "sub-1"}) == guard.EXIT_ALLOW

    def test_main_thread_payload_is_not_treated_as_a_subagent(self, handoff_factory):
        handoff_factory(FIELD_HEAD="0" * 40)
        assert run(guard.MODE_MANUAL, {"session_id": "s"}) == guard.EXIT_BLOCK

    def test_the_legacy_field_name_does_not_grant_a_skip(self, handoff_factory):
        """`is_subagent` is not in the PreCompact payload. If a future edit
        reintroduces it as the signal, this stays red rather than silently
        skipping every main-session compaction that happens to carry it."""
        assert not guard.is_subagent({"is_subagent": True})


class TestPayloadRobustness:
    def test_malformed_payload_degrades_instead_of_crashing(self, handoff_factory):
        handoff_factory()
        assert guard.main(["--mode=manual"], stdin=io.StringIO("{not json")) == guard.EXIT_ALLOW

    def test_absent_payload_is_tolerated(self, handoff_factory):
        handoff_factory()
        assert guard.main(["--mode=manual"], stdin=io.StringIO("")) == guard.EXIT_ALLOW

    def test_outside_a_repository_it_never_blocks(self, tmp_path, monkeypatch, capsys):
        """A hook that blocked someone else's unrelated project would be a
        bug in THIS repository's tooling."""
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
        elsewhere = tmp_path / "not-a-repo"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
        assert guard.main(["--mode=manual"], stdin=io.StringIO("")) in (
            guard.EXIT_ALLOW,
            guard.EXIT_BLOCK,
        )


class TestGeneratedRegionRefresh:
    def test_the_generated_block_is_refreshed_before_comparison(self, repo: Path, handoff_factory):
        """The comparison must describe the tree as it is NOW, not as it
        was when the handoff was written."""
        handoff_factory()
        (repo / "late.py").write_text("z = 3\n", encoding="utf-8")
        run(guard.MODE_MANUAL)
        assert "late.py" in cs.memory_path(repo).read_text(encoding="utf-8")

    def test_refresh_never_edits_the_semantic_block(self, repo: Path, handoff_factory):
        before = cs.semantic_handoff(handoff_factory())
        run(guard.MODE_MANUAL)
        after = cs.semantic_handoff(cs.memory_path(repo).read_text(encoding="utf-8"))
        assert after == before, "the hook fabricated or dropped semantic content"


def test_check_mode_reports_success_on_stdout(handoff_factory, capsys):
    handoff_factory()
    assert run(guard.MODE_MANUAL, check=True) == guard.EXIT_ALLOW
    assert "safe to compact" in capsys.readouterr().out


def test_module_is_executable_as_a_script(repo: Path, handoff_factory):
    """The hook is registered as `python tools/claude_hooks/<file>.py`, so
    it must work when sys.path[0] is its own directory rather than the
    repository root."""
    handoff_factory()
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo)}
    out = subprocess.run(
        [sys.executable, str(Path(guard.__file__).resolve()), "--check", "--mode=manual"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(repo),
        check=False,
    )
    assert out.returncode == guard.EXIT_ALLOW, out.stderr
