"""Compose ``tools.ci_selection`` — never re-implement it.

``tools.ci_selection`` answers **WHAT should run**. This module is the only
place the harness asks it, and it adds nothing: it calls the same ``select()``
the workflow calls, then expands the selected modules into the concrete test
files the shard planner needs.

Fail-closed, matching the selector's own contract
(``tools/ci_selection/__main__.py``): any exception, any unmapped result, any
empty selection for a non-empty diff resolves to the FULL suite. A selector able
to answer "run nothing" is worse than no selector, because it produces a
confident green — so the same reasoning binds this wrapper.
"""

from __future__ import annotations

import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Selection:
    """What this run should execute, and why."""

    files: tuple[str, ...]
    full_suite: bool
    reason: str


def all_test_files(root: Path) -> list[str]:
    """Tracked unit-test files, from git.

    ``git ls-files`` rather than a filesystem walk: a walk picks up untracked
    scratch and stale artifacts, so two runs on the same SHA could disagree
    about what the suite even is.
    """
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "tests/unit/"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return sorted(f for f in out if Path(f).name.startswith("test_") and f.endswith(".py"))


def _expand(root: Path, modules: Iterable[str], universe: Sequence[str]) -> list[str]:
    """Turn selected modules (files or directories) into concrete test files."""
    selected: set[str] = set()
    for module in modules:
        normalized = module.rstrip("/")
        if normalized.endswith(".py"):
            if normalized in universe:
                selected.add(normalized)
            continue
        prefix = normalized + "/"
        selected.update(f for f in universe if f.startswith(prefix))
    return sorted(selected)


def resolve_selection(root: Path, changed: Sequence[str] | None) -> Selection:
    """Ask the existing authority which files this run should execute.

    Args:
        root: execution root.
        changed: changed paths, as ``git diff --name-only`` emits. ``None``
            means "no diff information", which is the full suite.

    Returns:
        A :class:`Selection`. ``full_suite`` is True whenever the harness could
        not narrow safely — which is every ambiguous case, by design.
    """
    universe = all_test_files(root)
    if not changed:
        return Selection(tuple(universe), True, "no changed-file input — full suite")

    try:
        from tools.ci_selection.resolver import select

        result = select(list(changed))
    except BaseException as exc:  # deliberate, mirrors the selector's own wrapper
        return Selection(
            tuple(universe), True, f"selector raised {type(exc).__name__}: {exc} — failing closed"
        )

    if result.full_suite or not result.modules:
        return Selection(tuple(universe), True, "selector chose the full suite")

    files = _expand(root, result.modules, universe)
    if not files:
        # The selector narrowed, but nothing expanded to a real test file. That
        # is exactly the "run nothing" answer its docstring calls the one
        # failure mode worse than having no selector.
        return Selection(
            tuple(universe), True, "selection expanded to zero test files — failing closed"
        )
    return Selection(tuple(files), False, f"selected {len(files)} of {len(universe)} test files")
