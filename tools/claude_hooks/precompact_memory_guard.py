#!/usr/bin/env python3
"""PreCompact guard — strict when deliberate, fail-safe when automatic.

Compaction is the last deterministic boundary before context is lost, so
this is where the handoff is checked. It is emphatically NOT where the
handoff is written: the hook owns one region (the generated repository
state) and validates the rest.

Two modes, because the two compactions mean different things:

    manual   the operator or the agent asked for a checkpoint. A stale
             handoff is a reason to STOP and synchronize — nothing is
             lost by refusing, because nobody is mid-emergency.

    auto     Claude Code ran out of room. Blocking here does not buy a
             synchronized handoff; it fails the current request and
             leaves the session with no way forward — which is exactly
             the deadlock this tool exists to remove. So the automatic
             path NEVER blocks on a stale handoff. It writes mechanical
             rescue evidence to the gitignored runtime directory and
             lets compaction proceed.

Neither path ever writes semantic content. The strict path refuses and
says what to fix; the fail-safe path records what a shell process can
know for certain and says plainly that the handoff may be wrong.

Mode resolution, in order:

    1. an explicit ``--mode {manual,auto}`` argument, so the tracked code
       is testable without Claude Code installed;
    2. the PreCompact payload's ``trigger`` field, which Claude Code
       2.1.228 sets to "manual" or "auto" and also uses as the matcher
       key;
    3. ``manual`` — the strict path is the safe default when the mode is
       unknown.

Exit codes:
    0  compaction proceeds
    2  stale or incomplete; compaction is blocked and stderr says exactly
       what to fix

Subagent compactions are ignored: a subagent has its own context and must
not be judged against the main session's handoff.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Import through the repository root so the module has ONE identity
# whether this file is executed as a script or imported by tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.claude_hooks import rescue_snapshot
from tools.claude_hooks.context_state import (
    MEMORY_BASENAME,
    ContinuityError,
    atomic_write,
    load_memory,
    memory_path,
    render_generated_state,
    replace_generated_state,
    repo_root,
    template_path,
    validate,
)

MODE_MANUAL = "manual"
MODE_AUTO = "auto"

VALIDATE_COMMAND = "./.venv/bin/python tools/claude_hooks/precompact_memory_guard.py --check"

EXIT_ALLOW = 0
EXIT_BLOCK = 2


def read_event(stream: object = None) -> dict:
    """Parse the hook payload, tolerating an absent or malformed one.

    A malformed payload must not crash the guard into allowing
    compaction — it degrades to "no session metadata", and validation
    still runs.
    """
    source = stream if stream is not None else sys.stdin
    try:
        raw = source.read()  # type: ignore[attr-defined]
    except (OSError, ValueError, AttributeError):
        return {}
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def is_subagent(event: dict) -> bool:
    """Whether this compaction belongs to a subagent.

    Claude Code 2.1.228 signals this with ``agent_id`` (and ``agent_type``,
    documented as "Present when the hook fires from within a subagent").
    There is no ``is_subagent`` field in the hook payload — the previous
    implementation looked for one and therefore never skipped anything.
    """
    return bool(event.get("agent_id") or event.get("agent_type"))


def resolve_mode(explicit: str | None, event: dict) -> str:
    if explicit in (MODE_MANUAL, MODE_AUTO):
        return explicit
    trigger = str(event.get("trigger", "")).strip().lower()
    return MODE_AUTO if trigger == MODE_AUTO else MODE_MANUAL


def instructions() -> str:
    return (
        "Do this, then retry compact:\n"
        "  1. update the PRIMARY DESIGN DOC named in the handoff, and its\n"
        "     implementation ledger;\n"
        f"  2. update {MEMORY_BASENAME} — PR identity, decisions, audits,\n"
        "     problems, deviations, validation already done, and the exact\n"
        "     next actions;\n"
        "  3. record the current HEAD and working-tree fingerprint in the\n"
        "     freshness fields (run the command below to see both);\n"
        "  4. set 'Design document synchronized: yes' and 'Safe to compact:\n"
        "     yes' only if that is actually true — knowingly setting either\n"
        "     falsely is a workflow violation;\n"
        "  5. retry.\n\n"
        f"Starting a NEW pull request? Do not edit the old handoff — copy\n"
        f"{template_path()} over {MEMORY_BASENAME} and fill it in for the new\n"
        f"PR. Continuity is intra-PR; merged design documents carry state\n"
        f"between PRs.\n\n"
        f"Validate locally without compacting:\n    {VALIDATE_COMMAND}\n"
    )


def _fail_safe(
    root: Path,
    *,
    event: dict,
    handoff_text: str | None,
    problems: list[str],
    reason: str,
) -> int:
    """Automatic compaction over a stale handoff: record, then ALLOW.

    A snapshot failure is reported but never converted into a block. The
    entire purpose of this path is that an automatic compaction cannot
    deadlock; trading one deadlock for another because the rescue file
    could not be written would defeat it. The operator still sees the
    failure on stderr.
    """
    try:
        path = rescue_snapshot.write(
            root, event=event, handoff_text=handoff_text, problems=problems
        )
        where = str(path)
    except (ContinuityError, OSError) as exc:
        print(
            f"[precompact] AUTO compaction proceeding, but the rescue snapshot "
            f"could not be written: {exc}. Repository state is unrecorded — "
            f"audit git truth before editing after this compaction.",
            file=sys.stderr,
        )
        return EXIT_ALLOW

    print(
        f"[precompact] AUTO compaction proceeding over a handoff that is not "
        f"current ({reason}). Mechanical rescue evidence written to {where}. "
        f"It is evidence, not memory: after compaction, audit git truth and "
        f"the PRIMARY DESIGN DOC before editing anything.",
        file=sys.stderr,
    )
    return EXIT_ALLOW


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, add_help=True)
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate without reading a hook payload and without compacting",
    )
    parser.add_argument(
        "--mode",
        choices=(MODE_MANUAL, MODE_AUTO),
        default=None,
        help="override the compaction mode instead of reading it from the payload",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, *, stdin: object = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    event = {} if args.check else read_event(stdin)

    # A subagent's compaction is its own business. Judging it against the
    # main session's handoff would block work the handoff does not describe.
    if is_subagent(event):
        return EXIT_ALLOW

    mode = resolve_mode(args.mode, event)

    try:
        root = repo_root()
    except ContinuityError as exc:
        print(f"[precompact] {exc}", file=sys.stderr)
        return EXIT_ALLOW  # not our repository — never block someone else's work

    try:
        text = load_memory(root)
    except ContinuityError as exc:
        if mode == MODE_AUTO:
            return _fail_safe(
                root,
                event=event,
                handoff_text=None,
                problems=[str(exc)],
                reason="the handoff could not be read",
            )
        print(
            f"BLOCKED: compaction would lose this session's state.\n\n{exc}\n\n{instructions()}",
            file=sys.stderr,
        )
        return EXIT_BLOCK

    # Refresh the generated block FIRST, so the freshness comparison below
    # reports on the tree as it is right now. This touches only the
    # generated region; semantic content is byte-preserved.
    try:
        refreshed = replace_generated_state(
            text,
            render_generated_state(
                root,
                session_id=str(event.get("session_id", "")),
                trigger=mode,
            ),
        )
        if refreshed != text:
            atomic_write(memory_path(root), refreshed)
        text = refreshed
    except ContinuityError as exc:
        if mode == MODE_AUTO:
            return _fail_safe(
                root,
                event=event,
                handoff_text=text,
                problems=[str(exc)],
                reason="the handoff is malformed",
            )
        print(
            f"BLOCKED: {MEMORY_BASENAME} is malformed and cannot be refreshed.\n\n"
            f"{exc}\n\n{instructions()}",
            file=sys.stderr,
        )
        return EXIT_BLOCK

    problems = validate(root, text)
    if not problems:
        if args.check:
            print(f"[precompact] {MEMORY_BASENAME} is complete and current — safe to compact.")
        return EXIT_ALLOW

    if mode == MODE_AUTO:
        return _fail_safe(
            root,
            event=event,
            handoff_text=text,
            problems=problems,
            reason=f"{len(problems)} freshness condition(s) failed",
        )

    numbered = "\n".join(f"  {i}. {p}" for i, p in enumerate(problems, start=1))
    print(
        f"BLOCKED: compaction would lose this session's state.\n\n"
        f"{MEMORY_BASENAME} is not current. Every failing condition:\n\n{numbered}\n\n"
        f"{instructions()}",
        file=sys.stderr,
    )
    return EXIT_BLOCK


if __name__ == "__main__":
    sys.exit(main())
