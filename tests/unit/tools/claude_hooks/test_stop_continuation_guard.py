"""The Stop guard: continue unfinished work, release control when due.

Each test below names a defect that only it catches. The guard has
exactly two ways to be wrong, and they are not symmetric:

    blocks when it should not   -> the session cannot hand back control,
                                   which is the only failure that can
                                   trap an operator
    allows when it should not   -> the operator types "continue", which
                                   is the status quo this work removes

So the allow-side cases (C-G) are the safety property and the block-side
cases (A, B) are the feature. Both are covered, and the loop-safety pair
covers the one way a Stop hook becomes unusable.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from tests.unit.tools.claude_hooks.conftest import git, set_field
from tools.claude_hooks import context_state as cs
from tools.claude_hooks import stop_continuation_guard as guard

NEXT_ACTIONS_HEADING = "## Exact Next Actions"


def _decide(repo: Path, text: str | None, *, last_block: dict | None = None) -> cs.StopDecision:
    """Decide against the fixture repository's real git state."""
    return cs.decide_stop(
        text,
        branch=cs.branch_name(repo),
        head=cs.head_sha(repo),
        fingerprint=cs.working_tree_fingerprint(repo),
        last_block=last_block,
    )


def _set_section(text: str, heading: str, body: str) -> str:
    """Replace a ``## Heading`` section's body, keeping the rest byte-identical."""
    marker = f"\n{heading}\n"
    start = text.index(marker) + len(marker)
    rest = text[start:]
    for line in rest.splitlines(keepends=True):
        if line.startswith("#"):
            stop = start + rest.index(line)
            break
    else:  # pragma: no cover - the template always has a following heading
        stop = len(text)
    return text[:start] + f"\n{body}\n\n" + text[stop:]


# ---------------------------------------------------------------------
# A / B — the feature: unfinished autonomous work keeps going
# ---------------------------------------------------------------------


def test_active_work_with_next_actions_blocks_the_stop(repo, handoff_factory):
    """Case A. The exact shape observed during Step 03: ACTIVE PR,
    incomplete checkpoint, listed next actions, nothing owed by the
    operator — and the turn ended anyway.

    Fails when: the guard stops keying on ACTIVE + next actions, i.e.
    the premature-stop failure returns unnoticed.
    """
    text = handoff_factory()

    decision = _decide(repo, text)

    assert decision.allow is False
    assert decision.code == cs.CONTINUE_WORK_INCOMPLETE
    assert "no operator decision is required" in decision.reason


def test_completed_checkpoint_still_blocks_while_a_milestone_remains(repo, handoff_factory):
    """Case B. A checkpoint finishing is not the PR finishing.

    The guard deliberately does NOT read '## Current Checkpoint' prose —
    a checkpoint that says COMPLETE while next actions still list the
    following milestone must still block. This test fails if anyone
    "improves" the guard by letting checkpoint prose end the turn.
    """
    text = handoff_factory()
    text = _set_section(text, "## Current Checkpoint", "CHECKPOINT B COMPLETE — committed 1234abc.")
    text = _set_section(
        text, NEXT_ACTIONS_HEADING, "1. Start Checkpoint C: wire the bounded step cap."
    )
    cs.atomic_write(cs.memory_path(repo), text)

    decision = _decide(repo, text)

    assert decision.allow is False
    assert decision.code == cs.CONTINUE_WORK_INCOMPLETE


# ---------------------------------------------------------------------
# C-F — the safety property: legitimate stops still work
# ---------------------------------------------------------------------


def test_closed_awaiting_operator_action_allows_the_stop(repo, handoff_factory):
    """Case C. The documented closeout wording — READY FOR OPERATOR
    REVIEW is recorded as ``CLOSED / AWAITING OPERATOR ACTION``.

    Fails when: reaching the PR's stop condition no longer releases
    control, which would make every finished PR unreportable.
    """
    text = handoff_factory(FIELD_CONTEXT_STATE="CLOSED / AWAITING OPERATOR ACTION")

    decision = _decide(repo, text)

    assert decision.allow is True
    assert decision.code == cs.STOP_CLOSED


def test_plain_closed_state_allows_the_stop(repo, handoff_factory):
    """Case D. ``CLOSED`` with no operator suffix is the same verdict.

    Fails when: the CLOSED classification starts depending on the suffix
    an agent happened to write.
    """
    text = handoff_factory(FIELD_CONTEXT_STATE="CLOSED")

    assert _decide(repo, text).code == cs.STOP_CLOSED


