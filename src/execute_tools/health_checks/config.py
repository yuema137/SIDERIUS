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
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from execute_tools.dataset_config import resolve_dataset_profile
from execute_tools.health_checks import _plugin_binding
from execute_tools.health_checks._composition import (
    SIDERIUS_ROOT,
    DispositionPolicy,
    HealthBindingState,
    TaskHealthBinding,
    body_markers,
    default_disposition_policy,
    resolve_composed_gates,
)
from execute_tools.health_checks._plugin_binding import ResolvedHealthPlugin
from execute_tools.health_checks._policy_resources import DEFAULT_POLICY_LABEL, default_policy_path
from execute_tools.health_checks._task_health_config import TaskHealthConfig
from execute_tools.health_checks.schemas import GateAction


def default_health_policy_path() -> str:
    """Locate the packaged generic policy without opening it.

    Use this accessor for explicit production-policy comparisons. Omitted
    loader overrides use the same resource; scientific Health remains external.
    """
    return default_policy_path()


# Private compatibility name; values and location have no checkout authority.
_DEFAULT_CONFIG_PATH = default_health_policy_path()

# Basename of the per-workspace materialized effective config — the single
# path every downstream loader reads once the run-level monitored-file
# override is applied. See docs/design/enable_partial_file_list.md (DS4).
EFFECTIVE_CONFIG_BASENAME: str = "health_checks_effective.yaml"

