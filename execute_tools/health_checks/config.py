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

import os
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from execute_tools.health_checks.schemas import GateAction

_DEFAULT_CONFIG_PATH: str = os.path.join("configs", "health_checks.yaml")


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
