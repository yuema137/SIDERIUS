#!/usr/bin/env python3
"""Stop: refuse to end the turn while recorded work is unfinished.

The observed failure, repeatedly, during a long implementation session:
an ACTIVE PR, an incomplete checkpoint, explicit next actions, nothing
waiting on the operator — and the turn ends anyway at an ordinary
milestone ("Next: Checkpoint C…"), so the operator has to type
"continue". Autonomous execution that pauses at every milestone is not
autonomous execution.

This hook decides nothing about the work. It reads
:func:`~tools.claude_hooks.context_state.decide_stop`, which reads the
handoff, and blocks only the one combination that is unambiguously
premature:

```text
CONTEXT STATE: ACTIVE
+ this checkout is the handoff's branch
+ '## Exact Next Actions' lists something
+ 'Operator input required' is not yes
   -> block, and quote the recorded next actions
anything else                        -> allow
```

**It never authors semantics.** The continuation message is a fixed
sentence; the agent re-reads its own handoff for what to do. A hook that
summarised the work would be the same failure as trusting a compaction
summary — plausible text nobody verified.

**It fails safe, three ways.** Any unreadable, malformed, missing or
foreign state allows the stop. A block is recorded with the repository
state it happened at, and an identical state next time allows the stop —
so a continuation that changes nothing can never loop. And Claude Code
caps consecutive blocks at 8 (``CLAUDE_CODE_STOP_HOOK_BLOCK_CAP``)
independently of anything here.

Registered per machine, like the other hooks in this directory; see
``docs/development/claude_context_continuity.md``.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.claude_hooks.context_state import (
    ContinuityError,
    StopDecision,
    atomic_write,
    branch_name,
    decide_stop,
    head_sha,
    load_memory,
    repo_root,
    section_body,
    semantic_handoff,
    stop_ledger_path,
    working_tree_fingerprint,
)


def _read_event(stream: object = None) -> dict[str, Any]:
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


def read_ledger(path: Path) -> dict[str, Any] | None:
    """The state recorded at the previous block, or None.

    Unreadable is treated as absent: the ledger only ever weakens the
    guard (it converts a repeat block into an allow), so failing to read
    it can cost one extra block, never a deadlock.
    """
    try:
        if not path.is_file():
            return None
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def write_ledger(path: Path, *, head: str, fingerprint: str, session_id: str) -> None:
    """Record the state this block happened at. Best-effort by design."""
    payload = {
        "head": head,
        "fingerprint": fingerprint,
        "session_id": session_id,
    }
    # A guard that crashes on a full disk is worse than one that repeats a
    # block: the ledger only ever weakens the decision.
    with contextlib.suppress(OSError):
        atomic_write(path, json.dumps(payload, indent=2) + "\n")


def continuation_message(decision: StopDecision, handoff: str) -> str:
    """The blocking reason, plus the agent's OWN recorded next actions.

    The next actions are quoted verbatim from the handoff rather than
    restated. Bounded, because this text enters the model's context.
    """
    parts = [decision.reason]
    body = section_body(handoff, "## Exact Next Actions")
    if body:
        parts += ["", "Recorded next actions:", "", body[:4000]]
    parts += [
        "",
        "If this is wrong — the work really is finished, or a genuine "
        "operator decision is outstanding — record that in "
        "before_end_memory.md (CONTEXT STATE, or 'Operator input "
        "required: yes') rather than stopping against the recorded state.",
    ]
    return "\n".join(parts)


def evaluate(root: Path) -> tuple[StopDecision, str, str, str]:
    """Resolve repository truth and decide. Returns (decision, handoff, head, fingerprint)."""
    try:
        text: str | None = load_memory(root)
    except ContinuityError:
        text = None

    head = head_sha(root)
    fingerprint = working_tree_fingerprint(root)
    decision = decide_stop(
        text,
        branch=branch_name(root),
        head=head,
        fingerprint=fingerprint,
        last_block=read_ledger(stop_ledger_path(root)),
    )
    handoff = ""
    if text:
        try:
            handoff = semantic_handoff(text)
        except ContinuityError:
            handoff = ""
    return decision, handoff, head, fingerprint


def main(argv: list[str] | None = None, *, stdin: object = None) -> int:
    event = _read_event(stdin)

    try:
        root = repo_root()
        decision, handoff, head, fingerprint = evaluate(root)
    except ContinuityError as exc:
        # Not this repository, or git is unavailable. Never block on a
        # state we could not establish.
        print(f"[stop-guard] allowing stop: {exc}", file=sys.stderr)
        return 0

    if decision.allow:
        print(f"[stop-guard] allowing stop: {decision.code}", file=sys.stderr)
        return 0

    write_ledger(
        stop_ledger_path(root),
        head=head,
        fingerprint=fingerprint,
        session_id=str(event.get("session_id", "")),
    )
    print(
        json.dumps(
            {"decision": "block", "reason": continuation_message(decision, handoff)},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
