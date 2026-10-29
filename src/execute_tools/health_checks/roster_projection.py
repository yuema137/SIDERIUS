"""Public, read-only projection of the Health roster a task declares.

Display callers (the console Task panel) need to know WHICH gates a task's
Health declaration composes and what each means scientifically, without
re-deriving policy. This module answers that question through the one
composition path (:func:`~execute_tools.health_checks.config.load_composed_health_config`)
and the declared ``gate_role``; it never infers a role from an action, a gate
id or a check name.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from execute_tools.health_checks._composition import HealthBindingState, TaskHealthBinding
from execute_tools.health_checks.config import (
    load_composed_health_config,
    load_health_gates_config,
)


class HealthRosterGate(BaseModel):
    """One composed gate with its DECLARED ``gate_role``; ``None`` means undeclared.

    ``blocking`` gates decide candidate validity; ``observational`` gates only
    record (a task's ``recording`` disposition composes to ``observational``).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    gate_id: str
    checks: tuple[str, ...]
    role: Literal["blocking", "observational"] | None


class HealthRosterProjection(BaseModel):
    """``declaration`` names the binding state; ``gates`` is the composed roster.

    ``explicit_none`` is a declared absence (always zero gates). ``not_declared``
    is the omitted binding, whose roster is whatever the framework file carries
    (normally none). ``declared`` is an explicit task Health configuration.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    declaration: Literal["declared", "explicit_none", "not_declared"]
    gates: tuple[HealthRosterGate, ...]


def project_health_roster(binding: TaskHealthBinding) -> HealthRosterProjection:
    """Compose the roster exactly as a run would and project gate, checks and role.

    Loading an explicit task binding imports its declared Health plugins, so
    callers must run this where task code may execute (a sandboxed child).
    """
    if binding is HealthBindingState.LEGACY_OMITTED:
        declaration: Literal["declared", "explicit_none", "not_declared"] = "not_declared"
        config = load_health_gates_config(None)
    else:
        declaration = "explicit_none" if binding is HealthBindingState.EXPLICIT_NONE else "declared"
        config, _task_config, _plugins = load_composed_health_config(None, binding)
    return HealthRosterProjection(
        declaration=declaration,
        gates=tuple(
            HealthRosterGate(
                gate_id=gate.id,
                checks=tuple(check.name for check in gate.checks),
                role=gate.gate_role,
            )
            for gate in config.health_gates
        ),
    )
