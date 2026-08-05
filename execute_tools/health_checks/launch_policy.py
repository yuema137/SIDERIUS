"""Startup refusal for a formal launch whose declared policy is unusable.

V20 PR D, checkpoint D-C1b.

D-C1a made ``healthgate_mode`` and ``result_authority`` **declared** facts.
This module is what makes the declaration mean something: a new formal
launch whose declaration is missing, self-contradictory, or contradicted by
the HealthGate config it is about is refused **before** the first LLM call,
model construction or GPU work.

Five refusals, and each exists because the alternative is a silent lie:

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

from execute_tools.health_checks.candidate_eligibility import resolve_scientific_gate_ids
from execute_tools.health_checks.config import load_health_gates_config
from execute_tools.health_checks.schemas import BLOCKING_ACTIONS


class FormalLaunchPolicyError(ValueError):
    """A formal launch may not proceed with the declared policy.

    A ``ValueError`` so it joins the existing startup-configuration failure
    convention (``validate_runtime_config`` raises the same type) rather
    than inventing a new classification. A policy mismatch is emphatically
    **not** a candidate failure, a HealthGate round failure, an operator
    stop, or GPU evidence.
    """


def _enforcing_gate_ids(config_path: str | None) -> frozenset[str]:
    """Gate ids whose failure actually invalidates, by configured action.

    This is the ENFORCEMENT question — deliberately action-derived, which
    is correct here and wrong for scientific membership. Keeping the two
    questions apart is the whole point of the role hotfix.
    """
    config = load_health_gates_config(config_path)
    return frozenset(g.id for g in config.health_gates if g.on_fail.action in BLOCKING_ACTIONS)


def validate_formal_launch(
    *,
    healthgate_mode: str | None,
    result_authority: str | None,
    health_checks_config: str | None,
    gates_enabled: bool,
    skip_formal_min_delta: float,
    bypass_formal_time_budget_min_delta: float,
) -> None:
    """Refuse a formal launch whose declared policy cannot be honoured.

    Args:
        healthgate_mode: the declared enforcement mode, or ``None``.
        result_authority: the declared result authority, or ``None``.
        health_checks_config: the operator's HealthGate config path;
            ``None`` means the shipped default.
        gates_enabled: whether the chain-incumbent formal gates are on.
            The delta-ordering invariant is checked **only** when they are
            — an unused historical delta pair must not block a launch.
        skip_formal_min_delta: the skip margin.
        bypass_formal_time_budget_min_delta: the bypass margin.

    Raises:
        FormalLaunchPolicyError: any of the five refusals above.
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
    enforcing = _enforcing_gate_ids(health_checks_config)
    scientific = resolve_scientific_gate_ids(health_checks_config)

    if healthgate_mode == "blocking":
        if scientific is None:
            raise FormalLaunchPolicyError(
                f"healthgate_mode=blocking, but the roles in "
                f"{health_checks_config!r} cannot be established — it "
                f"declares no gate_role and its sha is not in the audited "
                f"compatibility map. A new formal launch must declare every "
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

    # --- 5. delta ordering, only where the deltas are consumed ---------
    if gates_enabled and skip_formal_min_delta > bypass_formal_time_budget_min_delta:
        raise FormalLaunchPolicyError(
            f"skip_formal_min_delta ({skip_formal_min_delta}) must not "
            f"exceed bypass_formal_time_budget_min_delta "
            f"({bypass_formal_time_budget_min_delta}). Inverted, BOTH formal "
            f"gates fire for the same trial score and the outcome is decided "
            f"by statement order rather than by policy."
        )
