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
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from core.execution_calibration import calibration_provenance

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
        ordering_override_strategy: The operator's data-ordering override for
            this chain, or ``None`` when no override is in force. This locks
            the chain's ordering CONTROL POLICY, not its outcome — see below.
        ordering_override_file_order: The operator-forced file visitation
            order, or ``None``.
        structured_health_feedback_enabled: Whether the structured
            HealthGate feedback PROMPT rendering is enabled (V19 PR 3,
            ``docs/design/v19_priorities/pr3_healthgate_feedback.md``
            §3.9). Locked because it changes the agents' decision context
            — the chain's behavioral policy — even though it changes no
            data or scoring.
        health_feedback_history_window_iterations: Fingerprint-history
            retention window (total iterations retained, including the
            current one). Locked with the flag: retention affects agent
            context.
        health_feedback_history_max_entries_per_model: Deterministic trim
            bound on retained history entries per model. Locked with the
            flag.
        created_at: ISO-8601 creation timestamp. Provenance only — never
            part of equality.

    PR 3 resume matrix (the generic ``_CANONICAL`` comparison enforces it;
    defaults below make a pre-PR3 lock file validate into the pre-feature
    state):

        same flag + same policy values        → accepted
        changed flag, same workspace          → RunInvariantsViolation
        changed window or entry limit         → RunInvariantsViolation
        legacy workspace (no PR3 keys)        → resolves OFF / 3 / 8; accepted
        enabling ON on a legacy/OFF workspace → rejected (canonical
                                                 mismatch); use a NEW
                                                 workspace

    Why the ordering OVERRIDE is locked but the RESOLVED ordering is not:
    an override is a chain-level control decision, and silently changing it
    mid-chain would invalidate the comparison the chain exists to make. The
    resolved value, by contrast, may legitimately differ from round to round
    when no override is active and the agent is exploring — locking it would
    forbid the intended behavior. Each round's resolved ordering is recorded
    on its own ``ExperimentRecord`` instead
    (docs/design/v19_priorities/pr2_data_ordering.md §3.8).
    """

    model_config = ConfigDict(frozen=True)

    resolved_data_scope: list[int]
    health_gate_enabled: bool
    health_config_sha256: str | None
    # Default None so a pre-PR2 lock file — which has no ordering keys at
    # all — validates cleanly into the no-override state instead of tripping
    # the corruption guard in load_run_invariants().
    ordering_override_strategy: str | None = None
    ordering_override_file_order: list[int] | None = None
    # V19 PR 3 — defaults chosen so a pre-PR3 lock file validates into the
    # pre-feature state (OFF / 3 / 8), same mechanism as the ordering keys.
    structured_health_feedback_enabled: bool = False
    health_feedback_history_window_iterations: int = 3
    health_feedback_history_max_entries_per_model: int = 8
    # C9d — the runtime decision subsystem's behavioral identities. Unlike
    # every field above, these have NO pre-feature state to default into:
    # a lock without them was written before runtime authority was
    # unified, so the workspace's history was produced under different
    # decision rules. `None` therefore means "legacy", and legacy is
    # REJECTED at validation (see _reject_legacy_runtime_lock) rather
    # than silently accepted. The default exists only so an old lock file
    # can be PARSED well enough to produce that explicit error.
    runtime_estimator_identity: str | None = None
    runtime_policy_identity: str | None = None
    # Step 10 / P1 — the COMPOSED run's canonical semantic task-composition
    # fingerprint, or None for an un-composed (legacy) run. `None` is not a
    # compatible default here: it means "this workspace was not composed",
    # and a composed run meeting an un-composed lock is a genuine mismatch
    # that the canonical comparison below must refuse. The key is OMITTED
    # from the serialized lock when None (see `write_run_invariants`), so a
    # legacy lock file stays byte-identical to its pre-P1 form.
    task_composition_fingerprint: str | None = None
    created_at: str | None = None
    # Step 11 C3 (R-11-6) — the per-role subprocess memory ceilings this
    # run executed under, plus their provenance. RECORDED, never compared.
    #
    # Ceilings are execution-HOST calibration, not task semantics: the same
    # scientific run resumed on a differently-calibrated host must remain
    # legal, unlike a composition, metric or dataset-semantics change. That
    # is why this field is declared in `_PROVENANCE` below rather than
    # merely left out of `_CANONICAL` — "absent from the canonical tuple"
    # is a validator remembering not to compare something, and the operator
    # constraint on R-11-6 is that the two concepts be distinguishable in
    # the REPRESENTATION.
    #
    # Omitted from the serialized lock when None, like the composition
    # fingerprint, so a pre-C3 lock file stays byte-identical.
    execution_calibration: dict[str, Any] | None = None

    # Fields participating in lock equality.
    _CANONICAL: ClassVar[tuple[str, ...]] = (
        "resolved_data_scope",
        "health_gate_enabled",
        "health_config_sha256",
        "ordering_override_strategy",
        "ordering_override_file_order",
        "structured_health_feedback_enabled",
        "health_feedback_history_window_iterations",
        "health_feedback_history_max_entries_per_model",
        "runtime_estimator_identity",
        "runtime_policy_identity",
        "task_composition_fingerprint",
    )

    #: Fields RECORDED for audit and never compared (Step 11 C3, R-11-6).
    #:
    #: The counterpart of ``_CANONICAL``, declared so the distinction is a
    #: property of the model rather than of whichever validator happens to
    #: read it. Together the two tuples must PARTITION every declared
    #: field: a new field is either a semantic invariant or execution
    #: provenance, and it cannot be neither. ``__init_subclass__``-free —
    #: the partition is asserted by a guard test, because enforcing it at
    #: import time would turn a naming slip into a repo-wide import error.
    _PROVENANCE: ClassVar[tuple[str, ...]] = (
        "created_at",
        "execution_calibration",
    )

    #: C9d fields that a legacy lock cannot supply. Their absence is a
    #: refusal, never a compatible default.
    _RUNTIME_IDENTITY_FIELDS: ClassVar[tuple[str, ...]] = (
        "runtime_estimator_identity",
        "runtime_policy_identity",
    )

    def canonical(self) -> dict:
        """The equality-defining subset of the invariants."""
        return {name: getattr(self, name) for name in self._CANONICAL}

    def provenance(self) -> dict:
        """The RECORDED-only subset: audit evidence, never compared."""
        return {name: getattr(self, name) for name in self._PROVENANCE}


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
    payload = stamped.model_dump()
    # Step 10 / P1 §5.9: an UN-COMPOSED run's lock must be byte-identical to
    # its pre-P1 form, so the composition key is ABSENT rather than `null`.
    # Serializing it as null would change every legacy lock's bytes for a
    # feature those runs do not use — and "absent" is also the honest
    # encoding: the workspace predates composition rather than having been
    # composed with nothing. Pydantic's default makes it parse back to None.
    if payload.get("task_composition_fingerprint") is None:
        payload.pop("task_composition_fingerprint", None)
    # Step 11 C3 — same rule, same reason: a lock written before execution
    # calibration was recorded stays byte-identical rather than gaining a
    # `null` for a concept it predates.
    if payload.get("execution_calibration") is None:
        payload.pop("execution_calibration", None)
    fd, tmp_path = tempfile.mkstemp(dir=workspace, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        os.link(tmp_path, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_path)
    return path


def _reject_legacy_runtime_lock(
    workspace: str, locked: RunInvariants, expected: RunInvariants
) -> None:
    """C9d: refuse to resume a workspace locked before runtime authority
    was unified.

    Pydantic defaults let an old lock file PARSE — that is all they are
    for. They must never be read as "compatible": a workspace whose lock
    predates these fields produced its history under different decision
    rules (a static formula could gate rounds, priors could arm the
    watchdog), so continuing it under the current rules would mix two
    incompatible regimes in one trajectory.

    Raised before any LLM call or training, and only when THIS run has the
    identities (a legacy-vs-legacy comparison stays legal so old tooling
    can still read old workspaces).
    """
    missing = [
        name
        for name in RunInvariants._RUNTIME_IDENTITY_FIELDS
        if getattr(locked, name) is None and getattr(expected, name) is not None
    ]
    if not missing:
        return
    raise RunInvariantsViolation(
        f"workspace {workspace!r} was created before the runtime-control "
        f"invariants existed and cannot be resumed by this build.\n"
        + "\n".join(f"  - {name}: absent from the lock" for name in missing)
        + "\n  This run would decide runtime authority under rules the "
        "workspace's existing iterations never ran under (unified "
        "estimator/policy, measured-evidence-only blocking, "
        "REQUEST_PROBE resolution). Defaults are used to PARSE the old "
        "lock, never to declare it compatible.\n"
        "  Start a FRESH workspace; the old one remains readable and is "
        "not modified."
    )


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
    _reject_legacy_runtime_lock(workspace, locked, expected)
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
    ordering_override_strategy: str | None = None,
    ordering_override_file_order: list[int] | None = None,
    structured_health_feedback_enabled: bool = False,
    health_feedback_history_window_iterations: int = 3,
    health_feedback_history_max_entries_per_model: int = 8,
    include_runtime_identities: bool = True,
    task_health_binding: Any = None,
    task_composition_fingerprint: str | None = None,
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
        ordering_override_strategy: The run's data-ordering override, or
            ``None`` for no override. Defaults keep every pre-PR2 call site
            producing an unchanged, no-override lock.
        ordering_override_file_order: The operator-forced file order, or
            ``None``.
        structured_health_feedback_enabled: V19 PR 3 structured-feedback
            prompt flag (chain behavioral policy — locked). Defaults keep
            every pre-PR3 call site producing an unchanged OFF lock.
        health_feedback_history_window_iterations: PR 3 retention window
            (locked policy).
        health_feedback_history_max_entries_per_model: PR 3 retention trim
            bound (locked policy).

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
        # Step 10 / P1: the composed task Health binding is PASSED THROUGH to
        # 08b's existing keyword. Omitting it (the un-composed default) is
        # what resolves `LEGACY_OMITTED`, so a legacy run materializes the
        # byte-identical effective config it always did — the call shape is
        # the branch, and there is no task name on either side of it.
        health_kwargs = (
            {} if task_health_binding is None else {"task_health_binding": task_health_binding}
        )
        effective_path, sha = materialize_effective_config(
            health_checks_config,
            health_gate_files,
            workspace,
            resolved_scope=resolved_data_scope,
            **health_kwargs,
        )
    else:
        effective_path, sha = None, None
    return (
        RunInvariants(
            resolved_data_scope=list(resolved_data_scope),
            health_gate_enabled=health_gate_enabled,
            health_config_sha256=sha,
            ordering_override_strategy=ordering_override_strategy,
            ordering_override_file_order=(
                list(ordering_override_file_order)
                if ordering_override_file_order is not None
                else None
            ),
            structured_health_feedback_enabled=structured_health_feedback_enabled,
            health_feedback_history_window_iterations=(health_feedback_history_window_iterations),
            health_feedback_history_max_entries_per_model=(
                health_feedback_history_max_entries_per_model
            ),
            # C9d: stamped HERE so every entry point (workflow, chain
            # runner, standalone tuner) locks the same identities — the
            # builder is the one shared path by contract.
            task_composition_fingerprint=task_composition_fingerprint,
            # Step 11 C3 (R-11-6) — stamped at the SAME shared builder, for
            # the same reason C9d is: every entry point then records the
            # ceilings its children actually ran under. Provenance, never
            # compared.
            execution_calibration=calibration_provenance(),
            **_runtime_identity_fields(include_runtime_identities),
        ),
        effective_path,
    )


def _runtime_identity_fields(include: bool) -> dict[str, str | None]:
    """The runtime subsystem's behavioral identities for the lock.

    ``include=False`` is for tooling that must build a LEGACY-shaped
    invariant set (e.g. reading an old workspace); production callers
    always stamp them.
    """
    if not include:
        return {}
    from core.runtime_control.estimator import shared_runtime_components

    estimator, policy = shared_runtime_components()
    return {
        "runtime_estimator_identity": estimator.identity,
        "runtime_policy_identity": policy.identity,
    }


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

    **Step 11 C8 / R-11-9 — the composition fingerprint, three cases.**
    ``_CANONICAL`` has included ``task_composition_fingerprint`` since
    Step 10, so the workspace LOCK refuses a cross-composition resume — but
    this INGRESS validator never looked at it, so a record produced under a
    different composition could be restored into a run that would then
    compare it as though it were its own (**F-11-6**). The asymmetry is
    closed under a rule that distinguishes the modes rather than picking one
    default::

        legacy / un-composed run + unstamped record   -> READABLE
        composed run + record carrying a fingerprint  -> must MATCH
        composed run + UNSTAMPED legacy record        -> REFUSE

    The third case is the one that needs stating. A record written before
    composition existed cannot be certified as belonging to this
    composition: "unstamped" says *nothing was recorded*, not *nothing was
    composed*. Treating absence as agreement is exactly how a
    cross-composition record would slip in, so this follows
    ``_reject_legacy_runtime_lock``'s precedent of refusing rather than
    defaulting. An UN-composed run is untouched by all of it, which is what
    keeps every pre-Step-10 workspace readable.

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
        origin = "unstamped (legacy = gates active)" if record_enabled is None else "stamped"
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

    # Step 11 C8 / R-11-9 — the composition fingerprint. Keyed on whether
    # THIS RUN is composed, never on a task name.
    if expected.task_composition_fingerprint is not None:
        record_fingerprint = stamped.get("task_composition_fingerprint")
        if record_fingerprint is None:
            problems.append(
                "task_composition_fingerprint: this run is COMPOSED "
                f"({expected.task_composition_fingerprint[:12]}…) but the record "
                "carries no fingerprint. A record written before composition "
                "existed cannot be certified as belonging to this composition — "
                "unstamped means nothing was recorded, not that nothing was "
                "composed."
            )
        elif record_fingerprint != expected.task_composition_fingerprint:
            problems.append(
                f"task_composition_fingerprint: record pinned "
                f"{str(record_fingerprint)[:12]}… vs this run's "
                f"{expected.task_composition_fingerprint[:12]}…"
            )

    if problems:
        detail = "\n".join(f"  - {p}" for p in problems)
        raise RunInvariantsViolation(
            f"ingress evidence from {source} is incompatible with this run's "
            f"invariants:\n{detail}\n"
            f"  Records are only comparable within one invariant set — start "
            f"a new workspace, or seed with matching-scope evidence."
        )