def test_operator_input_required_allows_the_stop(repo, handoff_factory):
    """Case E. A genuine blocker mid-PR: work is ACTIVE and next actions
    exist, but they cannot proceed until the operator decides.

    This is the ONLY lever that releases control without closing the
    context, so it is the one the guard must honour. Fails when the
    field stops being read — and the symptom would be an agent unable to
    ask its question.
    """
    text = handoff_factory()
    text = set_field(text, cs.FIELD_OPERATOR_INPUT, "yes")
    cs.atomic_write(cs.memory_path(repo), text)

    decision = _decide(repo, text)

    assert decision.allow is True
    assert decision.code == cs.STOP_OPERATOR_INPUT


def test_no_recorded_next_actions_allows_the_stop(repo, handoff_factory):
    """Case F, part 1. Nothing left to do is not something to continue.

    Fails when: the 'NONE' declaration stops being recognised and a
    finished context blocks on its own emptiness.
    """
    text = handoff_factory()
    text = _set_section(text, NEXT_ACTIONS_HEADING, "**NONE — this context is closed.**")
    cs.atomic_write(cs.memory_path(repo), text)

    decision = _decide(repo, text)

    assert decision.allow is True
    assert decision.code == cs.STOP_NO_NEXT_ACTIONS


def test_no_handoff_at_all_allows_the_stop(repo):
    """Case F, part 2. No active task means no state to continue.

    Fails when: an ordinary conversation in a repository with no handoff
    starts refusing to end.
    """
    decision = _decide(repo, None)

    assert decision.allow is True
    assert decision.code == cs.STOP_NO_STATE


# ---------------------------------------------------------------------
# G — malformed state must never deadlock
# ---------------------------------------------------------------------


def test_missing_semantic_markers_allow_the_stop(repo):
    """Case G, part 1. A truncated or hand-mangled handoff is
    uninterpretable, and uninterpretable means allow.

    Fails when: a partially written handoff can trap the session.
    """
    decision = _decide(repo, "# not a handoff at all\n")

    assert decision.allow is True
    assert decision.code == cs.STOP_UNREADABLE


def test_unrecognisable_context_state_allows_the_stop(repo, handoff_factory):
    """Case G, part 2. A CONTEXT STATE that is neither ACTIVE nor CLOSED
    is not evidence of active work.

    Fails when: an unparseable state is silently treated as ACTIVE,
    which would block on a value nobody can interpret.
    """
    text = handoff_factory(FIELD_CONTEXT_STATE="MAYBE?")

    decision = _decide(repo, text)

    assert decision.allow is True
    assert decision.code == cs.STOP_UNREADABLE


def test_repeated_block_without_progress_allows_the_stop(repo, handoff_factory):
    """Case G, part 3 — THE loop-safety property.

    A continuation that changes nothing must not be blocked a second
    time at the same repository state. Without this, an agent that
    genuinely has nothing to do would be pinned until Claude Code's own
    consecutive-block cap fired.

    Fails when: the ledger comparison is dropped or compares the wrong
    fields, and the guard becomes an infinite Stop loop.
    """
    text = handoff_factory()
    ledger = {
        "head": cs.head_sha(repo),
        "fingerprint": cs.working_tree_fingerprint(repo),
    }

    decision = _decide(repo, text, last_block=ledger)

    assert decision.allow is True
    assert decision.code == cs.STOP_NO_PROGRESS


def test_block_resumes_once_the_working_tree_moves(repo, handoff_factory):
    """The other half of loop safety: real progress re-arms the guard.

    Without this test, a guard that simply allowed every stop after its
    first block would pass the loop-safety test above and silently do
    nothing for the rest of the session.
    """
    text = handoff_factory()
    stale = {"head": cs.head_sha(repo), "fingerprint": "0" * 64}

    decision = _decide(repo, text, last_block=stale)

    assert decision.allow is False
    assert decision.code == cs.CONTINUE_WORK_INCOMPLETE


# ---------------------------------------------------------------------
# H — the active state is read dynamically, never remembered
# ---------------------------------------------------------------------


def test_handoff_for_another_branch_allows_the_stop(repo, handoff_factory):
    """Case H, part 1. Continuity is intra-PR: a handoff naming a
    different branch is the previous PR's context, and its next actions
    are not this checkout's work.

    Fails when: the lifecycle guard is dropped and a finished PR's
    handoff starts driving a new branch's session.
    """
    text = handoff_factory(FIELD_BRANCH="feat/some-other-pr")

    decision = _decide(repo, text)

    assert decision.allow is True
    assert decision.code == cs.STOP_OTHER_PR


