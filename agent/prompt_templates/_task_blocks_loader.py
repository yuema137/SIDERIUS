# agent/prompt_templates/_task_blocks_loader.py
"""The deterministic mechanics shared by every task-blocks adapter.

Step 12 / PR-12a C7-4. Three adapters now parse a task-owned YAML declaration
into a typed blocks value — interpretation (09b), proposal (C7-3) and
implementor (C7-4) — and the *mechanics* of doing so are identical every time:
resolve the path, read the file, insist it is a mapping, hand it to the model,
and fail closed on anything else.

What is deliberately NOT shared is the SCHEMA. Each family owns a different
key set because each renders in a different place for a different reason, and
collapsing them into one "task blocks" object would turn three explicit
contracts into one bag whose keys nobody owns. This module holds the loading,
not the meaning: it takes the model as an argument and never inspects it.

The 09b interpretation adapter is deliberately left alone — it is frozen
evidence for that step, and rewriting it to save a few lines would put a
Step-12 edit inside Step-09b's guard surface for no behavioural gain.
"""

from __future__ import annotations

import os
from typing import Any

import yaml
from pydantic import BaseModel

SIDERIUS_ROOT: str = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""This checkout's repository root, derived from this file's own location.

Path resolution for the three adapters' shipped-config defaults, which is
mechanics and therefore belongs here rather than being re-derived in each
adapter. The 09b interpretation adapter imports THIS constant and keeps its
own loader — anchoring a path is not the migration this module's docstring
declines to make.

**F-7, second occurrence.** The three ``LEGACY_DEFAULT_TASK_*_CONFIG``
constants were RELATIVE paths, so they resolved against the caller's working
directory, and each adapter's loader is fail-closed. No launcher under
``sdsc_submission_scripts/`` or ``scripts/`` cd's to the repo root, so an
un-composed chain launched from any other cwd raised ``FileNotFoundError`` in
the proposer, the implementor AND the interpreter — the same launch geometry
that produced the original F-7 failure in the Health config, one layer over.
CLAUDE.md's portability rule names exactly this: path resolution derives from
the file's own location or a supplied root, never from the caller's cwd.
"""


def load_task_blocks_declaration[Blocks: BaseModel](
    model: type[Blocks],
    *,
    path: str | None,
    default_path: str,
    kind: str,
) -> Blocks:
    """Parse a task-owned declaration file into ``model``. FAIL-CLOSED.

    Args:
        model: the typed blocks contract to validate against. Its OWN
            ``extra="forbid"`` is what rejects a typo'd section name — this
            function never enumerates keys.
        path: the caller's declaration path, or ``None`` for ``default_path``.
        default_path: the bounded legacy compatibility default. A CONSTANT
            supplied by the caller, never derived here from a task name.
        kind: the family name, used only to make errors say which declaration
            failed.

    Raises:
        FileNotFoundError: the declaration file does not exist.
        ValueError: the file is not a YAML mapping, or the mapping fails the
            model's contract (unknown key, wrong type).
    """
    resolved = path if path is not None else default_path
    if not os.path.exists(resolved):
        raise FileNotFoundError(
            f"{kind} task-blocks declaration not found: {resolved!r} — the "
            f"caller must supply an existing declaration file or construct "
            f"the {model.__name__} value directly"
        )
    with open(resolved, encoding="utf-8") as handle:
        raw: Any = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise ValueError(
            f"{kind} task-blocks declaration {resolved!r} must be a YAML "
            f"mapping of section name -> prose, got {type(raw).__name__}"
        )
    try:
        return model.model_validate(raw)
    except Exception as exc:
        raise ValueError(
            f"{kind} task-blocks declaration {resolved!r} failed the "
            f"{model.__name__} contract: {exc}"
        ) from exc
