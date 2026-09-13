"""Startup refusal for a formal launch whose declared policy is unusable.

V20 PR D, checkpoint D-C1b.

D-C1a made ``healthgate_mode`` and ``result_authority`` **declared** facts.
This module is what makes the declaration mean something: a new formal
launch whose declaration is missing, self-contradictory, or contradicted by
the HealthGate config it is about is refused **before** the first LLM call,
model construction or GPU work.

Six refusals, and each exists because the alternative is a silent lie:

1. **``healthgate_mode`` omitted** — there is no safe default. Defaulting to
   ``blocking`` would let a run claim enforcement nobody configured.
2. **``result_authority`` omitted** — same, one axis up: a run would claim
   scientific standing nobody granted.
3. **``observe_only + scientific``** — a contradiction. Gates that only
   record cannot certify anything.
4. **Declared mode contradicts the config's enforcement.** Declaring
   ``blocking`` over a config whose gates all ``continue`` is the exact
   shape of the 08:17-class defect: the artifact says enforced, the run was
   not.
5. **Inverted deltas** while the formal gates are enabled. Measured: an
   inverted pair makes *both* gates fire, and today the outcome is decided
   by statement order rather than policy.
6. **Non-finite deltas** while the formal gates are enabled (FU-D-8). NaN
   or an infinity makes every gate comparison ``False``, so the gates are
   *silently disabled* while the artifact still records an enforced run —
   the same fail-open shape as the missing bootstrap reference. Checked
   BEFORE the ordering rule, which NaN would otherwise defeat: ``NaN >
   NaN`` is ``False``, so an unusable pair would pass ordering unnoticed.

   The refusal is scoped to the **operator-configured deltas**. The
   internally resolved ``-inf`` comparison reference (§16.C) is a
   deliberate resolver value and stays legal — the two must not be
   conflated.

**Roles are never inferred here.** Membership comes from the shared
role-aware resolver merged in the predecessor hotfix (``af5339ce``), not
from the gate id, the ``_blocking`` suffix, the configured action or the
filename. Inferring the role from the action was the defect that hotfix
fixed, and re-deriving it here would reintroduce it one layer up.

**Why the SOURCE config is sufficient.** ``materialize_effective_config``
only applies ``apply_monitored_files`` (``peek_file_indices``) and
``validate_health_scope``; it never rewrites ``on_fail.action`` or
``gate_role``. So the enforcement semantics of the source and the
materialized effective config are identical, and this check can run at the
launch boundary — before materialization — without weakening it.
"""

from __future__ import annotations

import math

from execute_tools.health_checks._composition import HealthBindingState, TaskHealthBinding
from execute_tools.health_checks.candidate_eligibility import (
    resolve_run_scientific_gate_ids,
    resolve_scientific_gate_ids,
)
from execute_tools.health_checks.config import (
    load_composed_health_config,
    load_health_gates_config,
)
from execute_tools.health_checks.schemas import BLOCKING_ACTIONS


class FormalLaunchPolicyError(ValueError):
    """A formal launch may not proceed with the declared policy.

    A ``ValueError`` so it joins the existing startup-configuration failure
    convention (``validate_runtime_config`` raises the same type) rather
    than inventing a new classification. A policy mismatch is emphatically
    **not** a candidate failure, a HealthGate round failure, an operator
    stop, or GPU evidence.
    """


def _effective_config(
    config_path: str | None,
    task_health_binding: TaskHealthBinding,
):
    """Resolve the config governed by this launch without selecting a task."""
    if config_path is not None or task_health_binding is HealthBindingState.LEGACY_OMITTED:
        return load_health_gates_config(config_path)
    config, _task_config, _plugins = load_composed_health_config(None, task_health_binding)
    return config


def _enforcing_gate_ids(
    config_path: str | None,
    task_health_binding: TaskHealthBinding,
) -> frozenset[str]:
    """Gate ids whose failure actually invalidates, by configured action.

    This is the ENFORCEMENT question — deliberately action-derived, which
    is correct here and wrong for scientific membership. Keeping the two
    questions apart is the whole point of the role hotfix.
    """
    config = _effective_config(config_path, task_health_binding)
    return frozenset(g.id for g in config.health_gates if g.on_fail.action in BLOCKING_ACTIONS)