def test_continuation_message_quotes_the_current_handoff_not_a_remembered_one(
    repo, handoff_factory
):
    """Case H, part 2 — the defect that already happened once here.

    ``inject_session_memory`` used to hardcode one initiative's recovery
    ladder, so every resumed session was pointed at finished work. This
    proves the Stop guard reads whichever handoff is on disk RIGHT NOW:
    two different next-action bodies must produce two different
    continuation messages.

    Fails when: any project, PR, path or checkpoint literal is baked
    into the guard.
    """
    first = _set_section(handoff_factory(), NEXT_ACTIONS_HEADING, "1. Land the dtype contract.")
    cs.atomic_write(cs.memory_path(repo), first)
    message_one = guard.continuation_message(_decide(repo, first), cs.semantic_handoff(first))

    second = _set_section(first, NEXT_ACTIONS_HEADING, "1. Bound the Gate-2 step count.")
    cs.atomic_write(cs.memory_path(repo), second)
    message_two = guard.continuation_message(_decide(repo, second), cs.semantic_handoff(second))

    assert "Land the dtype contract." in message_one
    assert "Bound the Gate-2 step count." in message_two
    assert "Land the dtype contract." not in message_two


# ---------------------------------------------------------------------
# Reachability — production actually calls the decision
# ---------------------------------------------------------------------


def test_hook_main_emits_the_block_payload_and_records_the_ledger(
    repo, handoff_factory, monkeypatch, capsys
):
    """The guard is only real if the HOOK path produces it.

    Everything above tests ``decide_stop`` directly. This drives
    ``main()`` exactly as Claude Code does — event JSON on stdin — and
    asserts the wire contract Claude Code parses. It fails if the hook
    stops calling the decision, emits the wrong keys, or forgets to
    record the ledger that makes the next stop loop-safe.
    """
    handoff_factory()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))

    rc = guard.main(
        [], stdin=io.StringIO(json.dumps({"session_id": "s-1", "stop_hook_active": False}))
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["decision"] == "block"
    assert "Continue with the recorded next actions." in payload["reason"]

    ledger = json.loads(cs.stop_ledger_path(repo).read_text(encoding="utf-8"))
    assert ledger["head"] == cs.head_sha(repo)
    assert ledger["fingerprint"] == cs.working_tree_fingerprint(repo)


def test_hook_main_stays_silent_when_the_stop_is_legitimate(
    repo, handoff_factory, monkeypatch, capsys
):
    """A permitted stop must print NOTHING on stdout.

    Claude Code parses stdout as the hook's decision; any stray output
    on the allow path risks being read as one. Fails if a diagnostic is
    ever moved from stderr to stdout.
    """
    handoff_factory(FIELD_CONTEXT_STATE="CLOSED")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))

    rc = guard.main([], stdin=io.StringIO("{}"))

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_hook_allows_the_stop_outside_a_repository(tmp_path, monkeypatch, capsys):
    """A hook that cannot find the repository must not block.

    Fails when: a git failure or a non-repository cwd turns into a
    blocked turn nobody can clear.
    """
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    rc = guard.main([], stdin=io.StringIO("{}"))

    assert rc == 0
    assert capsys.readouterr().out == ""


def test_unreadable_ledger_does_not_block_the_guard(repo):
    """A corrupt ledger weakens the guard by one block, never deadlocks.

    Fails when: ledger parsing raises instead of degrading, which would
    make every Stop event crash the hook.
    """
    path = cs.stop_ledger_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    assert guard.read_ledger(path) is None


def test_template_declares_the_operator_input_field(repo):
    """A new PR must start with the field the guard reads.

    Fails when: the template loses the declaration and every freshly
    initialised handoff silently has no way to hand control back short
    of closing the context.
    """
    template = cs.template_path().read_text(encoding="utf-8")

    assert cs.read_field(cs.semantic_handoff(template), cs.FIELD_OPERATOR_INPUT) == "no"


def test_git_fixture_is_untouched_by_the_guard(repo, handoff_factory):
    """The guard reads state; it never commits, stages or reverts.

    Fails when: a future 'helpful' guard starts mutating the repository
    it is supposed to observe.
    """
    text = handoff_factory()
    before = git(repo, "status", "--porcelain")

    _decide(repo, text)

    assert git(repo, "status", "--porcelain") == before
