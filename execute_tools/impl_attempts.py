"""Per-implementation-attempt layout inside a proposal attempt directory.

arXiv-readiness S2 / U6 (#256). The implement→validate retry loop used to
reuse ONE storage per proposal attempt, so every retry overwrote the
previous implementor record, validation record, plugin ``.py``, test
``.py``, ``description.md`` and loss ``.py`` — a documented PR-E limitation
(``pr_e_proposal_scale_funnel.md`` §0.C). Every retry now persists in its
own directory NESTED under the proposal attempt:

```text
{iter_dir}/attempt_{NNN}_{model}/
    proposal_{run}.json              proposal stage — attempt level, unchanged
    impl_001/                        implement→validate attempt 1
        implementor_{run}.json
        validation_{run}.json
        models/{model}.py  models/{model}/description.md
        tests/test_{model}.py  losses/{loss}.py
    impl_002/ ...                    retry 2, distinct files, nothing overwritten
```

Nested rather than sibling on purpose: the funnel's duplicate-identity
seam (``funnel_assembly.DuplicateIdConflict``) treats one ``candidate_id``
in two *attempt* directories as a collision, and under O-E-4 the retries
ARE one candidate. Readers consume the **terminal** attempt — the highest
index — through :func:`stage_artifact_dir`, which falls back to the attempt
directory itself for pre-U6 workspaces (artifacts at the attempt level).
This module is the ONE naming authority; the workflow writes through it and
every reader resolves through it, so the two cannot drift apart.
"""

from __future__ import annotations

import os
import re

IMPL_ATTEMPT_PREFIX = "impl_"
_IMPL_DIR_RE = re.compile(r"^impl_(\d{3,})$")


def impl_attempt_dirname(impl_attempt: int) -> str:
    """``impl_001`` for attempt 1 — zero-padded so lexical order is index order."""
    if impl_attempt < 1:
        raise ValueError(f"impl_attempt is 1-based; got {impl_attempt}")
    return f"{IMPL_ATTEMPT_PREFIX}{impl_attempt:03d}"


def impl_attempt_dir(attempt_dir: str, impl_attempt: int) -> str:
    return os.path.join(attempt_dir, impl_attempt_dirname(impl_attempt))


def list_impl_attempt_dirs(attempt_dir: str) -> list[str]:
    """Every ``impl_NNN`` directory under ``attempt_dir``, ascending by index.

    Entries that do not match the exact ``impl_<digits>`` shape (files,
    ``models/``, a stray ``impl_x``) are ignored — discovery is by the
    authority's own naming, never by listing order.
    """
    try:
        entries = os.listdir(attempt_dir)
    except OSError:
        return []
    indexed: list[tuple[int, str]] = []
    for entry in entries:
        match = _IMPL_DIR_RE.match(entry)
        full = os.path.join(attempt_dir, entry)
        if match and os.path.isdir(full):
            indexed.append((int(match.group(1)), full))
    return [path for _, path in sorted(indexed)]


def terminal_impl_attempt_dir(attempt_dir: str) -> str | None:
    """The highest-indexed implementation attempt, or ``None`` when the
    attempt directory holds no ``impl_NNN`` (pre-U6 layout, or the
    implementor never ran)."""
    dirs = list_impl_attempt_dirs(attempt_dir)
    return dirs[-1] if dirs else None


def stage_artifact_dir(attempt_dir: str) -> str:
    """Where a reader finds the implementor / validation artifacts.

    The terminal ``impl_NNN`` when the nested layout exists; otherwise the
    attempt directory itself, which is where pre-U6 workflows wrote them.
    """
    terminal = terminal_impl_attempt_dir(attempt_dir)
    return terminal if terminal is not None else attempt_dir
