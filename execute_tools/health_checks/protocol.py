# execute_tools/health_checks/protocol.py
"""
Protocol contract every rev-6 health check implements.

See ``docs/design/pluggable_health_checks.md`` §6.
"""

from __future__ import annotations

from typing import Any, ClassVar, Protocol, runtime_checkable

from execute_tools.health_checks.schemas import (
    HealthCheckContext,
    HealthCheckResult,
)


@runtime_checkable
class HealthCheckSkill(Protocol):
    """Contract every rev-6 health check implements.

    Rev-6 note: no ``is_applicable`` step — the pre-migration Protocol
    had one but the HealthGate model dropped it. Skills are always
    invoked by ``evaluate_gate``; a skill that finds its inputs
    missing should return ``HealthCheckResult(passed=True, reason=
    "<check_name>: not applicable — <what's missing>")``. This
    simplifies gate reasoning: every check contributes a definite
    pass/fail verdict, and routing decisions live in the gate's
    ``on_pass`` / ``on_fail`` config rather than in an implicit skip
    step.

    See ``docs/design/pluggable_health_checks.md`` §6.
    """

    name: ClassVar[str]

    def run(
        self,
        ctx: HealthCheckContext,
        config: dict[str, Any] | None = None,
    ) -> HealthCheckResult:
        """Execute the check.

        Args:
            ctx: Shared context — the skill reads only the fields it needs.
            config: Per-gate threshold overrides from
                ``configs/health_checks.yaml``. ``None`` (default) means
                the skill uses its own defaults. Partial config overlays:
                skills merge provided keys over their instance defaults,
                so YAML can override just one threshold and leave the
                rest at the check's default.
        """
        ...
