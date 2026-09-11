#!/usr/bin/env python3
"""Initialise the context handoff for a NEW pull request.

Run this once, at the start of a PR, before implementation begins:

    ./.venv/bin/python tools/claude_hooks/init_pr_handoff.py \\
        --project "Widget refactor (PR 42)" \\
        --design  docs/design/development/widget_refactor.md

Everything except the PR identity is left at its template placeholder on
purpose. The agent fills in its own objective, checkpoints and stop
conditions; inheriting someone else's is the failure this command exists
to prevent.

**It refuses to overwrite an existing handoff unless --force is given.**
Clobbering a live handoff would destroy the very state the system is
meant to protect, and the common case for wanting to is having forgotten
that the previous PR's context is still open. Close it first.
"""

from __future__ import annotations

import argparse
import sys

from tools.claude_hooks.context_state import (
    MEMORY_BASENAME,
    STATE_CLOSED,
    ContinuityError,
    atomic_write,
    branch_name,
    context_state,
    head_sha,
    initialize_handoff,
    load_memory,
    memory_path,
    read_pr_identity,
    repo_root,
    semantic_handoff,
)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialise a PR-scoped context handoff.")
    parser.add_argument("--project", required=True, help="the PR's name, as a human would say it")
    parser.add_argument(
        "--design", required=True, help="repository-relative path to the PRIMARY DESIGN DOC"
    )
    parser.add_argument("--binding-docs", default="", help="other binding documents, comma listed")
    parser.add_argument(
        "--base", default="", help="implementation base SHA (default: current HEAD)"
    )
    parser.add_argument("--branch", default="", help="implementation branch (default: current)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing handoff (destroys the current PR's context)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    try:
        root = repo_root()
    except ContinuityError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    target = memory_path(root)
    if target.exists() and not args.force:
        try:
            identity = read_pr_identity(semantic_handoff(load_memory(root)))
            state = context_state(semantic_handoff(load_memory(root)))
        except ContinuityError:
            identity, state = None, None
        existing = identity.project if identity and identity.project else "(unnamed)"
        note = (
            "It is already CLOSED, so overwriting is probably what you want — re-run with --force."
            if state == STATE_CLOSED
            else "It is still ACTIVE. Close that PR's context before starting a new one."
        )
        print(
            f"refusing to overwrite {MEMORY_BASENAME}: it holds the handoff for "
            f"{existing!r}. {note}",
            file=sys.stderr,
        )
        return 1

    design = args.design
    if not (root / design).is_file():
        print(
            f"error: --design {design!r} does not exist. The PRIMARY DESIGN DOC is the "
            f"semantic authority for the PR; create it first.",
            file=sys.stderr,
        )
        return 1

    text = initialize_handoff(
        project=args.project,
        primary_design=design,
        base=args.base or head_sha(root),
        branch=args.branch or branch_name(root),
        binding_docs=args.binding_docs,
    )
    atomic_write(target, text)
    print(
        f"initialised {MEMORY_BASENAME} for {args.project!r}.\n"
        f"Fill in the remaining sections before the first compaction — the guard "
        f"blocks on unresolved placeholders."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
