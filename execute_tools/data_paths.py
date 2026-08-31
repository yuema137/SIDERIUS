"""Run-scoped physical dataset-root validation and transport."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar


class DatasetDirectoryUnavailable(RuntimeError):
    """The configured physical dataset directory is unavailable."""


def resolve_dataset_dir(explicit: str | None, *, purpose: str = "this run") -> str:
    """Validate an explicitly selected physical dataset directory.

    Physical location is caller-owned execution provenance. The framework does
    not select a task, machine, or per-user fallback when the caller omits it.
    """
    if explicit is None or not explicit.strip():
        raise DatasetDirectoryUnavailable(
            f"no dataset directory was supplied for {purpose}. "
            "Pass --data_dir <existing-directory>."
        )
    if not os.path.isdir(explicit):
        raise DatasetDirectoryUnavailable(
            f"the dataset directory supplied for {purpose} is not a readable "
            f"directory: {explicit!r}. Pass --data_dir <existing-directory>."
        )
    return explicit


_ACTIVE_PHYSICAL_DATA_ROOT: ContextVar[str | None] = ContextVar(
    "siderius_active_physical_data_root", default=None
)


@contextmanager
def bind_physical_data_root(root: str, *, purpose: str = "this run") -> Iterator[str]:
    """Validate and bind one run's caller-selected physical dataset root."""
    validated = resolve_dataset_dir(root, purpose=purpose)
    token = _ACTIVE_PHYSICAL_DATA_ROOT.set(validated)
    try:
        yield validated
    finally:
        _ACTIVE_PHYSICAL_DATA_ROOT.reset(token)


def active_physical_data_root() -> str | None:
    """Return the explicitly bound root without inventing a fallback."""
    return _ACTIVE_PHYSICAL_DATA_ROOT.get()


def resolve_physical_data_root() -> str:
    """Return the bound root or refuse an unbound production read."""
    bound = active_physical_data_root()
    if bound is None:
        raise DatasetDirectoryUnavailable(
            "no physical data root is bound. Compose the run and pass "
            "--data_dir <existing-directory> before execution."
        )
    return bound
