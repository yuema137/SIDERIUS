"""Run-seed resolution against a workspace lock, for entry boundaries (issue #983).

Contracts: ``docs/agent-reference/mechanisms/seeding.md`` (the seed value) and
``docs/agent-reference/mechanisms/persistence-and-resume.md`` (the lock).

Precedence is fixed: an existing lock's ``run_seed`` wins, then the
operator's explicit seed, then :func:`core.seeding.resolve_run_seed`
generation. A different explicit seed is refused against a seeded lock, and a
lock that records no seed (written before this contract) is refused for
continuation. Only the target workspace's lock is read, so a history import
(``--seed_paths``, ``source_run_name``) never inherits a source run's seed.
"""

from __future__ import annotations

import argparse
from typing import Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from core.run_invariants import (
    RunInvariantsViolation,
    load_run_invariants,
    pre_seed_lock_violation,
)
from core.seeding import RUN_SEED_MAX, RunSeed, format_seed_line, resolve_run_seed

SeedOrigin = Literal["operator", "generated", "locked"]
_RUN_SEED = TypeAdapter(RunSeed)


def run_seed_argument(text: str) -> int:
    """argparse type for ``--run_seed``: an integer ``RunSeed`` in ``[0, 2**53 - 1]``."""
    try:
        return _RUN_SEED.validate_python(int(text))
    except (ValueError, ValidationError) as error:
        raise argparse.ArgumentTypeError(
            f"expected an integer run seed in [0, {RUN_SEED_MAX}], got {text!r}"
        ) from error


class WorkspaceRunSeed(BaseModel):
    """The seed one execution against a workspace uses, and where it came from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: RunSeed
    origin: SeedOrigin

    def log_line(self) -> str:
        """The operator-visible startup line, printed before any node runs."""
        return format_seed_line(self.value, self.origin)


def _locked_seed(workspace: str, explicit: int | None) -> int | None:
    """The workspace lock's seed, or ``None`` when no lock exists yet.

    Raises:
        RunInvariantsViolation: the lock predates the seed contract, or
            ``explicit`` contradicts the locked seed.
    """
    locked = load_run_invariants(workspace)
    if locked is None:
        return None
    if locked.run_seed is None:
        raise pre_seed_lock_violation(workspace)
    if explicit is not None and explicit != locked.run_seed:
        raise RunInvariantsViolation(
            f"run-invariants lock violation in workspace {workspace!r}:\n"
            f"  - run_seed: locked={locked.run_seed!r} vs this run={explicit!r}\n"
            "  A workspace keeps one run seed; omit --run_seed to continue with "
            "the locked seed, or use a new workspace for a different seed."
        )
    return locked.run_seed


def continuation_run_seed(workspace: str, explicit: int | None) -> int | None:
    """The seed a pre-flight must expect, without generating one.

    Returns the locked seed when a lock exists, else ``explicit`` (``None``
    means the workflow startup will generate it). Raises like
    :func:`resolve_workspace_run_seed`.
    """
    locked = _locked_seed(workspace, explicit)
    return explicit if locked is None else locked


def resolve_workspace_run_seed(workspace: str, explicit: int | None) -> WorkspaceRunSeed:
    """Resolve this execution's run seed: lock, then explicit, then generation.

    Raises:
        RunInvariantsViolation: see :func:`_locked_seed`.
        pydantic.ValidationError: ``explicit`` is not a valid ``RunSeed``.
    """
    locked = _locked_seed(workspace, explicit)
    if locked is not None:
        return WorkspaceRunSeed(value=locked, origin="locked")
    binding = resolve_run_seed(explicit)
    return WorkspaceRunSeed(value=binding.value, origin=binding.source)
