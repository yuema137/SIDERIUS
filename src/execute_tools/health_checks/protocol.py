# execute_tools/health_checks/protocol.py
"""
Protocol contract every rev-6 health check implements.

See ``docs/design/pluggable_health_checks.md`` §6 and, for the Step-08a
applicability contract that supersedes its "not applicable" convention,
``docs/design/generic_framework_upgrade/step_08_health_check_task_profile.md``
§7.
"""

from __future__ import annotations

from typing import Any, ClassVar, Protocol, runtime_checkable

from execute_tools.health_checks._view_provider import HealthView
from execute_tools.health_checks.schemas import (
    CheckInputDeclaration,
    HealthCheckContext,
    HealthCheckResult,
)


@runtime_checkable
class HealthCheckSkill(Protocol):
    """Contract every rev-6 health check implements.

    **Step 08a — a check declares its inputs; it does not excuse itself.**
    The rev-6 contract used to say that a skill finding its inputs missing
    should return a PASSING result carrying a "not applicable" reason. That
    made inapplicability indistinguishable from health in every aggregate,
    count and record: the gate's ``all(r.passed …)``, candidate eligibility
    and the persisted status could not tell "the output is fine" from "this
    question does not arise here", and persistence had to recover the truth
    by string-matching prose.

    A check now publishes a :class:`CheckInputDeclaration` as data, and
    ``evaluate_gate`` compares it against the bound task's declared facts
    and the round context BEFORE invoking ``run`` — so an inapplicable
    check is never asked to inspect anything, opens no artifact, and is
    recorded as ``CheckVerdict.INAPPLICABLE``, which never counts as a
    pass. See the Step-08 parent design §7.

    A check may still return a defensive typed inapplicable result when
    invoked directly with inputs it cannot use; that is a safety net for
    non-gate callers, not the mechanism.
    """

    name: ClassVar[str]

    declaration: ClassVar[CheckInputDeclaration]
    """What this check consumes: view capability key, required context
    inputs, required task-fact axes, and which config keys are task
    thresholds.

    Required of checks written from Step 08a onward. ``evaluate_gate``
    remains tolerant of its absence — a check without one is treated as
    unconditionally applicable, which is exactly pre-08a behaviour — so a
    pre-08a or externally supplied check keeps working unchanged.
    """

    def run(
        self,
        ctx: HealthCheckContext,
        config: dict[str, Any] | None = None,
        *,
        view: HealthView | None = None,
    ) -> HealthCheckResult:
        """Execute the check.

        Args:
            ctx: Shared context — the skill reads only the fields it needs.
            config: Per-gate threshold overrides from
                ``configs/health/health_checks.yaml``. ``None`` (default) means
                the skill uses its own defaults. Partial config overlays:
                skills merge provided keys over their instance defaults,
                so YAML can override just one threshold and leave the
                rest at the check's default.
            view: The materialized view this check declared, when it
                declared ``requires_view`` and a provider was bound
                (Step 08b). **Backward compatibility is a DISPATCH rule,
                not merely this default**: a check that does not require a
                view is invoked as ``run(ctx, config)`` and is never
                gratuitously passed ``view=None``, so a pre-08b or
                externally supplied check is called exactly as it always
                was. The parameter exists on this Protocol so a
                view-consuming check is structurally typed; implementations
                that ignore views accept it and never see it.
        """
        ...
