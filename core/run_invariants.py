# core/run_invariants.py
"""Immutable run-level invariants — workspace lock creation and validation.

A *run invariant* is a configuration value that defines the identity of every
record produced in a workspace and therefore must never change across
executions against that workspace (chain iterations, ``--resume``, standalone
tuner runs). Changing one mid-workspace would make already-persisted records
incomparable with future ones — e.g. a DataScope change alters the scalar
population, and a HealthGate policy change retroactively relabels candidate
validity (see docs/design/enable_partial_file_list.md, *Policy lock*).

The invariants are pinned by ``{workspace}/run_invariants_lock.json``:

- The first execution to initialize a workspace atomically creates the lock
  (first writer wins; a concurrent losing writer falls through to
  read-and-validate).
- Every later execution validates its own resolved configuration against the
  lock and fails fast on mismatch, naming exactly which field drifted.
- Equality is defined ONLY over the canonical invariant fields; provenance
  metadata (``created_at``) never participates.

The current canonical set is ``resolved_data_scope`` +
``health_gate_enabled`` + ``health_config_sha256``. The mechanism is
deliberately generic: future run-defining settings (dataset version,
execution policy, ...) join by adding a field to ``RunInvariants`` — the
file format and validation logic need no redesign.

v1 policy: no escape hatch — a deliberate invariant change means a new
workspace (FU-6 tracks an explicit migration path if a need appears).
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import UTC, datetime
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

RUN_INVARIANTS_BASENAME = "run_invariants_lock.json"


class RunInvariantsViolation(ValueError):
    """A run's configuration contradicts the workspace's invariant lock."""


class RunInvariants(BaseModel):
    """The canonical immutable configuration of one workspace.

    Attributes:
        resolved_data_scope: Sorted resolved file indices this workspace's
            runs may access (full scope is stored explicitly, e.g.
            ``[0..19]`` — never ``None``, so records are unambiguous).
        health_gate_enabled: Whether the HealthGate subsystem is active.
        health_config_sha256: sha256 of the canonical materialized effective
            HealthGate config; ``None`` when gates are disabled (a disabled
            run has no effective config file, so the flag itself is part of
            the locked identity).
        created_at: ISO-8601 creation timestamp. Provenance only — never
            part of equality.
    """

    model_config = ConfigDict(frozen=True)

    resolved_data_scope: list[int]
    health_gate_enabled: bool
    health_config_sha256: str | None
    created_at: str | None = None

    # Fields participating in lock equality. created_at (and any future
    # provenance metadata) is deliberately absent.
    _CANONICAL: ClassVar[tuple[str, ...]] = (
        "resolved_data_scope",
        "health_gate_enabled",
        "health_config_sha256",
    )

    def canonical(self) -> dict:
        """The equality-defining subset of the invariants."""
        return {name: getattr(self, name) for name in self._CANONICAL}


def _lock_path(workspace: str) -> str:
    return os.path.join(workspace, RUN_INVARIANTS_BASENAME)


def load_run_invariants(workspace: str) -> RunInvariants | None:
    """Read the workspace's invariant lock; ``None`` when no lock exists.

    A missing lock means the workspace predates this mechanism (or is being
    initialized right now) — callers decide whether to create it via
    ``ensure_run_invariants``.

    Raises:
        RunInvariantsViolation: the lock file exists but is unreadable or
            structurally invalid (corruption is a violation, not a legacy
            state — silently regenerating it could relabel history).
    """
    try:
        with open(_lock_path(workspace)) as f:
            raw = f.read()
    except FileNotFoundError:
        return None
    try:
        return RunInvariants.model_validate(json.loads(raw))
    except Exception as exc:
        raise RunInvariantsViolation(
            f"{RUN_INVARIANTS_BASENAME} in workspace {workspace!r} is corrupted "
            f"or has an unrecognized shape ({exc}). Refusing to guess the "
            f"workspace's invariants — restore the file or use a new workspace."
        ) from exc


def write_run_invariants(workspace: str, invariants: RunInvariants) -> str:
    """Atomically create the invariant lock. First writer wins.

    The content is written to a same-directory temp file and published with
    ``os.link`` — atomic on POSIX and, unlike ``os.rename``, it FAILS when
    the lock already exists instead of overwriting it, which is what gives
    the first writer its win. A losing concurrent writer receives
    ``FileExistsError`` and should fall through to validation
    (``ensure_run_invariants`` does exactly that).

    Returns:
        The lock file path.

    Raises:
        FileExistsError: the lock already exists (caller must validate
            against it instead).
    """
    os.makedirs(workspace, exist_ok=True)
    stamped = (
        invariants
        if invariants.created_at is not None
        else invariants.model_copy(update={"created_at": datetime.now(UTC).isoformat()})
    )
    path = _lock_path(workspace)
    fd, tmp_path = tempfile.mkstemp(dir=workspace, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(stamped.model_dump(), f, indent=2)
            f.write("\n")
        os.link(tmp_path, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_path)
    return path


def validate_run_invariants(workspace: str, expected: RunInvariants) -> None:
    """Compare ``expected`` against the workspace lock; raise on any drift.

    Equality covers only the canonical fields. Every drifted field is named
    with its locked and attempted values so the operator sees exactly what
    changed (scope change, HealthGate enable flip, and policy-content drift
    each produce their own line).

    Raises:
        RunInvariantsViolation: no lock exists (callers wanting
            create-or-validate semantics use ``ensure_run_invariants``), or
            one or more canonical fields differ.
    """
    locked = load_run_invariants(workspace)
    if locked is None:
        raise RunInvariantsViolation(
            f"workspace {workspace!r} has no {RUN_INVARIANTS_BASENAME} to "
            f"validate against. Initialize it via ensure_run_invariants()."
        )
    drifted = [
        name
        for name in RunInvariants._CANONICAL
        if getattr(locked, name) != getattr(expected, name)
    ]
    if drifted:
        detail = "\n".join(
            f"  - {name}: locked={getattr(locked, name)!r} vs this run={getattr(expected, name)!r}"
            for name in drifted
        )
        raise RunInvariantsViolation(
            f"run-invariants lock violation in workspace {workspace!r} — this "
            f"run's configuration contradicts the workspace's immutable "
            f"invariants:\n{detail}\n"
            f"  Run invariants are immutable per workspace; use a new "
            f"workspace to change them."
        )


def ensure_run_invariants(workspace: str, expected: RunInvariants) -> str:
    """Create the lock if absent, else validate against it.

    The single entry point for workspace startup (workflow pre-flight,
    standalone tuner, resume): exactly one caller wins the creation race and
    every other execution — concurrent or later — is validated.

    Returns:
        ``"created"`` when this call created the lock, ``"validated"`` when
        an existing lock matched.

    Raises:
        RunInvariantsViolation: an existing lock contradicts ``expected``.
    """
    try:
        write_run_invariants(workspace, expected)
        return "created"
    except FileExistsError:
        validate_run_invariants(workspace, expected)
        return "validated"