def validate_formal_launch(
    *,
    healthgate_mode: str | None,
    result_authority: str | None,
    health_checks_config: str | None,
    gates_enabled: bool,
    skip_formal_min_delta: float,
    bypass_formal_time_budget_min_delta: float,
    task_health_binding: TaskHealthBinding = HealthBindingState.LEGACY_OMITTED,
) -> None:
    """Refuse a formal launch whose declared policy cannot be honoured.

    Args:
        healthgate_mode: the declared enforcement mode, or ``None``.
        result_authority: the declared result authority, or ``None``.
        health_checks_config: the operator's HealthGate config path;
            ``None`` means the shipped default.
        gates_enabled: whether the chain-incumbent formal gates are on.
            The delta finiteness and ordering invariants are checked
            **only** when they are — an unused historical delta pair must
            not block a launch.
        skip_formal_min_delta: the skip margin. Must be finite when the
            gates are enabled.
        bypass_formal_time_budget_min_delta: the bypass margin. Same.

    Raises:
        FormalLaunchPolicyError: any of the six refusals above.
    """
    missing = [
        name
        for name, value in (
            ("--healthgate_mode", healthgate_mode),
            ("--result_authority", result_authority),
        )
        if value is None
    ]
    if missing:
        raise FormalLaunchPolicyError(
            f"a formal launch must declare {' and '.join(missing)}. There is "
            f"no default: defaulting to blocking/scientific would let this "
            f"run claim enforcement and scientific standing that nobody "
            f"configured. Declare both explicitly."
        )

    if healthgate_mode == "observe_only" and result_authority == "scientific":
        raise FormalLaunchPolicyError(
            "observe_only + scientific is a contradiction: gates that only "
            "record cannot certify a result. Use observe_only + diagnostic "
            "to observe, or blocking + scientific to enforce and certify. "
            "(blocking + diagnostic is also legal — enforced, deliberately "
            "not promoted.)"
        )

    # --- 4. the declaration must match the config it describes ---------
    enforcing = _enforcing_gate_ids(health_checks_config, task_health_binding)
    scientific = (
        resolve_scientific_gate_ids(health_checks_config)
        if health_checks_config is not None
        else resolve_run_scientific_gate_ids(task_health_binding)
    )

    if healthgate_mode == "blocking":
        if scientific is None:
            raise FormalLaunchPolicyError(
                f"healthgate_mode=blocking, but the roles in "
                f"{health_checks_config!r} cannot be established — it "
                f"has a missing gate_role. A new formal launch must declare every "
                f"gate's role; roles are never guessed from ids or actions."
            )
        unenforced = sorted(scientific - enforcing)
        if unenforced:
            raise FormalLaunchPolicyError(
                f"healthgate_mode=blocking, but these role:blocking gates "
                f"cannot invalidate anything in {health_checks_config!r}: "
                f"{unenforced}. The declaration says enforced and the "
                f"configuration says observe — the artifact would record a "
                f"policy the run did not have."
            )
    elif healthgate_mode == "observe_only" and enforcing:
        raise FormalLaunchPolicyError(
            f"healthgate_mode=observe_only, but these gates still "
            f"invalidate in {health_checks_config!r}: {sorted(enforcing)}. "
            f"An observe-only run must not be able to invalidate a round."
        )

    # --- 5+6. the deltas, only where they are consumed -----------------
    if not gates_enabled:
        # THE SCOPING RULE, unchanged from D-C1b: with the gates off the
        # deltas are never consumed, so an unused historical pair — however
        # malformed — must not block a launch.
        return

    # 6 (FU-D-8) — finiteness FIRST, because a NaN silently defeats the
    # ordering check below: every comparison against NaN is False, so
    # `skip > bypass` is False and an inverted-and-unusable pair would sail
    # through. A non-finite delta then disables BOTH gates at runtime for
    # the same reason — `score < NaN` and `score >= NaN` are both False —
    # which is the fail-open shape §16.C exists to eliminate.
    #
    # This rejects the OPERATOR-CONFIGURED deltas. It does NOT touch the
    # internally resolved `-inf` comparison reference, which is a
    # deliberate resolver value (§16.C) and a different concept entirely.
    non_finite = [
        f"{name}={value}"
        for name, value in (
            ("skip_formal_min_delta", skip_formal_min_delta),
            ("bypass_formal_time_budget_min_delta", bypass_formal_time_budget_min_delta),
        )
        if not math.isfinite(value)
    ]
    if non_finite:
        raise FormalLaunchPolicyError(
            f"the formal gates are enabled but these deltas are not finite: "
            f"{', '.join(non_finite)}. Every comparison against NaN or an "
            f"infinity is False, so the gate would be silently disabled "
            f"rather than loudly refused — the run would look enforced and "
            f"gate nothing. Configure finite deltas, or disable the gates "
            f"explicitly with --no-enable_chain_incumbent_formal_gates. "
            f"(The internally resolved -inf comparison reference is a "
            f"different thing and remains legal.)"
        )

    if skip_formal_min_delta > bypass_formal_time_budget_min_delta:
        raise FormalLaunchPolicyError(
            f"skip_formal_min_delta ({skip_formal_min_delta}) must not "
            f"exceed bypass_formal_time_budget_min_delta "
            f"({bypass_formal_time_budget_min_delta}). Inverted, BOTH formal "
            f"gates fire for the same trial score and the outcome is decided "
            f"by statement order rather than by policy."
        )
