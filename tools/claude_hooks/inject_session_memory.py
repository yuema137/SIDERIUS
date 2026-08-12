#!/usr/bin/env python3
"""SessionStart: re-inject the ACTIVE PR's context and demand a re-audit.

SessionStart stdout is added to the model's context — unlike most hooks,
whose stdout only reaches a debug log. That is why recovery lives here.

**Everything injected is read from the repository at run time.** The
previous implementation hardcoded one initiative's recovery ladder
(a V21 priorities file and a specific PR document), so every resumed
session was pointed at work that had been finished for weeks. This module
contains no project, initiative, PR or design-document literal of any
kind: it reads them from the handoff, which is the only place that knows
which PR is active.

Three shapes of output, chosen deterministically:

    normal      the handoff validates -> inject the active PR, its
                design doc, the current checkpoint, next actions and
                stop conditions, plus the standing re-audit procedure.

    recovery    the handoff does NOT validate and an automatic-compaction
                rescue snapshot exists -> the same, preceded by a
                high-priority banner: the previous compaction happened
                over stale memory, so audit before editing.

    cold        no usable handoff -> generic recovery guidance. Never a
                fallback to some historical project path.

**Precedence is state-derived, not timestamp-derived.** A rescue snapshot
never forces recovery mode on its own: if the handoff validates clean
against the repository right now, the snapshot describes a situation that
has since been repaired, and normal mode is correct. Comparing file
mtimes would make resume behaviour depend on filesystem accidents.

Output is bounded: this competes for the same context window it is
trying to protect.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.claude_hooks.context_state import (
    FIELD_BASE,
    FIELD_BINDING_DOCS,
    FIELD_BRANCH,
    MAX_INJECTED_CHARS,
    MEMORY_BASENAME,
    STATE_CLOSED,
    ContinuityError,
    branch_name,
    head_sha,
    load_memory,
    read_field,
    read_pr_identity,
    repo_root,
    rescue_path,
    section_body,
    semantic_handoff,
    template_path,
    validate,
    working_tree_fingerprint,
)

#: Sections a resumed session actually needs. The rest of the handoff
#: stays on disk one Read away — injecting all of it crowds out the work.
INJECTED_SECTIONS: tuple[str, ...] = (
    "## Current Checkpoint",
    "## Exact Next Actions",
    "## Stop Conditions",
)

RECOVERY_PROCEDURE = """\
## MANDATORY RECOVERY PROCEDURE

Do not resume implementation solely from this handoff. It is a claim
written before the context was lost, not verified fact.

Before editing or executing implementation work:

1. verify branch, HEAD and the working-tree fingerprint against the
   repository;
2. read the PRIMARY DESIGN DOC named above — it is the semantic authority
   for the active PR, and its per-commit checklists say what has actually
   landed;
3. read the binding documents it names;
4. inspect the recent implementation commits;
5. inspect the current diff;
6. audit the relevant producer-to-consumer code path;
7. compare repository evidence with this handoff;
8. correct the handoff AND the design document wherever they disagree;
9. only then continue autonomous execution.

If the handoff and the repository conflict, the repository is
authoritative.
"""

AUTO_COMPACT_BANNER = """\
## AUTO-COMPACT RECOVERY MODE

The semantic handoff was stale at compact time.

Do not edit immediately.

Recover:
  git/branch/HEAD/status/diff/process truth
  active design
  handoff
  emergency mechanical snapshot
  transcript tail if available

Then reconcile the live design + handoff before implementation continues.
"""

CLOSED_CONTEXT_NOTICE = """\
## THIS PR'S CONTEXT IS CLOSED

The handoff above records a PR that has reached its stop condition. It is
history, not an instruction to continue.

Do NOT resume its implementation, and do NOT append new work to it.

Starting the next PR is a separate, operator-authorized step:

  new PR authorized
    -> fresh Implementation Working Rules contract
    -> fresh handoff initialised from
       {template}
    -> implementation

Continuity is intra-PR. What the previous PR did is read from merged
repository and design state, not from this file.
"""

COLD_START = """\
## No usable session handoff

`{basename}` is not available or cannot be parsed: {reason}

