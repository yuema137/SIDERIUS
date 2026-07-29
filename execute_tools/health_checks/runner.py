# execute_tools/health_checks/runner.py
"""
Runner for the pluggable HealthGate framework.

Implements the four rev-6 tuner-facing functions from design §8:
    * ``severity_of(action)`` — integer severity of a GateAction
    * ``resolve_action(gate_results)`` — most-severe action from a batch
    * ``get_gates_for_position(round_index)`` — gate ids at a round
    * ``evaluate_gate(gate_id, ctx)`` — evaluate a named gate → GateResult

Production uses ``load_health_gates_config()`` from ``config.py`` (returns
a Pydantic-validated ``HealthChecksConfig``) rather than raw-dict access
against the YAML — the design doc §8 pseudo-code predates commit-2's
schema. Semantics are identical; the models add validation.

See ``docs/design/pluggable_health_checks.md`` §8.
"""

from __future__ import annotations

from collections.abc import Iterable

from execute_tools.health_checks.config import load_health_gates_config
from execute_tools.health_checks.registry import get

# _SEVERITY / severity_of moved to schemas.py (V19 PR 3 CB1 — the
# side-effect-free canonical home; see pr3_healthgate_feedback.md §2.5).
# Re-imported here so every existing ``from ...runner import severity_of``
# call site keeps working unchanged. The ordering logic is defined ONCE,
# in schemas.py.
from execute_tools.health_checks.schemas import (
    _SEVERITY,
    GateAction,
    GateResult,
    HealthCheckContext,
    HealthCheckResult,
)
from execute_tools.health_checks.schemas import severity_of as severity_of


def resolve_action(gate_results: Iterable[GateResult]) -> GateAction:
    """Pick the most-severe action across a batch of gate results.

    Empty iterable returns ``GateAction.CONTINUE`` (the identity element for
    max-severity — no gates means proceed normally). Accepts any iterable,
    not just a list, so callers can pipe generators through.
    """
    max_action = GateAction.CONTINUE
    max_severity = _SEVERITY[max_action]
    for gr in gate_results:
        s = _SEVERITY[gr.action]
        if s > max_severity:
            max_action = gr.action
            max_severity = s
    return max_action


def get_gates_for_position(round_index: int, config_path: str | None = None) -> list[str]:
    """Return the ids of gates configured to fire at this round.

    Multiple gates may share a round position. Empty list = no gates fire →
    the tuner proceeds with no per-round overhead. Matching is delegated to
    ``GateConfig.matches_round`` so the three ``after_round`` forms (int,
    ``"every"``, list[int]) are handled uniformly.
    """
    config = (
        load_health_gates_config(config_path)
        if config_path is not None
        else load_health_gates_config()
    )
    return [g.id for g in config.health_gates if g.matches_round(round_index)]


def evaluate_gate(
    gate_id: str, ctx: HealthCheckContext, config_path: str | None = None
) -> GateResult:
    """Evaluate a named gate from ``configs/health_checks.yaml``.

    Runs the gate's checks in config-listed order. When the gate's
    ``short_circuit`` (default True per commit-2 D4) is set, stops at the
    first failure. Returns a ``GateResult`` with ``action = on_pass`` when
    every check passed, otherwise ``action = on_fail``. ``round_index`` is
    propagated from ``ctx.round_index`` for logging.

    Args:
        gate_id: The gate's id in the YAML. Raises ``ValueError`` with the
            available gate list when the id is unknown — fail-loud during dev.
        ctx: Shared context passed verbatim to each skill's ``run``.

    Raises:
        ValueError: ``gate_id`` not present in ``health_checks.yaml``.
        KeyError: A referenced check name is not in the registry (bubbles up
            from ``registry.get``).
    """
    config = (
        load_health_gates_config(config_path)
        if config_path is not None
        else load_health_gates_config()
    )
    gate_cfg = next((g for g in config.health_gates if g.id == gate_id), None)
    if gate_cfg is None:
        available = sorted(g.id for g in config.health_gates)
        raise ValueError(
            f"Gate {gate_id!r} not found in health_checks.yaml. Available: {available!r}."
        )

    check_results: list[HealthCheckResult] = []
    first_failure_reason = ""
    for check_ref in gate_cfg.checks:
        skill = get(check_ref.name)
        # D8-B: empty CheckRef.config becomes None so the skill sees "use
        # defaults" per Protocol §6, matching design §8's ``.get("config")``
        # semantic.
        cfg_override = check_ref.config or None
        # Bug B fix (PR #101 Gate 2 forensic, 2026-07-15): guard the skill
        # call so an unhandled exception inside a check does not propagate
        # out of evaluate_gate and crash the tuner. Individual checks may
        # still catch their own expected exceptions (e.g. output_diversity
        # catches OSError from peek), but this outer guard covers the
        # residual "any other raise" case. The resulting gate action still
        # comes from ``on_fail`` per the gate's YAML config, keeping policy
        # in config and mechanism in code.
        try:
            result = skill.run(ctx, config=cfg_override)
        except Exception as exc:
            import traceback

            _err_name = type(exc).__name__
            print(
                f"[Gate {gate_id}] check {check_ref.name!r} raised {_err_name}: {exc}",
                flush=True,
            )
            traceback.print_exc()
            result = HealthCheckResult(
                check_name=check_ref.name,
                passed=False,
                reason=(f"{check_ref.name}: check raised unexpected {_err_name}: {exc}"),
                metrics={"exception_type": _err_name},
            )
        check_results.append(result)
        if not result.passed and not first_failure_reason:
            first_failure_reason = result.reason
        if not result.passed and gate_cfg.short_circuit:
            break

    gate_passed = all(r.passed for r in check_results)
    return GateResult(
        gate_id=gate_id,
        round_index=ctx.round_index,
        passed=gate_passed,
        action=gate_cfg.on_pass.action if gate_passed else gate_cfg.on_fail.action,
        failure_reason="" if gate_passed else first_failure_reason,
        check_results=check_results,
    )
