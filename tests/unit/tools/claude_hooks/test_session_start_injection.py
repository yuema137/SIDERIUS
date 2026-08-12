"""C4 — SessionStart resolves the ACTIVE PR dynamically.

Tests H, I, J, K, L, M and R of the required matrix.

R (zero historical hardcoding) is the one that would have caught the
audited defect directly: the previous injector named a V21 priorities
ledger and a specific finished PR, so every resumed session was pointed
at work that had been merged weeks earlier.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from tools.claude_hooks import context_state as cs
from tools.claude_hooks import inject_session_memory as inject
from tools.claude_hooks import rescue_snapshot

#: Literals from the audited implementation, plus historical PR names.
#: Production hook OUTPUT must contain none of them.
HISTORICAL_LITERALS = (
    "v21_priorities",
    "pr_c_generated_model_production_compat",
    "v19_priorities",
    "v20_priorities",
    "step_00_golden_baseline_harness",
    "step_01_proposer_hypothesis_space",
)


@pytest.fixture(autouse=True)
def _point_hooks_at_the_fixture_repo(repo: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.chdir(repo)


def render(repo: Path, source: str = "compact", event: dict | None = None) -> str:
    return inject.build_injection(repo, source, event=event or {})


class TestNormalResume:
    """H — a clean handoff injects the active PR, dynamically."""

    def test_injects_the_pr_identity_from_the_handoff(self, repo: Path, handoff_factory):
        handoff_factory(FIELD_PROJECT="Widget Refactor PR 7")
        out = render(repo)
        assert "Widget Refactor PR 7" in out
        assert "DESIGN.md" in out
        assert "validated clean" in out

    def test_injects_checkpoint_next_actions_and_stop_conditions(self, repo: Path, handoff_factory):
        """These three are what a resumed session acts on. Injecting the
        identity alone would leave it knowing WHICH PR but not what to do."""
        handoff_factory()
        out = render(repo)
        for heading in inject.INJECTED_SECTIONS:
            assert heading in out, f"{heading} was not injected"

    def test_does_not_dump_the_entire_handoff(self, repo: Path, handoff_factory):
        """The injection competes for the window it is protecting."""
        text = handoff_factory()
        out = render(repo)
        assert len(out) < len(text), "injection is not smaller than the file it summarises"
        assert "## Audits Performed and Evidence Found" not in out

    def test_output_is_bounded(self, repo: Path, handoff_factory):
        handoff_factory()
        assert len(render(repo)) <= cs.MAX_INJECTED_CHARS + 200


class TestZeroHistoricalHardcoding:
    """R — no project/initiative/PR literal may survive in the hooks."""

    @pytest.mark.parametrize("literal", HISTORICAL_LITERALS)
    def test_injected_output_contains_no_historical_literal(
        self, repo: Path, handoff_factory, literal
    ):
        handoff_factory()
        assert literal not in render(repo)

    @pytest.mark.parametrize("literal", HISTORICAL_LITERALS)
    def test_tracked_hook_source_contains_no_historical_literal(self, literal):
        """Mutation M-C5 inserts one; this goes red.

        Scans the implementation and the shipped template — not this test
        file, which necessarily names them to forbid them.
        """
        hook_dir = Path(cs.__file__).resolve().parent
        for path in sorted(hook_dir.rglob("*")):
            if path.is_file() and path.suffix in {".py", ".md"}:
                assert literal not in path.read_text(encoding="utf-8"), (
                    f"{path.name} hardcodes {literal!r} — a resumed session would be "
                    f"pointed at a specific historical project instead of the active PR"
                )

    def test_the_template_names_no_specific_pr(self):
        """N — the canonical template must be able to represent ANY PR."""
        text = cs.template_path().read_text(encoding="utf-8")
        assert "SIDERIUS Context Continuity" not in text
        assert "PROJECT / PR: TODO" in text


class TestAutoCompactRecoveryMode:
    """I and J — the banner appears when it should, and only then."""

    def test_stale_handoff_plus_snapshot_triggers_recovery_mode(self, repo: Path, handoff_factory):
        handoff_factory(FIELD_HEAD="0" * 40)
        rescue_snapshot.write(repo, event={}, handoff_text=None, problems=["stale"])
        out = render(repo)
        assert "AUTO-COMPACT RECOVERY MODE" in out
        assert str(cs.rescue_path(repo)) in out
        assert "Do not edit immediately" in out

    def test_a_clean_handoff_outranks_an_existing_snapshot(self, repo: Path, handoff_factory):
        """J — the precedence pin (mutation M-C6).

        A rescue file left over from a previous incident must not force
        every future session into emergency mode forever. Precedence is
        state-derived: once the handoff validates, the situation the
        snapshot describes has been repaired.
        """
        handoff_factory()
        rescue_snapshot.write(repo, event={}, handoff_text=None, problems=["old incident"])
        assert cs.rescue_path(repo).is_file()
        out = render(repo)
        assert "AUTO-COMPACT RECOVERY MODE" not in out
        assert "validated clean" in out

    def test_stale_handoff_without_a_snapshot_warns_but_does_not_claim_a_rescue(
        self, repo: Path, handoff_factory
    ):
        handoff_factory(FIELD_HEAD="0" * 40)
        out = render(repo)
        assert "WARNING" in out
        assert "AUTO-COMPACT RECOVERY MODE" not in out


class TestClosedContext:
    """M — a finished PR must not read as an instruction to continue."""

    def test_closed_context_says_a_new_pr_needs_a_fresh_kickoff(self, repo: Path, handoff_factory):
        handoff_factory(FIELD_CONTEXT_STATE="CLOSED / AWAITING OPERATOR ACTION")
        out = render(repo)
        assert "THIS PR'S CONTEXT IS CLOSED" in out
        assert "fresh Implementation Working Rules contract" in out
        assert str(cs.template_path()) in out

    def test_active_context_gets_no_closed_notice(self, repo: Path, handoff_factory):
        handoff_factory()
        assert "THIS PR'S CONTEXT IS CLOSED" not in render(repo)


class TestColdStart:
    """K — no usable handoff must not crash, and must not invent a task."""

    def test_missing_handoff_gives_generic_guidance(self, repo: Path):
        out = render(repo)
        assert "No usable session handoff" in out
        assert str(cs.template_path()) in out
        assert "do not infer an active task" in out.lower()

    @pytest.mark.parametrize("literal", HISTORICAL_LITERALS)
    def test_cold_start_does_not_fall_back_to_a_historical_path(self, repo: Path, literal):
        assert literal not in render(repo)

    def test_malformed_handoff_is_treated_as_cold_not_as_a_crash(self, repo: Path):
        cs.atomic_write(cs.memory_path(repo), "garbage with no markers\n")
        out = render(repo)
        assert "No usable session handoff" in out


class TestPRIdentityContinuity:
    """L — compact/resume stays inside the same PR."""

    def test_repeated_resumes_report_the_same_pr_and_design(self, repo: Path, handoff_factory):
        handoff_factory(FIELD_PROJECT="Stable PR Name")
        first = render(repo, "compact")
        second = render(repo, "resume")
        for out in (first, second):
            assert "Stable PR Name" in out
            assert "DESIGN.md" in out

    def test_the_session_source_is_reported(self, repo: Path, handoff_factory):
        handoff_factory()
        assert "compact start" in render(repo, "compact")
        assert "startup start" in render(repo, "startup")


class TestEntryPoint:
    def test_main_prints_and_exits_zero(self, repo: Path, handoff_factory, capsys):
        handoff_factory()
        payload = json.dumps({"source": "resume", "session_id": "s1"})
        assert inject.main([], stdin=io.StringIO(payload)) == 0
        assert "Active PR" in capsys.readouterr().out

    def test_source_comes_from_the_payload(self, repo: Path, handoff_factory, capsys):
        """The audited implementation drained stdin and ignored it, so it
        could not tell a fresh startup from a post-compact resume."""
        handoff_factory()
        inject.main([], stdin=io.StringIO(json.dumps({"source": "clear"})))
        assert "clear start" in capsys.readouterr().out

    def test_malformed_payload_does_not_crash(self, repo: Path, handoff_factory, capsys):
        handoff_factory()
        assert inject.main([], stdin=io.StringIO("{broken")) == 0
        assert capsys.readouterr().out.strip()
