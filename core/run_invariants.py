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


def build_run_invariants(
    resolved_data_scope: list[int],
    health_gate_enabled: bool,
    health_gate_files: list[int] | None,
    health_checks_config: str | None,
    workspace: str,
) -> tuple[RunInvariants, str | None]:
    """Compute a run's invariants — the ONE shared path for every entry point.

    Materializes and hashes the effective HealthGate config FIRST (when
    gates are enabled), then constructs ``RunInvariants`` from the result,
    so the sha in the lock always describes the exact config the run will
    read. Workflow startup and the standalone tuner both call this — never
    duplicate the normalization/hashing logic at a call site.

    Args:
        resolved_data_scope: Already-resolved sorted file indices (the
            caller runs its scope validation — e.g.
            ``validate_runtime_config`` — before this).
        health_gate_enabled: The run's HealthGate switch.
        health_gate_files: Run-level shared monitored-file list
            (``None`` = YAML defaults; only legal with a full scope).
        health_checks_config: Operator-supplied HealthGate YAML path, or
            ``None`` for the shipped default.
        workspace: Directory receiving ``health_checks_effective.yaml``.

    Returns:
        ``(invariants, effective_config_path)`` — the path is ``None`` when
        gates are disabled (no effective config exists for disabled runs).
    """
    # Imported here, not at module top: keeps this generic module importable
    # without the health-check package for consumers that only need the
    # lock primitives (and avoids widening core→execute_tools coupling to
    # every importer of the lock).
    from execute_tools.health_checks.config import materialize_effective_config

    if health_gate_enabled:
        effective_path, sha = materialize_effective_config(
            health_checks_config,
            health_gate_files,
            workspace,
            resolved_scope=resolved_data_scope,
        )
    else:
        effective_path, sha = None, None
    return (
        RunInvariants(
            resolved_data_scope=list(resolved_data_scope),
            health_gate_enabled=health_gate_enabled,
            health_config_sha256=sha,
        ),
        effective_path,
    )


def validate_stamped_invariants(
    stamped: dict,
    expected: RunInvariants,
    *,
    full_scope: list[int],
    source: str,
) -> None:
    """Check one persisted record/output's invariant stamps against a run.

    Legacy-aware ingress validation for restored history and seed evidence:

    - ``resolved_data_scope`` missing → the record predates DataScope and
      was necessarily produced under the FULL scope (compared against
      ``full_scope``).
    - ``health_gate_enabled`` missing → the record predates the disabled
      mode and was produced with gates active — compatible ONLY with an
      enabled run.
    - ``health_config_sha256`` missing → predates the policy lock; the sha
      comparison is skipped (scope + enabled remain enforced).

    Raises:
        RunInvariantsViolation: any present-or-assumed stamp contradicts
            ``expected``; the message names ``source`` and the field.
    """
    problems: list[str] = []

    record_scope = stamped.get("resolved_data_scope")
    effective_scope = full_scope if record_scope is None else sorted(record_scope)
    if effective_scope != list(expected.resolved_data_scope):
        origin = "unstamped (legacy = full scope)" if record_scope is None else "stamped"
        problems.append(
            f"resolved_data_scope: record is {origin} {effective_scope} vs "
            f"this run's {list(expected.resolved_data_scope)}"
        )

    record_enabled = stamped.get("health_gate_enabled")
    effective_enabled = True if record_enabled is None else record_enabled
    if effective_enabled != expected.health_gate_enabled:
        origin = (
            "unstamped (legacy = gates active)" if record_enabled is None else "stamped"
        )
        problems.append(
            f"health_gate_enabled: record is {origin} {effective_enabled} vs "
            f"this run's {expected.health_gate_enabled}"
        )

    record_sha = stamped.get("health_config_sha256")
    if record_sha is not None and record_sha != expected.health_config_sha256:
        problems.append(
            f"health_config_sha256: record pinned {record_sha[:12]}… vs "
            f"this run's {(expected.health_config_sha256 or 'None')[:12]}…"
        )

    if problems:
        detail = "\n".join(f"  - {p}" for p in problems)
        raise RunInvariantsViolation(
            f"ingress evidence from {source} is incompatible with this run's "
            f"invariants:\n{detail}\n"
            f"  Records are only comparable within one invariant set — start "
            f"a new workspace, or seed with matching-scope evidence."
        )