Treat this session as having NO carried-over state.

Before making any change:

1. establish repository truth — branch, HEAD, status, recent commits,
   current diff;
2. find the governing design document for the work you are asked to do,
   and read it before editing;
3. if you are starting a new PR, initialise a handoff from
   {template};
4. do not infer an active task from this message — it says only that no
   handoff was found.
"""


def _read_event(stream: object = None) -> dict:
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


def _live_state(root: Path) -> str:
    try:
        return (
            "```text\n"
            f"branch      {branch_name(root)}\n"
            f"head        {head_sha(root)}\n"
            f"fingerprint {working_tree_fingerprint(root)}\n"
            "```"
        )
    except ContinuityError:
        return "```text\n(repository state unavailable)\n```"


def _identity_block(handoff: str) -> str:
    identity = read_pr_identity(handoff)
    rows = [
        ("PROJECT / PR", identity.project),
        ("PRIMARY DESIGN DOC", identity.primary_design),
        ("RELATED / BINDING DOCS", read_field(handoff, FIELD_BINDING_DOCS)),
        ("IMPLEMENTATION BASE", read_field(handoff, FIELD_BASE)),
        ("IMPLEMENTATION BRANCH", read_field(handoff, FIELD_BRANCH)),
        ("CONTEXT STATE", identity.state),
    ]
    body = "\n".join(f"{name}: {value or '(not recorded)'}" for name, value in rows)
    return f"## Active PR\n\n```text\n{body}\n```"


def build_injection(root: Path, source: str, *, event: dict | None = None) -> str:
    """The full text SessionStart prints. Pure apart from reading files."""
    event = event or {}
    try:
        text = load_memory(root)
    except ContinuityError as exc:
        return COLD_START.format(basename=MEMORY_BASENAME, reason=exc, template=template_path())

    try:
        handoff = semantic_handoff(text)
    except ContinuityError as exc:
        return COLD_START.format(basename=MEMORY_BASENAME, reason=exc, template=template_path())

    problems = validate(root, text)
    identity = read_pr_identity(handoff)
    snapshot = rescue_path(root)

    # State-derived precedence: a snapshot only matters while the handoff
    # is still not current. Once it validates, the situation the snapshot
    # describes has been repaired.
    recovery_mode = bool(problems) and snapshot.is_file()

    parts: list[str] = [f"# Session context ({source or 'unknown'} start)", ""]
    if recovery_mode:
        parts += [AUTO_COMPACT_BANNER, f"Mechanical snapshot: `{snapshot}`", ""]

    parts += ["Live repository state at injection time:", "", _live_state(root), ""]
    parts += [_identity_block(handoff), ""]

    if problems:
        listed = "\n".join(f"  - {p}" for p in problems)
        parts += [
            "WARNING — this handoff did NOT validate against the current "
            "repository. Treat every claim in it as suspect and re-audit "
            "first. Failing conditions:\n" + listed,
            "",
        ]
    else:
        parts += ["This handoff validated clean against the current repository state.", ""]

    if identity.state == STATE_CLOSED:
        parts += [CLOSED_CONTEXT_NOTICE.format(template=template_path()), ""]

    for heading in INJECTED_SECTIONS:
        body = section_body(handoff, heading)
        if body:
            parts += [heading, "", body, ""]

    parts += [RECOVERY_PROCEDURE, "", f"Full handoff: `{MEMORY_BASENAME}` (read it directly)."]
    out = "\n".join(parts)
    if len(out) > MAX_INJECTED_CHARS:
        out = (
            out[:MAX_INJECTED_CHARS] + f"\n\n[... truncated at {MAX_INJECTED_CHARS} characters. "
            f"Read {MEMORY_BASENAME} directly for the remainder ...]\n"
        )
    return out


def main(argv: list[str] | None = None, *, stdin: object = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    event = _read_event(stdin)
    source = str(event.get("source", "")) or (argv[0] if argv else "")

    try:
        root = repo_root()
    except ContinuityError:
        return 0  # not this repository — inject nothing

    print(build_injection(root, source, event=event))
    return 0


if __name__ == "__main__":
    sys.exit(main())