# LEGACY COMPATIBILITY ADAPTER since Step 08b C5. This marker is written into a check's
# ``peek_file_indices`` and resolved, at config validation, into
# ``DatasetProfile.health_peek_files`` — the one route by which task-owned
# data reached the framework config. The task now states its peek set
# directly in its own health config, so the sentinel has no remaining job
# and no production YAML uses it (census at C5: zero, and no Python consumer
# outside this module).
#
# It still RESOLVES, and the C5 audit is why: a pre-08b config is re-read to
# reproduce its recorded ``health_config_sha256`` (see
# ``candidate_eligibility._LEGACY_ROLES_BY_CONFIG_SHA``), the sha is computed
# over the RESOLVED document, and those configs carry this marker — so
# refusing it would make a historical artifact unreadable and turn every
# affected candidate UNKNOWN. Bounded legacy adapter, never the extension
# mechanism and never generic task-package vocabulary.
TASK_HEALTH_PEEK: str = "task_health_peek"


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
            "Empty dict (default) means the check uses its own defaults.\n\n"
            "``peek_file_indices`` must be an explicit list. Step 08b C5 "
            f"retired the ``{TASK_HEALTH_PEEK}`` marker: the task states its "
            "peek set in its own health config and composition injects it."
        ),
    )

    @field_validator("config")
    @classmethod
    def _resolve_legacy_peek_marker(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Resolve the LEGACY marker into the task's file set. Legacy adapter only.

        Which files a task's blocking checks watch is a property of the TASK.
        Until Step 08b C5 this marker was the one route by which that fact
        reached the framework config; a task now declares its peek set in its
        own health config and composition injects the resolved list, so **no
        shipped config uses this any more**.

        **It resolves rather than raises, and the reason is concrete.** A
        pre-08b config is re-read to reproduce its recorded
        ``health_config_sha256`` — that is how
        ``candidate_eligibility._LEGACY_ROLES_BY_CONFIG_SHA`` recovers the
        gate roles of a workspace written before ``gate_role`` existed. Those
        configs carry the marker, and the sha is computed over the RESOLVED
        document, so refusing to resolve it would make a historical artifact
        unreadable and turn every such candidate UNKNOWN.

        Strictly a bounded legacy compatibility adapter (child design §3.8):
        **not** the extension mechanism, **not** required by any future task,
        and **not** task-package vocabulary. A new task declares
        ``health_peek_files`` in its own config instead.

        Any OTHER string is rejected. Left alone, a typo'd marker is truthy,
        and ``_resolve_indices`` would iterate it CHARACTER by character and
        peek file indices like ``'t'`` — a silent wrong answer rather than an
        error.
        """
        peek = value.get("peek_file_indices")
        if not isinstance(peek, str):
            return value
        if peek != TASK_HEALTH_PEEK:
            raise ValueError(
                f"peek_file_indices={peek!r} is not a recognized marker. Use "
                f"an explicit list of file indices. (The legacy "
                f"{TASK_HEALTH_PEEK!r} marker is retained only so pre-08b "
                f"configs stay readable; a task declares health_peek_files in "
                f"its own health config.)"
            )
        return {
            **value,
            "peek_file_indices": list(resolve_dataset_profile().health_peek_files),
        }


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
    """One HealthGate entry in ``configs/health/health_checks.yaml``.

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


class PersistedHealthPluginIdentity(BaseModel):
    """Canonical plugin provenance carried by a materialized Health config."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    configured_ref: str
    member: str = ""
    content_sha256: str


class HealthChecksConfig(BaseModel):
    """The rev-6 HealthGate YAML root.

    Loaded from ``configs/health/health_checks.yaml`` by
    ``load_health_gates_config``. See
    ``docs/design/pluggable_health_checks.md`` §3.
    """

    health_gates: list[GateConfig] = Field(
        default_factory=list,
        description=(
            "Ordered list of gates. Empty list = no gates fire "
            "(``get_gates_for_position`` returns ``[]`` for every round).\n\n"
            "Step 08b: this is the COMPOSED roster in a materialized "
            "effective config. In the shipped framework config it is empty — "
            "the roster is task-owned and ``health_policy`` below is what "
            "the framework contributes."
        ),
    )
    health_policy: dict[str, DispositionPolicy] = Field(
        default_factory=dict,
        # EXCLUDED from serialization on purpose. The policy table is an
        # INPUT to composition, not part of its result: once gates are
        # composed, each one carries its resolved role, cadence, actions and
        # short-circuit directly. Emitting it into the materialized effective
        # config would put the same facts in the document twice — and would
        # change the pinned sha of every existing workspace for a change in
        # nothing.
        exclude=True,
        description=(
            "Disposition → what the framework DOES for gates of that "
            "disposition (Step 08b §3.7). The operator policy surface: "
            "gate role, cadence, short-circuit, actions, severity and "
            "per-check policy keys such as ``aggregation``.\n\n"
            "Empty means the built-in default table, which reproduces the "
            "six shipped gates exactly — so a pre-08b custom YAML keeps "
            "working without acquiring a block it never had. The shipped "
            "observe-mode config exists precisely because this is data: it "
            "differs from the production config ONLY in ``on_fail`` for "
            "blocking gates."
        ),
    )

    task_health_binding: str | None = Field(
        default=None,
        # EXCLUDED from serialization for the same reason `health_policy` is,
        # and additionally because `materialize_effective_config` writes this
        # key itself from `body_markers`. Emitting it from the model too would
        # put it in the document twice and move the pinned sha of every
        # existing workspace for a change in nothing.
        exclude=True,
        description=(
            "The binding state a MATERIALIZED effective config was composed "
            "under, as written into its hashed body by "
            "``_composition.body_markers``: ``legacy_default`` / "
            "``explicit_none`` / ``explicit``.\n\n"
            "``None`` means the document does not declare one — a framework "
            "policy file, or a pre-08b hand-written YAML. Declared here so "
            "the marker SURVIVES the load: it is the only thing that "
            "distinguishes an EXPLICITLY EMPTY roster from an absent one, "
            "and while it was dropped as an undeclared extra an "
            "``explicit_none`` effective config read back as 'no roster "
            "supplied' and acquired the legacy task's family (F-6)."
        ),
    )
    resolved_plugins: tuple[PersistedHealthPluginIdentity, ...] = Field(
        default=(),
        exclude=True,
        description=(
            "Canonical plugin identities read from a materialized effective "
            "config. They are provenance, not a second plugin-loading path."
        ),
    )

    def resolved_policy(self) -> dict[str, DispositionPolicy]:
        """The policy table in effect — declared, or the built-in default."""
        return self.health_policy or default_disposition_policy()

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

_CACHED_BINDING_IDENTITY: tuple[Any, ...] | None = None
"""The resolved binding ``_CACHED_GATES`` was composed under.

``None`` means nothing is memoized. See :func:`_resolved_binding_identity`
for why the memo is keyed on this and on nothing else.
"""


def _resolved_binding_identity(path: str | None) -> tuple[Any, ...]:
    """Which binding is resolved in this process RIGHT NOW.

    Read entirely from run-scoped state that is **already in memory**: no
    file is opened, no plugin is re-read and no digest is recomputed. That
    is the whole point — a key whose computation paid the composition's I/O
    would have reinvented the cost it exists to remove.

    The components are exactly the three run-scoped globals that a
    composition ESTABLISHES and that ``_plugin_binding.reset_run_scope``
    clears — the plugin set loaded into this process, the bound task's
    declared facts, and the resolved view bindings. Completeness against
    that list is not an assertion here; it is pinned executably by
    ``tests/unit/execute_tools/health_checks/test_c12p_cp12_composition_cache_authority.py``,
    so a fourth run-scoped global cannot be added without the key learning
    to observe it. ``path`` is part of the key because a different source
    file is a different composition; only the default path is ever
    memoized, so the memoized key's ``path`` component is always ``None``.

    TWO DIFFERENT MECHANISMS PROTECT THIS KEY, and conflating them is how
    someone reintroduces the very defect this memo exists to kill.

    ``_RUN_SCOPE`` and ``_TASK_FACTS`` are **REBOUND** (``_plugin_binding``
    :421 / :599 and :540 / :600). They must be read through the MODULE,
    never ``from ... import _RUN_SCOPE``, because an imported name would be
    a snapshot taken at import time and would answer this question with the
    state of a process that no longer exists.

    ``_VIEW_BINDINGS`` is **MUTATED IN PLACE and never rebound** — declared
    once at ``_plugin_binding:191``, then ``.clear()`` + ``.update()`` at
    :534-535 and ``.clear()`` at :601. For that component the module read
    buys nothing; what protects it is ``tuple(sorted(...items()))``, a
    VALUE SNAPSHOT taken at key-build time and therefore immune to in-place
    mutation.

    **Do not "simplify" that component to ``_plugin_binding._VIEW_BINDINGS``**
    to match the shape of its two neighbours. The key would then hold a live
    reference to a dict that is mutated in place, the memo comparison would
    compare that dict to itself, it would ALWAYS be equal, and a CHANGED view
    binding would produce a silent memo HIT serving a stale config — this
    PR's own defect, one layer up.
    """
    return (
        path,
        _plugin_binding._RUN_SCOPE,
        _plugin_binding._TASK_FACTS,
        tuple(sorted(_plugin_binding._VIEW_BINDINGS.items())),
    )


def _resolve_config_path(path: str | None) -> str:
    """Preserve explicit paths and falsey-path compatibility for the default."""
    return path or default_health_policy_path()


def _load_raw_health_config(path: str | None = None) -> HealthChecksConfig:
    """Parse one config file verbatim. No composition, no binding.

    Split out at Step 08b C5 so composition has something to build FROM
    without recursing through the public loader.
    """
    resolved = _resolve_config_path(path)
    if resolved == default_health_policy_path():
        return HealthChecksConfig(health_policy=default_disposition_policy())
    with open(resolved) as f:
        raw = yaml.safe_load(f) or {}
    return HealthChecksConfig.model_validate(raw)


def load_health_gates_config(path: str | None = None) -> HealthChecksConfig:
    """The HealthGate config IN EFFECT — framework policy plus task roster.

    Cached per process for the default path. When ``path`` is provided
    the cache is bypassed and the returned config is not cached — so
    tests can point at a fixture YAML without polluting the default
    cache.

    **Step 08b C5: this returns the COMPOSED config.** The framework file
    now carries policy only, so a loader that returned it verbatim would
    hand every caller an empty roster. Composition happens here, once, which
    is why no consumer had to change: `runner`, `candidate_eligibility`,
    `launch_policy`, `evaluation` and `scripts/run_comparison.py` all keep
    asking the same question and keep getting the roster that will actually
    run.

    A file that is already composed — a materialized effective config (which
    DECLARES its binding, including an explicitly EMPTY roster), or a
    pre-08b/custom YAML carrying its own gates — is returned untouched (see
    :func:`load_composed_health_config`).

    **F-C12P-CP12-1: the memo is keyed on the RESOLVED BINDING, because
    composing is not only a computation — it BINDS.** It resolves the task's
    Health plugin set into this process's run scope
    (``_plugin_binding.load_task_health_plugins``) and replaces the regime-A
    fact derivation with the task's DECLARED facts
    (``_plugin_binding.resolve_task_health_bindings`` → ``_TASK_FACTS``).
    Those globals have their own lifecycle and are cleared independently of
    this cache, so the original memo — keyed on NOTHING, and therefore able
    to return a value composed under a *different* binding — made composition
    AUTHORITY depend on cache warmth: the same declaration resolved TIDMAD's
    declared facts in a cold process and ``None`` — the regime-A fallback,
    with no ``value_scale`` — in a warm one, and a run whose first health
    resolution bound nothing then let a second, DIFFERENT family bind past
    the run-scope guard.

    Keying on :func:`_resolved_binding_identity` fixes exactly that and
    nothing else. Cold: no memo, so it composes and binds. Warm under the
    SAME binding: recomposing could not reach a different result or a
    different binding, so the memo is sound and the call is O(1). Warm under
    a DIFFERENT binding: a MISS *by construction*, so it recomposes and the
    Step-08b run-scope guard fires exactly as it does cold. **The property
    that survives is the one that matters — a cold process and a warm one
    resolve the same authority** — and it survives without paying the
    composition's file I/O on all 17 call sites, several of them per
    gate evaluation.

    The rejected alternative was to split "ensure the binding is established"
    from "load the config": it still pays the binding's I/O on every call
    just to discover the bind is idempotent, which is the cost being removed.

    Args:
        path: Optional override for the config file location.

    Returns:
        A validated ``HealthChecksConfig`` whose ``health_gates`` are the
        gates in effect.
    """
    global _CACHED_GATES, _CACHED_BINDING_IDENTITY
    if (
        path is None
        and _CACHED_GATES is not None
        and _resolved_binding_identity(path) == _CACHED_BINDING_IDENTITY
    ):
        return _CACHED_GATES
    cfg, _task_config, _plugins = load_composed_health_config(path)
    if path is not None:
        return cfg
    # Recorded AFTER composing: the key describes the binding this value was
    # composed under, which is precisely the state composition just left
    # behind. Never recorded on the failure path — an exception propagates
    # before this line, so a refused composition memoizes nothing.
    _CACHED_GATES = cfg
    _CACHED_BINDING_IDENTITY = _resolved_binding_identity(path)
    return _CACHED_GATES


def clear_health_gates_config_cache() -> None:
    """Clear the process-wide cache for the rev-6 config. Test-only —
    never call from production code.

    Resets the memoized value AND its binding key together: a key left
    behind without its value (or the reverse) is the half-cleared state the
    keying exists to make impossible.
    """
    global _CACHED_GATES, _CACHED_BINDING_IDENTITY
    _CACHED_GATES = None
    _CACHED_BINDING_IDENTITY = None


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
    # ``health_policy`` and ``task_health_binding`` are excluded from the dump
    # (see their Fields), so they are carried across explicitly. A "pure
    # transform" that silently dropped a field would be a worse defect than
    # the one this function fixes — and dropping the binding marker is
    # precisely how an explicitly-empty roster stopped being distinguishable
    # from an absent one (F-6).
    return HealthChecksConfig.model_validate(
        {
            **dumped,
            "health_policy": config.health_policy,
            "task_health_binding": config.task_health_binding,
        }
    )


def validate_health_scope(
    config: HealthChecksConfig,
    resolved_scope: list[int],
    *,
    dataset_partition_count: int | None = None,
) -> None:
    """Startup invariant: every file-accessing check stays inside the scope.

    Covers ALL checks, not only blocking ones. A check WITHOUT an explicit
    ``peek_file_indices`` reads the full dataset by default (recording
    checks fall back to ``range(num_files)``; blocking checks to the
    pre-M9 single-file peek) — under a partial DataScope that implicit
    full-dataset access is itself a violation. No intersection, no
    fallback, no silent correction: violations fail before any execution.

    Raises:
        ValueError: Listing every offending gate/check with remediation.

    ``dataset_partition_count`` is the resolved run topology when composition
    has not yet been activated. Omitting it preserves the bound/legacy lookup.
    """
    scope_set = set(resolved_scope)
    num_files = (
        dataset_partition_count
        if dataset_partition_count is not None
        else resolve_dataset_profile().partition_count
    )
    scope_is_full = scope_set == set(range(num_files))
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


def _load_task_binding(
    binding: TaskHealthBinding,
) -> tuple[TaskHealthConfig | None, tuple[ResolvedHealthPlugin, ...]]:
    """Resolve an explicit task-health-config binding (§3.10 state C).

    States A and B load nothing: "the caller said nothing" and "the caller
    says there is none" are different claims, and NEITHER may be satisfied by
    reading some other task's config. That distinction is what stops a task
    which deliberately declares no health from silently inheriting another
    task's family.

    Returns:
        ``(task_config, resolved_plugins)``; ``(None, ())`` for states A and B.
    """
    if binding is HealthBindingState.EXPLICIT_NONE:
        return None, ()
    if binding is HealthBindingState.LEGACY_OMITTED:
        return None, ()
    resolved_ref = binding

    from execute_tools.health_checks._plugin_binding import (
        load_task_health_plugins,
        resolve_task_health_bindings,
    )

    with open(resolved_ref) as handle:
        raw = yaml.safe_load(handle) or {}
    task_config = TaskHealthConfig.model_validate(raw)  # Phase A
    config_dir = os.path.dirname(os.path.abspath(resolved_ref))
    resolved_plugins = load_task_health_plugins(task_config, config_dir)
    resolve_task_health_bindings(task_config)  # Phase B — fails closed
    return task_config, resolved_plugins


def load_composed_health_config(
    source_path: str | None = None,
    task_health_binding: TaskHealthBinding = HealthBindingState.LEGACY_OMITTED,
) -> tuple[HealthChecksConfig, TaskHealthConfig | None, tuple[ResolvedHealthPlugin, ...]]:
    """The gate roster in effect, composed from framework policy + task config.

    **The one composition path.** ``load_health_gates_config`` stays a pure
    loader of whatever file it is given; this is what any caller that needs
    the ROSTER should use, because after Step 08b C5 the framework file
    carries policy only and the roster is the task's.

    A config that is ALREADY COMPOSED is returned untouched, and there are two
    independent ways to recognize one:

    * it DECLARES the binding it was composed under
      (``task_health_binding``, written into every materialized effective
      config by :func:`~execute_tools.health_checks._composition.body_markers`);
    * or it carries gates — a pre-08b or hand-written custom YAML with its own
      roster, and any effective config materialized before the marker existed.

    Neither should acquire a second roster from a task binding, and the
    "two authorities" refusal in :func:`resolve_composed_gates` states the
    same principle from the other side.

    **F-6: the declaration is asked FIRST, and the gate list's truthiness is
    not a substitute for it.** ``EXPLICIT_NONE`` materializes ``health_gates:
    []`` — a roster that is EMPTY BY DECISION — and ``if cfg.health_gates:``
    reads that as "no roster supplied", so reading such a config back composed
    the legacy task's family into a run that had declared it has none. That is
    the one thing ``EXPLICIT_NONE`` exists to make impossible.

    Returns:
        ``(config, task_config, resolved_plugins)`` — the latter two are
        ``None``/empty unless a task binding was actually loaded here.
    """
    cfg = _load_raw_health_config(source_path)

    if task_health_binding is HealthBindingState.EXPLICIT_NONE:
        # A NAMED absence outranks whatever the framework file happens to
        # carry: a task stating it has no Health binding must never acquire
        # a roster, least of all another task's.
        return cfg.model_copy(update={"health_gates": []}), None, ()

    if cfg.task_health_binding is not None or cfg.health_gates:
        return cfg, None, ()

    task_config, resolved_plugins = _load_task_binding(task_health_binding)
    if task_config is None:
        return cfg, None, ()
    composed = resolve_composed_gates([], task_config, cfg.resolved_policy())
    return (
        HealthChecksConfig.model_validate(
            {"health_gates": composed, "health_policy": cfg.health_policy}
        ),
        task_config,
        resolved_plugins,
    )


def _record_path(path: str) -> str:
    """How a config path is RENDERED into a persisted artifact.

    **Resolve absolutely; record relatively.** F-7 anchored the shipped-config
    defaults to ``SIDERIUS_ROOT`` so they stop depending on the caller's
    working directory — a correct fix for LOADING, and the wrong string to
    WRITE DOWN. A materialized effective config that names
    ``/home/<whoever>/<some-checkout>/configs/health_checks.yaml`` embeds the
    identity of the machine that produced it, and its byte length then varies
    by environment: the Step-09.5a envelope oracle caught exactly that, and
    the deeper problem is that no stable baseline for it could exist. A
    persisted artifact carrying one developer's absolute path is the failure
    CLAUDE.md's portability section is written about — so closing F-7 must not
    reintroduce it one layer over.

    The header's job is PROVENANCE — *which framework config was this composed
    from* — and ``configs/health_checks.yaml`` answers that better on every
    machine than an absolute path that is true on exactly one.

    An EXTERNAL file keeps its absolute form, deliberately: there the absolute
    path IS the informative answer, and no repo-relative rendering of it could
    be either honest or stable.

    Args:
        path: the path as resolved for loading (absolute or relative).

    Returns:
        The repo-relative path when it lies inside this checkout, else the
        absolute path.
    """
    absolute = Path(path).resolve()
    if absolute == Path(default_health_policy_path()):
        return DEFAULT_POLICY_LABEL
    if SIDERIUS_ROOT is None:
        return str(absolute)
    root = Path(SIDERIUS_ROOT).resolve()
    if absolute.is_relative_to(root):
        return str(absolute.relative_to(root))
    return str(absolute)


def materialize_effective_config(
    source_path: str | None,
    files: list[int] | None,
    workspace: str,
    resolved_scope: list[int] | None = None,
    task_health_binding: TaskHealthBinding = HealthBindingState.LEGACY_OMITTED,
    dataset_partition_count: int | None = None,
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

    ``task_health_binding`` selects between the three binding states (§3.10).
    An omitted binding means that no task roster was declared; it does not
    silently select a framework-shipped scientific task. Tasks that use
    Health checks pass their own config path explicitly.

    Returns:
        (effective_config_path, body_sha256)

    ``dataset_partition_count`` lets a composed preflight validate completeness
    against the already-resolved task instead of consulting an unbound default.
    """
    cfg, _task_config, resolved_plugins = load_composed_health_config(
        source_path, task_health_binding
    )
    if files is not None:
        cfg = apply_monitored_files(cfg, files)
    if resolved_scope is not None:
        validate_health_scope(
            cfg,
            resolved_scope,
            dataset_partition_count=dataset_partition_count,
        )

    markers = body_markers(task_health_binding, resolved_plugins)
    if (
        task_health_binding is not HealthBindingState.EXPLICIT_NONE
        and not resolved_plugins
        and cfg.resolved_plugins
    ):
        markers["resolved_plugins"] = [
            identity.model_dump(mode="json") for identity in cfg.resolved_plugins
        ]
    document = {**cfg.model_dump(mode="json"), **markers}
    body = yaml.safe_dump(document, sort_keys=True)
    sha = hashlib.sha256(body.encode()).hexdigest()
    files_repr = sorted({int(i) for i in files}) if files else None
    header = (
        "# Materialized effective HealthGate config — do not edit.\n"
        "# Written by materialize_effective_config (enable_partial_file_list DS4).\n"
        # Rendered, not the resolved string: see `_record_path`. This line is
        # provenance for a human reader and is never parsed back, but it IS
        # written, so it must not make the artifact's bytes depend on which
        # checkout produced them.
        f"# source: {_record_path(_resolve_config_path(source_path))}\n"
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


def read_effective_config_body_sha(path: str) -> str | None:
    """Canonical body sha of a materialized effective config, from its BYTES.

    The single implementation of "what is this artifact's body sha", so
    ``core/resume.py`` no longer mirrors the computation. That mirror
    re-derived the sha by loading the file into ``HealthChecksConfig`` and
    re-dumping it, which silently dropped any key the model does not
    declare — and Step 08b's ``resolved_plugins`` / ``task_health_binding``
    are exactly such keys. A verifier that cannot see part of what was hashed
    reports a mismatch that is not there.

    Hashing the on-disk body is also strictly more faithful: it verifies the
    bytes the run actually reads, rather than a re-serialization that could
    drift from them.

    Returns:
        The sha256, or ``None`` when the file is missing or unparseable —
        the same contract the previous mirror offered its callers.
    """
    try:
        with open(path) as handle:
            content = handle.read()
    except OSError:
        return None

    lines = content.splitlines(keepends=True)
    start = 0
    for index, line in enumerate(lines):
        if not line.startswith("#"):
            start = index
            break
    else:
        return None
    body = "".join(lines[start:])

    try:
        # Parsed for validity only; the sha comes from the bytes above.
        yaml.safe_load(body)
    except yaml.YAMLError:
        return None
    return hashlib.sha256(body.encode()).hexdigest()


def _header_value(content: str, prefix: str) -> str | None:
    """Extract a materialization-header value; None when the line is absent."""
    for line in content.splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
        if not line.startswith("#"):
            break
    return None
