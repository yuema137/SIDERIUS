"""Literature configuration paths and byte identity shared by launch consumers.

Importing this module does not import execution. Calling its helpers may read
explicit configuration files; relative paths require the installed checkout.
"""

from __future__ import annotations

import hashlib
import os

from core.layout import checkout_root, require_checkout

SIDERIUS_ROOT = checkout_root()


def resolve_lit_review_config_path(config_path: str) -> str:
    """The ONE rule that turns a lit-review config path into a file to read.

    Relative paths resolve against ``SIDERIUS_ROOT`` (the checkout), exactly
    as the lit-review branch of ``run_workflow`` has always done; absolute
    paths are taken as-is. Both the workflow's read and the chain runner's
    ``enabled`` peek call this, so the lock's config pin can never describe
    a file the run does not read.
    """
    if os.path.isabs(config_path):
        return config_path
    return str(require_checkout(SIDERIUS_ROOT) / config_path)


def lit_review_config_sha256(config_path: str | None, *, enabled: bool) -> str | None:
    """sha256 of the resolved lit-review YAML bytes, or ``None`` when disabled.

    arXiv U1 (#253): the lock pins the lit-review CONFIG, not just the
    topology flag — two runs whose literature-review node read different
    root-paper lists are not comparable. Hashed at pre-flight from the same
    resolved path the node later opens.

    Raises:
        ValueError: lit-review is enabled but the resolved config cannot be
            read. Refused here, before any LLM call, instead of crashing
            inside the iteration after the interpreter has already run.
    """
    if not enabled:
        return None
    if config_path is None:
        raise ValueError(
            "literature review is enabled but no config was declared. Supply "
            "the task or experiment config explicitly before launch."
        )
    resolved = resolve_lit_review_config_path(config_path)
    try:
        with open(resolved, "rb") as f:
            payload = f.read()
    except OSError as exc:
        raise ValueError(
            f"lit-review is enabled but its config {resolved!r} cannot be read "
            f"({exc}). The run-invariants lock pins the config's sha256, so an "
            "unreadable config is refused at pre-flight rather than after the "
            "first LLM call."
        ) from exc
    return hashlib.sha256(payload).hexdigest()
