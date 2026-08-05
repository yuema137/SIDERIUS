# execute_tools/health_checks/config.py
"""
YAML config loader for the pluggable health-check framework.

Loads the rev-6 HealthGate config classes for
``load_health_gates_config()``. The legacy rev-3 panel-model classes
(``HealthCheckConfig`` / ``CheckConfig``) and their loader were removed
in commit-6 — the migration is complete and no consumers remained.

See ``docs/design/pluggable_health_checks.md`` §3 for the new YAML
shape and §5 for the schema-side design principles.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from execute_tools.dataset_config import TIDMAD
from execute_tools.health_checks.schemas import GateAction

_DEFAULT_CONFIG_PATH: str = os.path.join("configs", "health_checks.yaml")

# Basename of the per-workspace materialized effective config — the single
# path every downstream loader reads once the run-level monitored-file
# override is applied. See docs/design/enable_partial_file_list.md (DS4).
EFFECTIVE_CONFIG_BASENAME: str = "health_checks_effective.yaml"


# ---------------------------------------------------------------------------
# rev-6 HealthGate config classes
# ---------------------------------------------------------------------------


class CheckRef(BaseModel):
    """One check reference inside a gate.

    A gate lists checks by name, each with its own per-gate config
    override. The check is dispatched from the runtime registry
    (``execute_tools/health_checks/registry.py``); its ``config`` dict
    is passed as the ``config`` arg to the skill's ``run(ctx, config)``.
    """

    name: str = Field(
        ...,
        description=(
            "Registered check name — must be in ``_REGISTRY`` at runtime, "
            "else ``evaluate_gate`` raises KeyError."
        ),
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Per-gate config override passed to the check's ``run()`` method. "
            "Empty dict (default) means the check uses its own defaults."
        ),
    )


class ActionConfig(BaseModel):
    """Wrapper for a gate action (``on_pass`` or ``on_fail``).

    Wrapping the action in an object (rather than a bare string) matches
    the design doc §3 YAML shape ``on_pass: {action: continue}`` and
    leaves room to grow (e.g. add ``reason``, ``metrics_key``, etc. under
    each branch) without breaking existing YAML.
    """

    action: GateAction = Field(
        ...,
        description="The ``GateAction`` to take when this branch fires.",
    )


class GateConfig(BaseModel):
    """One HealthGate entry in ``configs/health_checks.yaml``.

    A gate fires at its configured ``after_round`` position, runs its
    ``checks`` in listed order (with per-gate ``short_circuit``), and
    resolves to either the ``on_pass`` or the ``on_fail`` action.
    """

    id: str = Field(
        ...,
        description=(
            "Unique identifier for this gate — used as the lookup key for "
            "the tuner's ``evaluate_gate(gate_id, ctx)`` call. Duplicates "
            "across gates are rejected at load time by "
            "``HealthChecksConfig._validate_unique_ids``."
        ),
    )
    gate_role: Literal["blocking", "observational"] | None = Field(
        default=None,
        description=(
            "What this gate MEANS scientifically, declared — never inferred. "
            "``blocking`` gates decide whether a record is a valid candidate; "
            "``observational`` gates only record.\n\n"
            "This is a property of the SCIENCE, not of enforcement, so it is "
            "identical in the blocking and observe-only configs; those differ "
            "only in ``on_fail.action``. Deriving it from the action instead "
            "does not merely lose information, it INVERTS the answer: under an "
            "observe-only config every action is ``continue``, so an "
            "action-derived scientific set is EMPTY and every record classifies "
            "valid. That was a live defect (see "
            "``resolve_scientific_gate_ids``).\n\n"
            "``None`` only for a historical config written before this field "
            "existed. Such a config is resolved through the audited "
            "compatibility map, or treated as UNKNOWN — never guessed from the "
            "gate id, the filename or the action."
        ),
    )
    after_round: int | Literal["every"] | list[int] = Field(
        ...,
        description=(
            "Which round(s) trigger this gate. Three accepted forms: "
            "(a) a positive int — fires on that specific round; "
            '(b) the literal string ``"every"`` — fires on every round; '
            "(c) a list of positive ints — fires on any listed round. "
            "The tuner calls ``get_gates_for_position(round_index)`` after "
            "each round to look up gates matching that round. See M8 §3.2."
        ),
    )

    @field_validator("after_round")
    @classmethod
    def _validate_after_round(cls, v: int | str | list[int]) -> int | Literal["every"] | list[int]:
        """Reject 0/negative round indices and empty lists; normalise types."""
        if isinstance(v, str):
            if v != "every":
                raise ValueError(f"after_round string must be 'every', got {v!r}.")
            return v
        if isinstance(v, list):
            if not v:
                raise ValueError("after_round list must contain at least one round.")
            for item in v:
                if not isinstance(item, int) or isinstance(item, bool):
                    raise ValueError(f"after_round list entries must be int, got {item!r}.")
                if item < 1:
                    raise ValueError(f"after_round list entries must be >= 1, got {item}.")
            return v
        # int case (bool is a subclass of int — reject explicitly)
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(f"after_round must be int, list[int], or 'every'; got {v!r}.")
        if v < 1:
            raise ValueError(f"after_round must be >= 1, got {v}.")
        return v

    def matches_round(self, round_index: int) -> bool:
        """Return True when this gate fires at ``round_index``.

        Encapsulates the three ``after_round`` forms so the runner has one
        place to change if the schema grows. See ``get_gates_for_position``.
        """
        if isinstance(self.after_round, str):
            return self.after_round == "every"
        if isinstance(self.after_round, list):
            return round_index in self.after_round
        return self.after_round == round_index

    short_circuit: bool = Field(
        default=True,
        description=(
            "When True (default), the gate stops evaluating checks after "
            "the first non-skipped failure. When False, all checks run for "
            "full diagnostic completeness. Rationale for per-gate scoping: "
            "``evaluate_gate`` is already per-gate, and different gates may "
            "want different failure-verbosity trade-offs."
        ),
    )
    checks: list[CheckRef] = Field(
        ...,
        min_length=1,
        description=(
            "Ordered list of checks this gate runs. At least one check is "
            "required — a gate with no checks is a config error and fails "
            "validation at load time."
        ),
    )
    on_pass: ActionConfig = Field(
        ...,
        description=(
            "Action to take when all checks pass. Required — no default. "
            "A gate without explicit ``on_pass`` routing is a config error."
        ),
    )
    on_fail: ActionConfig = Field(
        ...,
        description=("Action to take when any check fails (short-circuit). Required — no default."),
    )
    reason: str = Field(
        default="",
        description=(
            "Free-text operator note explaining why this gate exists. "
            "Not consumed by the runner; surfaces in the loaded model for "
            "tooling and docs."
        ),
    )


class HealthChecksConfig(BaseModel):
    """The rev-6 HealthGate YAML root.

    Loaded from ``configs/health_checks.yaml`` by
    ``load_health_gates_config``. See
    ``docs/design/pluggable_health_checks.md`` §3.
    """

    health_gates: list[GateConfig] = Field(
        default_factory=list,
        description=(
            "Ordered list of gates. Empty list = no gates fire "
            "(``get_gates_for_position`` returns ``[]`` for every round)."
        ),
    )

    @model_validator(mode="after")
    def _validate_unique_ids(self) -> HealthChecksConfig:
        """Reject duplicate gate ids — the runner uses ``id`` as the
        lookup key for ``evaluate_gate``.

        A duplicate would create silent behaviour (first-match-wins in
        ``get_gates_for_position`` but ambiguous in downstream lookups).
        Failing at load time surfaces the mistake immediately with the
        list of offending ids in the message.
        """
        ids = [g.id for g in self.health_gates]
        seen: set[str] = set()
        dupes: list[str] = []
        for gid in ids:
            if gid in seen and gid not in dupes:
                dupes.append(gid)
            seen.add(gid)
        if dupes:
            raise ValueError(
                f"Duplicate gate ids in health_checks.yaml: {dupes!r}. "
                f"Each gate id must be unique — rename one, or remove the duplicate."
            )
        return self


_CACHED_GATES: HealthChecksConfig | None = None


def load_health_gates_config(path: str | None = None) -> HealthChecksConfig:
    """Load + validate the rev-6 HealthGate config.

    Cached per process for the default path. When ``path`` is provided
    the cache is bypassed and the returned config is not cached — so
    tests can point at a fixture YAML without polluting the default
    cache.

    Args:
        path: Optional override for the config file location.

    Returns:
        A validated ``HealthChecksConfig``.
    """
    global _CACHED_GATES
    if path is None and _CACHED_GATES is not None:
        return _CACHED_GATES
    resolved = path or _DEFAULT_CONFIG_PATH
    with open(resolved) as f:
        raw = yaml.safe_load(f) or {}
    cfg = HealthChecksConfig.model_validate(raw)
    if path is None:
        _CACHED_GATES = cfg
    return cfg


def clear_health_gates_config_cache() -> None:
    """Clear the process-wide cache for the rev-6 config. Test-only —
    never call from production code."""
    global _CACHED_GATES
    _CACHED_GATES = None


# ---------------------------------------------------------------------------
# DataScope-aware monitored-file override (enable_partial_file_list, DS4)
# ---------------------------------------------------------------------------


def apply_monitored_files(config: HealthChecksConfig, files: list[int]) -> HealthChecksConfig:
    """Return a NEW config with every check's ``peek_file_indices`` replaced.

    v1 intentional simplification: ONE shared run-level monitored-file list
    is applied uniformly to ALL file-accessing checks — blocking AND
    recording-only (the recording checks honor ``peek_file_indices`` as
    their top-priority file source since DS4). Per-check customization is
    out of scope; a custom YAML remains the escape hatch.

    Pure transform: the input ``config`` (and the process-wide default-path
    cache) is never mutated.

    Raises:
        ValueError: If ``files`` is empty (monitoring nothing must be
            expressed via ``health_gate_enabled=False``, never an empty list).
    """
    if not files:
        raise ValueError(
            "apply_monitored_files: files must be non-empty — to disable "
            "HealthGate monitoring use health_gate_enabled=False, not an "
            "empty monitored-file list."
        )
    normalized = sorted({int(i) for i in files})
    dumped = config.model_dump(mode="python")
    for gate in dumped.get("health_gates", []):
        for check in gate.get("checks", []):
            check_cfg = check.setdefault("config", {})
            check_cfg["peek_file_indices"] = list(normalized)
    return HealthChecksConfig.model_validate(dumped)


def validate_health_scope(config: HealthChecksConfig, resolved_scope: list[int]) -> None:
    """Startup invariant: every file-accessing check stays inside the scope.

    Covers ALL checks, not only blocking ones. A check WITHOUT an explicit
    ``peek_file_indices`` reads the full dataset by default (recording
    checks fall back to ``range(num_files)``; blocking checks to the
    pre-M9 single-file peek) — under a partial DataScope that implicit
    full-dataset access is itself a violation. No intersection, no
    fallback, no silent correction: violations fail before any execution.

    Raises:
        ValueError: Listing every offending gate/check with remediation.
    """
    scope_set = set(resolved_scope)
    scope_is_full = scope_set == set(range(TIDMAD.num_files))
    problems: list[str] = []
    for gate in config.health_gates:
        for check in gate.checks:
            configured = check.config.get("peek_file_indices") or []
            if not configured:
                if not scope_is_full:
                    problems.append(
                        f"gate '{gate.id}' check '{check.name}': no explicit "
                        f"peek_file_indices (defaults to full-dataset access) "
                        f"— an explicit in-scope list is required under a "
                        f"partial DataScope"
                    )
                continue
            outside = sorted({int(i) for i in configured} - scope_set)
            if outside:
                problems.append(
                    f"gate '{gate.id}' check '{check.name}': peek_file_indices "
                    f"{outside} outside the DataScope {sorted(scope_set)}"
                )
    if problems:
        raise ValueError(
            "HealthGate monitored files violate the DataScope:\n  - "
            + "\n  - ".join(problems)
            + "\n  Remediation: pass --health_gate_files with in-scope files "
            "(one shared list, applied to every check), or disable the "
            "subsystem with --no-health_gate_enabled."
        )


def materialize_effective_config(
    source_path: str | None,
    files: list[int] | None,
    workspace: str,
    resolved_scope: list[int] | None = None,
) -> tuple[str, str]:
    """Materialize the run's effective HealthGate config to the workspace.

    load → apply monitored-file override (no-op when ``files is None``) →
    validate against the scope (when ``resolved_scope`` given) → write
    ``{workspace}/health_checks_effective.yaml`` atomically (same-directory
    temp file + rename). The returned sha256 is computed over the canonical
    YAML body (header excluded) and is what the run-invariants lock pins
    (DS6).

    Resume semantics — the effective config is workspace-immutable:
    an existing file with the same body sha256 is reused; a mismatch raises,
    distinguishing "operator inputs changed" (header's recorded
    ``health_gate_files`` differs) from "source YAML content drifted"
    (same inputs, different body — e.g. the shipped
    ``configs/health_checks.yaml`` changed underneath the workspace).

    Returns:
        (effective_config_path, body_sha256)
    """
    cfg = load_health_gates_config(source_path)
    if files is not None:
        cfg = apply_monitored_files(cfg, files)
    if resolved_scope is not None:
        validate_health_scope(cfg, resolved_scope)

    body = yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=True)
    sha = hashlib.sha256(body.encode()).hexdigest()
    files_repr = sorted({int(i) for i in files}) if files else None
    header = (
        "# Materialized effective HealthGate config — do not edit.\n"
        "# Written by materialize_effective_config (enable_partial_file_list DS4).\n"
        f"# source: {source_path or _DEFAULT_CONFIG_PATH}\n"
        f"# health_gate_files: {files_repr}\n"
        f"# sha256: {sha}\n"
    )
    path = os.path.join(workspace, EFFECTIVE_CONFIG_BASENAME)

    # Read-then-fallback rather than exists-then-open: the existence check
    # would race with a concurrent materializer (TOCTOU) and is fooled by
    # test environments that stub os.path.exists globally.
    try:
        with open(path) as f:
            existing = f.read()
    except FileNotFoundError:
        existing = None

    if existing is not None:
        existing_sha = _header_value(existing, "# sha256:")
        if existing_sha == sha:
            return path, sha
        existing_files = _header_value(existing, "# health_gate_files:")
        if existing_files is None:
            cause = (
                "the existing file has no recognizable materialization header "
                "(corrupted or hand-written)"
            )
        elif existing_files != str(files_repr):
            cause = (
                f"operator inputs changed — the workspace was materialized "
                f"with health_gate_files={existing_files} but this invocation "
                f"passes {files_repr}"
            )
        else:
            cause = (
                "source YAML content drifted since materialization (e.g. the "
                "shipped configs/health_checks.yaml changed underneath the "
                "workspace, perhaps via git pull)"
            )
        raise ValueError(
            f"{EFFECTIVE_CONFIG_BASENAME} mismatch in workspace {workspace!r}: "
            f"{cause}. HealthGate policy is workspace-immutable — use a new "
            f"workspace to change it."
        )

    os.makedirs(workspace, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=workspace, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(header + body)
        os.rename(tmp_path, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_path)
        raise
    return path, sha


def _header_value(content: str, prefix: str) -> str | None:
    """Extract a materialization-header value; None when the line is absent."""
    for line in content.splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
        if not line.startswith("#"):
            break
    return None
