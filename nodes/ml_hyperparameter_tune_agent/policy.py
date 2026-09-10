"""Tuner POLICY — decisions taken on already-computed values.

Step 07 PR 07b, C7 (operator scope amendment): moved VERBATIM out of
``ml_hyperparameter_tune_agent.py``. Zero behaviour change; the C1 replay
goldens and the PRE/POST differential oracle are the evidence.

What belongs here: given scores, statuses, plans and configs that someone else
produced, decide *what the run should do* — which trial won, whether the formal
round is worth its cost, where the thresholds sit, which records are the
``best_*`` incumbents, how a round ends, what the reflector is told.

What does NOT belong here: anything that talks to the GPU, the filesystem, the
LLM or a subprocess (``runtime``); anything that builds or persists an
``ExperimentRecord`` (``records``); and the interpretation of
``MetricSpec.direction`` itself — that authority is and stays
``execute_tools/metric_order.py``. This module CONSUMES a ``MetricOrder``; it
never re-derives one.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from agent.prompt_templates.tuner.rendering import (
    EFFICIENCY_BAND_FRACTION,
)
from agent.schemas.hyperparam_tuning import (
    TRIAL_SCOPED_OVERRIDE_KEYS,
    ExperimentPlan,
    HyperparamTuningInput,
    PlanOverridesError,
    TrialConfig,
)
from agent.schemas.score_table import ScoreComparisonTable
from execute_tools.dataset_config import (
    DatasetConfig,
)
from execute_tools.health_checks.candidate_eligibility import (
    is_valid_candidate,
)
from execute_tools.health_checks.schemas import (
    BLOCKING_ACTIONS,
    GateAction,
    GateResult,
)
from execute_tools.metric_order import MetricOrder


class RoundDecision(StrEnum):
    """What the round loop does once its attempts are exhausted.

    F-SCANC-1: ``SKIP_TO_FORMAL`` was retired with the gate actions that
    produced it (operator decision packet v1, 2026-08-26) — see
    ``_decide_round_outcome``.
    """

    CONTINUE = "continue"
    BREAK_ITERATION = "break_iteration"


def _decide_round_outcome(
    *,
    scope_violation_reason: str | None,
    evidence_channel_failure: str | None,
) -> RoundDecision:
    """Arbitrate the end of a round (B-C4a0 E5).

    A pure function over already-computed inputs. The `break` and the
    operator-facing prints stay in the caller — this decides, it does
    not act, so it can be tested without a loop around it.

    F-SCANC-1 (operator decision packet v1, 2026-08-26): the
    ``resolved_action`` / ``is_formal_round`` inputs and the
    SKIP_ITER / SKIP_TO_FORMAL branches are RETIRED, not wired. The C7
    decomposition had severed the carrier (the gate verdict died as a
    local in ``execution.py``; the run loop passed this function only its
    own ``CONTINUE`` initializer), so those branches were unreachable —
    dead inputs advertising round semantics the runtime did not
    implement. Gate actions still reach the record surface
    (``_gate_results_to_score_meta`` → ``ExperimentRecord.gate_action``);
    they no longer claim loop control.
    """
    if scope_violation_reason or evidence_channel_failure:
        return RoundDecision.BREAK_ITERATION
    return RoundDecision.CONTINUE


def _validate_data_config(
    trial_config: TrialConfig,
    segmentation_size: int,
    dataset_config: DatasetConfig,
) -> None:
    """
    Validate integer relationships between dataset, PSD segments, ML segments,
    and sampling portions. Called in the agent loop where all configs converge.

    Args:
        trial_config: The round's validated trial configuration.
        segmentation_size: The planned ML segmentation size to check.
        dataset_config: The run-bound topology to validate AGAINST. Step 05a
            made this required. It used to default to the module-level TIDMAD
            singleton, so a run bound to another topology had its segmentation
            legality decided by TIDMAD's ``psd_segment_length`` — rejecting
            sizes that were legal for the bound task, and accepting sizes that
            were not. A default would silently restore exactly that, so there
            is none: every caller states which topology it means.

            The RULE is unchanged and still belongs to Step 02 — the legal
            values come from ``dataset_config.valid_segmentation_sizes()``.
            05a changes only which object is asked.

    Raises:
        ValueError: If any constraint is violated.
    """
    psd = dataset_config.psd_segment_length
    segs_per_file = dataset_config.segments_per_file

    # 1. PSD segment must divide evenly into ML segments.
    #
    # The rule and its legal-value enumeration both come from the dataset
    # authority. This used to restate the rule inline and re-derive the list
    # with ``range(100, psd + 1)`` — a 10,000,000-iteration loop on the error
    # path under TIDMAD, and a second place the rule could drift from
    # ``valid_segmentation_sizes()``. Same result set (divisors in
    # [100, 100_000]), so the diagnostic is byte-identical.
    if psd % segmentation_size != 0:
        valid = dataset_config.valid_segmentation_sizes()
        raise ValueError(
            f"psd_segment_length ({psd}) must be divisible by "
            f"segmentation_size ({segmentation_size}). "
            f"Remainder: {psd % segmentation_size}. "
            f"Valid segmentation_size values: {valid}."
        )

    # 2. trial_portion must produce at least 1 PSD segment per file
    if trial_config.mode != "single_file":
        eval_segs = max(1, round(trial_config.trial_portion * segs_per_file))
        if eval_segs < 1:
            raise ValueError(
                f"trial_portion ({trial_config.trial_portion}) produces 0 segments "
                f"from {segs_per_file} segments per file."
            )

        # 3. train_portion must produce at least 1 PSD segment from the scope
        train_segs = max(1, round(trial_config.train_portion * eval_segs))
        if train_segs < 1:
            raise ValueError(
                f"train_portion ({trial_config.train_portion}) of "
                f"{eval_segs} scope segments produces 0 training segments."
            )


def _validate_penalty_for_direction(agent_input: Any, order: MetricOrder) -> None:
    """Refuse a finite collapse penalty whose convention the metric contradicts.

    ``degenerate_penalty_score`` is DECLARED by the operator, in the golden
    metric's units and orientation, and its documented convention is "a large
    negative number, strictly below any healthy success" — a statement about a
    MAXIMISED metric. Under a minimised metric the same ``-5.0`` is the best
    score in the run, and although a collapsed record can never become an
    incumbent (its status is ``failed_mode_collapse`` and every selection
    filters on ``status == "success"``), the PLANNER still sees the penalised
    value in its history and would read the campaign's worst round as its best.

    Step 07 PR 07b (§3.3 row 5) classifies this rule (iv) — inapplicable, fail
    closed. It is not negated and not reinterpreted: the framework has no
    reference at startup against which "worse" could be checked, so guessing a
    sign would be inventing policy. ``None`` (the default) is always fine; it
    nulls the score instead, which is direction-free.

    Raised at tuner startup, beside ``validate_runtime_config``, BEFORE any LLM
    call or file I/O — the same refusal path every other illegal operator
    configuration takes.

    Raises:
        ValueError: a finite float penalty under a metric the convention does
            not describe.
    """
    penalty = agent_input.degenerate_penalty_score
    if penalty is None or order.penalty_convention_applies:
        return
    raise ValueError(
        f"degenerate_penalty_score={penalty!r} cannot be interpreted under a "
        f"'{order.direction}'-is-better golden metric: the value's documented "
        f"convention ('strictly below any healthy success') describes a "
        f"maximised metric, so this number would read to the planner as the "
        f"best score in the run. Use degenerate_penalty_score=None (the "
        f"default), which nulls a collapsed round's score instead. Operator "
        f"configuration is a contract: it is refused, never normalized."
    )


def _best_trial_winner(
    memory_history: list,
    *,
    order: MetricOrder,
    required_gate_ids: frozenset[str] | None = None,
) -> dict | None:
    """Best-scoring HealthGate-valid trial from ``memory_history``.

    "Best" is the bound golden metric's own notion (Step 07 PR 07b): the
    argmax under a ``higher`` metric, the argmin under a ``lower`` one, ties
    resolving to the first record exactly as ``max()`` did before.

    Role identity comes from the typed ``is_trial`` field ALONE — the same
    field ``core/resume.py`` already consults across runs — and it is written
    unconditionally from ``plan.is_trial`` (via ``trial_config.is_trial``).
    Legacy records without the key, and collapsed, non-finite or incompletely
    observed ones, are not execution candidates.

    **``memory.time_mode`` is deliberately NOT consulted** (Step 07
    correction, 2026-08-16). It is written by the record builder only when
    the wall-time gate ran (``time_check is not None``, i.e. the active
    mode's budget was set), so it is time-gate metadata, never a second role
    authority. Requiring the two to agree made candidate ROLE depend on
    whether time-budget enforcement happened to be enabled: with incumbent
    formal gates on and both time budgets unset, a successful, finite,
    HealthGate-valid trial produced ``winner=None``, ``_should_skip_formal``
    read that as *no evidence*, and the forced formal round was skipped.
    Surfaced by 07b's Gate 1; the coupling predates 07b, which was not
    permitted to change round semantics. Its population is unchanged.

    Used by both the forced-formal-round hyperparameter inheritance in
    :func:`_apply_mode_override_chain` (trial winner's config drives the
    formal round's plan) and the SkipFormal / bypass-formal-budget gates
    that consult the best trial score before deciding whether to run the
    formal round. The pre-5a ``reference_file_vector`` plumbing into
    ``sandbox.score_vector`` is gone — health checks now run tuner-side
    per ``docs/design/pluggable_health_checks.md`` §14 Option A.
    """
    candidates = [
        r
        for r in memory_history
        if is_valid_candidate(r, required_gate_ids=required_gate_ids) and r.get("is_trial") is True
    ]
    if not candidates:
        return None
    return order.best(candidates, key=_score_of)


def _should_skip_formal(
    winner: dict | None,
    *,
    threshold: float | None,
    gates_enabled: bool,
    order: MetricOrder,
) -> bool:
    """Whether to skip the formal round.

    Takes the ALREADY-RESOLVED winner so that the skip gate, the bypass
    gate and the formal plan inheritance all judge the same record. Three
    independent `_best_trial_winner` calls would agree today only because
    the history does not change between them — a coincidence, not a
    guarantee.

    Two reasons to skip, and the first is V20 PR D's correction:

    - **no valid trial winner** — no trial ran, all failed, or none passed
      its HealthGate. There is no evidence that justifies the cost of a
      formal round. Previously this returned ``False`` (via
      ``winner is not None and …``), so *absence of evidence* was
      indistinguishable from *sufficient evidence* and the round ran
      anyway. A high-scoring INVALID trial cannot change this: it never
      becomes the winner.
    - the winner is WORSE than the skip threshold (07b: worse in the bound
      metric's declared direction, not "numerically smaller").

    ``gates_enabled`` is the feature switch. With the gates off this
    behaves exactly as before — including running formal with no valid
    winner — because the deltas are not consumed at all.

    The disabled sentinel is the ORDER's worst value (``-inf`` under a
    ``higher`` metric): a threshold nothing can be worse than can never skip.
    """

    if not gates_enabled:
        return False
    if winner is None:
        return True
    if threshold is None or threshold == order.worst_sentinel:
        return False
    return order.is_better(threshold, winner["denoising_score"])


def _should_bypass_formal_time_budget(
    winner: dict | None,
    *,
    threshold: float | None,
    order: MetricOrder,
) -> bool:
    """Whether the winner clears the bypass threshold.

    Takes the same resolved winner the skip gate judged. On a chain with
    no formal incumbent the threshold resolves to the order's WORST value
    (``-inf`` under a ``higher`` metric — the ``negative_infinity_bootstrap``),
    so the first valid trial always clears it and establishes the chain's
    first formal baseline.

    The disabled sentinel is the order's BEST value: a threshold nothing can
    reach can never bypass.
    """

    if winner is None:
        return False
    if threshold is None or threshold == order.best_sentinel:
        return False
    return order.is_at_least(winner["denoising_score"], threshold)


def resolve_measured_time_budget(
    *,
    base_budget_minutes: float | None,
    admission_source: str,
    is_formal_round: bool,
    formal_trial_winner: dict | None,
    bypass_threshold: float | None,
    bypass_ceiling_minutes: float | None,
    order: MetricOrder,
) -> float | None:
    """Resolve the single in-process ceiling for measured admission.

    Forecast admission can re-evaluate an estimate after the normal ceiling
    is exceeded. Measured admission has no advance estimate, so an approved
    score-qualified Formal attempt receives its elevated ceiling before the
    subprocess starts. Configuring a bypass never raises an unqualified run.
    """
    if (
        admission_source != "measured"
        or not is_formal_round
        or bypass_ceiling_minutes is None
        or not _should_bypass_formal_time_budget(
            formal_trial_winner,
            threshold=bypass_threshold,
            order=order,
        )
    ):
        return base_budget_minutes
    if base_budget_minutes is None:
        return bypass_ceiling_minutes
    return max(base_budget_minutes, bypass_ceiling_minutes)


def _resolve_formal_comparison_thresholds(
    *,
    reference_score: float | None,
    skip_min_delta: float,
    bypass_min_delta: float,
    gates_enabled: bool,
    order: MetricOrder,
) -> tuple[float | None, float | None, float | None, str]:
    """Resolve invocation-wide formal comparison values once.

    The returned tuple is
    ``(reference, skip_threshold, bypass_threshold, source)``.
    V19 PR 1: this is the SINGLE authoritative computation — the gates,
    the startup banner, and the durable output metadata all consume these
    values, so the persisted thresholds provably equal what the gates
    used. ``reference_score=None`` (no chain incumbent) resolves to
    ``(None, None, None)`` and both gates short-circuit.
    """

    if reference_score is None:
        if not gates_enabled:
            # Feature off: the deltas are not consumed, so nothing is
            # resolved and both gates stay inert — pre-V20 behaviour,
            # unchanged.
            return (None, None, None, "gates_disabled")
        # V20 PR D §16.C — the negative-infinity bootstrap. A chain with
        # no restored HealthGate-valid formal incumbent has no reference,
        # and the pre-D behaviour was for both gates to fall silent: a
        # valid trial of 0.001 proceeded to formal, while an excellent
        # trial was still budget-blocked because bypass could not fire.
        # That is the v15 failure the bypass gate was written to fix,
        # reappearing because the reference is absent.
        #
        # -inf arms them instead: the first valid trial is never skipped,
        # always clears the bypass threshold, and establishes the chain's
        # first formal baseline. From the next iteration the restored
        # incumbent takes over and the gates tighten as the chain improves.
        #
        # There is no seeded artifact to use instead: every documented
        # paper baseline is trained-but-collapsed, and the historical seed
        # (5.5763) is the class-127 phantom.
        # Step 07 PR 07b: "the worst possible reference" is an ORDER fact, not
        # a number — `-inf` under a maximised metric, `+inf` under a minimised
        # one. The source string stays `negative_infinity_bootstrap` because it
        # is a PROVENANCE LABEL persisted on records; renaming it would be a
        # record-vocabulary change (D1-adjacent, not authorised here). Read it
        # as "the worst-value bootstrap".
        bootstrap = order.worst_sentinel
        return (bootstrap, bootstrap, bootstrap, "negative_infinity_bootstrap")
    # The two margins are DECLARED by the operator in the golden metric's own
    # units (§3.3 row 1) and are coordinates on the better-direction axis:
    # positive tightens the threshold, negative loosens it, under BOTH
    # directions. That is what preserves the documented disable convention —
    # skip `delta=-inf` and bypass `delta=+inf` still resolve to this metric's
    # worst and best sentinels rather than swapping meaning under `lower`.
    return (
        reference_score,
        order.toward_better(reference_score, skip_min_delta),
        order.toward_better(reference_score, bypass_min_delta),
        "restored_valid_formal_incumbent",
    )


def _json_safe_reference(value: float | None) -> float | None:
    """A reference or threshold that JSON can actually carry.

    ``-inf`` is a RESOLVER value, never a stored one (§16.C). Non-standard
    JSON ``Infinity`` is rejected by strict parsers, and `29ec0542` removed
    a fixed ``0.0`` default precisely because a stored sentinel became a
    silent policy — so an infinite bound persists as ``null`` and
    ``formal_comparison_reference_source`` carries the meaning instead.

    This also covers the pre-existing case of an operator explicitly
    disabling a gate with ``float("-inf")`` / ``float("inf")``, which could
    already put ``Infinity`` in an artifact.

    The test is ``math.isfinite``, deliberately, and NOT
    ``value in (-inf, +inf)``: that form compares by equality, and **NaN is
    not equal to itself**, so a NaN threshold would slip through and
    ``json.dump`` (whose ``allow_nan`` defaults to ``True``) would write a
    bare ``NaN`` into the artifact. One finite check covers all three
    non-standard values.
    """
    if value is None or not math.isfinite(value):
        return None
    return value


def _fmt_reference(value: float | None) -> str:
    """Render a resolved reference/threshold for banners and logs.

    ``None`` renders as ``"none"`` — never as ``0.0`` (the pre-V19
    defect value).
    """

    return "none" if value is None else f"{value:.4f}"


def _identity(value: float) -> float:
    """Key function for ordering a list of bare scores."""
    return value


def _score_of(record: dict) -> float:
    """Key function for ordering records by the golden metric."""
    return record["denoising_score"]


def _build_reflection_context(
    *,
    memory_history: list,
    current_score: float | None,
    current_loss_type: str | None,
    current_final_loss: float | None,
    current_params: int | None,
    current_epochs: int | None,
    train_psd_segments: int | None,
    eval_psd_segments: int | None,
    trial_config: TrialConfig,
    score_table: ScoreComparisonTable | None,
    order: MetricOrder,
) -> dict:
    """The reflector's comparison context for one completed round.

    Extracted from ``run()`` by Step 07 PR 07b so that the golden-metric
    ordering inside it (best score, best record, rank, new-best, worst score
    and the efficiency band) becomes independently testable and can be routed
    through the run's ONE order authority. Behaviour is byte-identical to the
    inline block it replaces; the C1 replay goldens are the evidence.

    Two DIFFERENT orderings live here and must not be conflated:

    * the golden metric's — ``best_score_so_far`` / ``rank`` / ``is_new_best``
      / ``is_more_efficient``, which follow the bound metric's declared
      direction;
    * the training loss's — ``same_loss_loss_rank`` /
      ``best_same_loss_final_loss``, which are lower-is-better *by definition
      of a loss* and must stay put when the metric direction flips.

    Args:
        memory_history: the run's records so far (``sandbox.get_summary()``).
        current_score: this round's golden-metric score, or ``None``.
        current_loss_type: this round's ``loss_config.loss_type``.
        current_final_loss: this round's final TRAINING loss, or ``None``.
        current_params: this round's model parameter count.
        current_epochs: this round's planned epochs.
        train_psd_segments: training sample-set size in PSD segments.
        eval_psd_segments: evaluation sample-set size in PSD segments.
        trial_config: the round's resolved trial configuration.
        score_table: this round's rendered per-file comparison table, if any.
        order: the run's ONE order authority — the only interpreter of the
            golden metric's declared direction.

    Returns:
        The reflector context dict — exactly the 23 keys WF-2 pins.
    """
    successful: list[dict] = [
        r
        for r in memory_history
        if r.get("status") == "success" and r.get("denoising_score") is not None
    ]
    baseline_record = next((r for r in memory_history if "baseline" in r.get("exp_id", "")), None)
    all_scores = [r["denoising_score"] for r in successful]
    best_score = order.best(all_scores, key=_identity) if all_scores else None
    best_record = order.best(successful, key=_score_of) if successful else None
    # ``current_score in all_scores`` keeps the pre-07b guard: a round whose
    # own score is not among the successful ones (a failure, or None) has no
    # rank at all rather than an invented one. The explicit ``is not None``
    # is redundant at runtime (``all_scores`` never contains ``None`` — the
    # ``successful`` filter excludes it) but it is what lets the checker
    # narrow ``float | None`` to ``float`` at the call.
    rank = (
        order.rank(all_scores, current_score)
        if current_score is not None and current_score in all_scores
        else None
    )

    # LOSS territory below — lower-is-better by definition of a loss, and
    # therefore NOT routed through the metric's order authority. A flip here
    # when the golden metric's direction flips would be a defect; the C2 rung
    # asserts these two values do not move.
    same_loss_finals = [
        r["final_loss"]
        for r in successful
        if r.get("params", {}).get("loss_config", {}).get("loss_type") == current_loss_type
        and r.get("final_loss") is not None
    ]
    if current_final_loss is not None:
        all_same_loss_finals = [*same_loss_finals, current_final_loss]
        sorted_finals = sorted(all_same_loss_finals)
        same_loss_loss_rank = sorted_finals.index(current_final_loss) + 1
        same_loss_total = len(all_same_loss_finals)
    else:
        same_loss_loss_rank = None
        same_loss_total = len(same_loss_finals)

    baseline_params = baseline_record.get("model_params") if baseline_record else None
    baseline_epochs = (
        baseline_record.get("params", {}).get("train_config", {}).get("epochs")
        if baseline_record
        else None
    )
    params_ratio = (
        round(current_params / baseline_params, 3) if (current_params and baseline_params) else None
    )
    epochs_ratio = (
        round(current_epochs / baseline_epochs, 3) if (current_epochs and baseline_epochs) else None
    )

    worst_score = order.worst(all_scores, key=_identity) if all_scores else None
    # The band is a fraction of the run's OBSERVED score range, so it is
    # scale-free by construction and no metric constant enters (§3.3 row 4,
    # classification (i)). `abs` because "range" is a width: under a minimised
    # metric the best score is the smaller number. The threshold then moves a
    # MAGNITUDE toward worse — never a raw `best - 0.05`, which would be a
    # hidden higher-is-better assumption and would drift the band the wrong way
    # on a minimised metric.
    score_range = (
        abs(best_score - worst_score)
        if (best_score is not None and worst_score is not None and best_score != worst_score)
        else None
    )
    # Narrowed on ``best_score`` rather than on ``score_range``: a non-None
    # range already implies a non-None best, but only the direct test lets the
    # checker see it, and the two conditions must not drift apart.
    score_threshold = (
        order.toward_worse(best_score, EFFICIENCY_BAND_FRACTION * score_range)
        if (best_score is not None and score_range is not None)
        else best_score
    )
    best_params = best_record.get("model_params") if best_record else None
    best_epochs = (
        best_record.get("params", {}).get("train_config", {}).get("epochs") if best_record else None
    )
    is_more_efficient = (
        score_threshold is not None
        and current_score is not None
        and order.is_at_least(current_score, score_threshold)
        and (
            (
                current_params is not None
                and best_params is not None
                and current_params < best_params
            )
            or (
                current_epochs is not None
                and best_epochs is not None
                and current_epochs < best_epochs
            )
        )
    )

    return {
        "baseline_score": baseline_record.get("denoising_score") if baseline_record else None,
        "best_score_so_far": best_score,
        "is_new_best": current_score is not None
        and (best_score is None or order.is_better(current_score, best_score)),
        "rank": rank,
        "total_experiments": len(successful),
        "best_config_so_far": best_record.get("params") if best_record else None,
        "best_same_loss_final_loss": min(same_loss_finals) if same_loss_finals else None,
        "current_loss_type": current_loss_type,
        "same_loss_loss_rank": same_loss_loss_rank,
        "same_loss_total": same_loss_total,
        "baseline_params": baseline_params,
        "baseline_epochs": baseline_epochs,
        "current_params": current_params,
        "current_epochs": current_epochs,
        "params_ratio": params_ratio,
        "epochs_ratio": epochs_ratio,
        "is_more_efficient": is_more_efficient,
        "training_psd_segments": train_psd_segments,
        "eval_psd_segments": eval_psd_segments,
        "baseline_psd_segments": baseline_record.get("training_psd_segments")
        if baseline_record
        else None,
        "trial_portion": trial_config.trial_portion if trial_config.mode != "single_file" else None,
        "eval_portion": trial_config.eval_portion if trial_config.mode != "single_file" else None,
        # Pre-rendered per-file comparison table (model vs raw_baseline vs
        # ground_truth) — consumed verbatim by the reflector prompt. None on
        # failed/skipped rounds so the prompt can branch.
        "score_comparison_table": score_table.rendered_markdown if score_table else None,
    }


@dataclass(frozen=True)
class BestTracks:
    """The five ``best_*`` finalization tracks of one tuner invocation.

    Extracted from ``run()`` by Step 07 PR 07b. Each track applies the SAME
    ordering (the run's order authority) to a DIFFERENT filter, and the
    filters are what carry the meaning:

    * ``top`` — any successful, finite-scored record;
    * ``formal`` — of those, the full-scope (non-trial) ones. Formal records
      have no ``is_trial`` key (it is set only when ``trial_config.is_trial``);
      absence == formal;
    * ``valid`` — of those, the HealthGate-valid ones;
    * ``valid_formal`` — valid AND formal (the chain incumbent's source);
    * ``valid_trial`` — valid AND trial. V19 PR 1 (P1-C4) bookkeeping,
      deliberately NOT the same predicate as ``_best_trial_winner``, which
      additionally requires ``memory.time_mode == "trial"``.

    Validity is a filter, never part of the comparison: an invalidated result
    must not become a better incumbent under EITHER metric direction, and the
    way that is guaranteed is that it never enters the ordering at all
    (design §3.4).
    """

    top: dict | None
    formal: dict | None
    valid: dict | None
    valid_formal: dict | None
    valid_trial: dict | None


def _select_best_records(
    all_records: list,
    *,
    order: MetricOrder,
    required_gate_ids: frozenset[str] | None = None,
) -> BestTracks:
    """Resolve the five ``best_*`` tracks from a run's complete record list.

    Args:
        all_records: every record the invocation produced.
        order: the run's ONE order authority.
        required_gate_ids: the RUN's own scientific gate set — F-12d-30.
            Omitted (``None``) means "resolve the default", which
            ``is_valid_candidate`` does by calling
            :func:`required_blocking_gate_ids`; that composes with
            ``LEGACY_OMITTED`` and is therefore **TIDMAD's** set. Correct for
            an un-composed run and wrong for a composed one, where it makes
            the process bind TIDMAD's Health family after the run has already
            bound its own — which the Step-08b run-scope guard then refuses,
            killing an otherwise-complete run at finalize. The caller resolves
            this through :func:`resolve_run_scientific_gate_ids`, the
            authority Step 10 / P5+P6 W6 built for exactly this
            (finding F-P56-2); this call site was simply never migrated to it.

    Returns:
        A :class:`BestTracks` whose fields are the winning records (or
        ``None`` when a track's filter admits nothing).
    """
    successful_records = [
        r
        for r in all_records
        if r.get("status") == "success"
        and isinstance(r.get("denoising_score"), int | float)
        and math.isfinite(r["denoising_score"])
    ]
    top_record = order.best(successful_records, key=_score_of) if successful_records else None
    formal_records = [r for r in successful_records if not r.get("is_trial", False)]
    formal_top_record = order.best(formal_records, key=_score_of) if formal_records else None
    valid_records = [
        r for r in successful_records if is_valid_candidate(r, required_gate_ids=required_gate_ids)
    ]
    valid_top_record = order.best(valid_records, key=_score_of) if valid_records else None
    valid_formal_records = [r for r in valid_records if not r.get("is_trial", False)]
    valid_formal_top_record = (
        order.best(valid_formal_records, key=_score_of) if valid_formal_records else None
    )
    valid_trial_records = [r for r in valid_records if r.get("is_trial", False)]
    valid_trial_top_record = (
        order.best(valid_trial_records, key=_score_of) if valid_trial_records else None
    )
    return BestTracks(
        top=top_record,
        formal=formal_top_record,
        valid=valid_top_record,
        valid_formal=valid_formal_top_record,
        valid_trial=valid_trial_top_record,
    )


def _latest_trial_inference_marginal(memory_history: list) -> float | None:
    """Return the most recent successful trial round's measured per-PSD-segment
    inference cost in ms, or ``None`` if no qualifying record exists.

    refine_inference_time_estimator.md Commit D — feeds the formal round's
    time gate as ``inference_per_psd_seg_ms_hint`` so the gate uses the
    measured marginal instead of the legacy ``× 2.7`` ratio.

    Looks within the *current iteration's* memory history only — under the
    Commit A (Step 0) ``model_cfg`` inheritance rule, formal rounds within
    an iteration always run the trial-winner architecture, so a measurement
    from an earlier iter is for a different arch and must not be reused.
    The chain runner already partitions ``memory_history`` per iteration,
    so the caller passes whatever in-iter record list it already has.

    Eligibility predicate: ``status == "success"`` AND
    ``memory.time_mode == "trial"`` AND
    ``memory.inference_per_psd_seg_ms_measured`` is a positive float. We
    walk in reverse so an OOM-killed retry between two successful trials
    doesn't displace the most recent useful measurement.
    """
    for r in reversed(memory_history):
        if r.get("status") != "success":
            continue
        mem = r.get("memory") or {}
        if mem.get("time_mode") != "trial":
            continue
        v = mem.get("inference_per_psd_seg_ms_measured")
        if v is not None and v > 0:
            return float(v)
    return None


# --------------------------------------------------------------------- #
# Formal-round strategy aliasing + registry
# (refactor_formal_round_strategy.md — Phase 1 added the alias map; Phase 2
# wires the three handlers + dispatch table consumed below in
# :func:`_apply_mode_override_chain`.)
# --------------------------------------------------------------------- #
# The schema's ``@field_validator`` is the primary canonicalisation point
# and live callers always reach this function with the already-canonical
# name; this helper is a defensive second pass so unit tests, ad-hoc
# constructions, and any future internal caller that bypasses the schema
# still see consistent behavior.
_LEGACY_STRATEGY_ALIASES: dict[str, str] = {
    "inherit_best_trial": "full_clone",
    "llm_propose": "independent",
}


def _canonical_strategy(name: str) -> str:
    """Return the canonical name for ``name``, resolving any legacy alias.

    Unknown names pass through unchanged — schema-layer validation is
    responsible for rejecting them.
    """
    return _LEGACY_STRATEGY_ALIASES.get(name, name)


def _strategy_full_clone(plan: ExperimentPlan, winner: dict) -> list[str]:
    """Inherit all five fields: model_cfg, loss_cfg, lr, epochs, batch_size.

    Production default. Required for the trial→formal inference-time
    measurement reuse landed in commits B-D of
    ``docs/refine_inference_time_estimator.md`` — the timing measurement
    must be for the same architecture the formal round runs.
    """
    p = winner["params"]
    plan.model_cfg = dict(p.get("model_config") or {})
    plan.loss_cfg = dict(p["loss_config"])
    plan.train_cfg["lr"] = p["train_config"]["lr"]
    inherited = ["model_cfg", "loss_cfg", "lr"]
    inherited_epochs = p["train_config"].get("epochs")
    if inherited_epochs is not None:
        plan.train_cfg["epochs"] = inherited_epochs
        inherited.append("epochs")
    inherited_bs = p["train_config"].get("batch_size")
    if inherited_bs is not None:
        plan.train_cfg["batch_size"] = inherited_bs
        inherited.append("batch_size")
    return inherited


def _strategy_hybrid_params(plan: ExperimentPlan, winner: dict) -> list[str]:
    """Inherit only loss_cfg + lr; planner keeps model_cfg, epochs, batch_size.

    Audit/exploration use case — lock the evaluation surface (loss + lr)
    but let the LLM scale capacity for the full-data pass. The time gate
    may reject the planner's heavier choice on the formal round; that is
    the intended trade-off, not a bug.
    """
    p = winner["params"]
    plan.loss_cfg = dict(p["loss_config"])
    plan.train_cfg["lr"] = p["train_config"]["lr"]
    return ["loss_cfg", "lr"]


def _strategy_independent(plan: ExperimentPlan, winner: dict) -> list[str]:
    """No-op. Planner's full plan survives verbatim.

    ``winner`` is unused but kept in the signature so the registry can
    dispatch without special-casing.
    """
    return []


_FORMAL_STRATEGY_REGISTRY: dict[str, Callable[[ExperimentPlan, dict], list[str]]] = {
    "full_clone": _strategy_full_clone,
    "hybrid_params": _strategy_hybrid_params,
    "independent": _strategy_independent,
}


def _apply_mode_override_chain(
    plan: ExperimentPlan,
    *,
    trial_allowed: bool,
    is_formal_round: bool,
    force_formal_round: bool,
    formal_round_strategy: str = "full_clone",
    memory_history: list | None = None,
    trial_winner: dict | None,
) -> ExperimentPlan:
    """Apply the run-level + last-round overrides to ``plan``.

    Three independent mutations can fire:

    1. ``trial_allowed=False`` — the run was launched without trial mode
       enabled, so every round forces ``plan.is_trial = False``.
    2. ``is_formal_round and force_formal_round`` — the last round of
       every iteration normally forces ``plan.is_trial = False`` so the
       run produces a cross-architecture comparable score. Operators can
       disable this override by passing ``--no-force_formal_round``.
    3. **Hyperparameter inheritance**, dispatched through
       :data:`_FORMAL_STRATEGY_REGISTRY` keyed by the canonical
       ``formal_round_strategy`` (legacy aliases ``inherit_best_trial`` /
       ``llm_propose`` resolve via :func:`_canonical_strategy`):

       * ``"full_clone"`` (default) — copies all 5 fields from the
         highest-scoring trial-mode success record. Production default;
         required for trial→formal inference-time measurement reuse.
       * ``"hybrid_params"`` — copies only ``loss_cfg`` + ``lr``;
         planner keeps ``model_cfg`` / ``epochs`` / ``batch_size``.
         Audit / exploration use case.
       * ``"independent"`` — no inheritance; planner's plan survives
         verbatim. ``plan.is_trial`` is still flipped to False.

       Shared no-winner fallback for ``full_clone`` and ``hybrid_params``:
       when ``memory_history`` carries no HealthGate-valid trial round, the
       planner's plan is preserved unchanged and a WARNING is logged
       (resilient — a messy trial stage shouldn't kill the chain).
       ``independent`` skips the warning because the strategy explicitly
       disclaims inheritance — there was nothing the user wanted to
       inherit.

       Why the default exists: V7 iter_001/iter_002 of explore_novel
       showed the LLM picking an untested ``focal_cw`` loss for the
       formal round despite all trial rounds using ``focal``; the
       resulting model collapsed to ~0 PSD output. V9 audit §7 found
       the same pattern at the architecture level — formal rounds
       emitting ``kernel_size=2``/``use_same_padding=False`` when both
       trial rounds used ``kernel_size=3``/``use_same_padding=True``.

    Audit log contract (refactor_formal_round_strategy.md §3):

    * ``[STRATEGY] formal_round_strategy=<canonical>`` — emitted once
      per forced formal round. Includes ``(alias_of:<legacy>)`` when
      the caller passed a legacy literal.
    * ``[FORMAL OVERRIDE] strategy=<canonical> winner=<exp_id>
      score=<float> inherited=<comma-list>`` on the inherit path, OR
      a WARNING line on the no-winner path (full_clone / hybrid_params).

    **``trial_winner`` is supplied, never re-derived** (V20 PR D, FU-D-6).
    The tuner resolves the iteration's HealthGate-valid trial winner ONCE
    at the formal-round boundary, and the skip gate, the bypass gate, the
    log line and this inheritance path all judge that same record. This
    function used to call ``_best_trial_winner(memory_history)`` itself.
    That agreed with the gates by construction — a formal round forces
    ``plan.is_trial = False``, so nothing it appends can satisfy the
    winner filter — but agreement by construction is not the same as one
    snapshot, and the frozen design (§16.F) requires the snapshot. Keeping
    the second call would leave a seam where a later state update between
    the gates and inheritance silently diverges the two.

    ``memory_history`` is still required, and is NOT redundant: the
    full-clone OOM-recovery branch inspects the LATEST record and the
    maximum ``round_index`` across the whole history, which a winner alone
    cannot answer.

    Mutates ``plan`` in place and returns it for caller-chaining.
    """
    if not trial_allowed:
        plan.is_trial = False
    if not (is_formal_round and force_formal_round):
        return plan

    plan.is_trial = False
    canonical = _canonical_strategy(formal_round_strategy)
    handler = _FORMAL_STRATEGY_REGISTRY.get(canonical)
    if handler is None:
        # Defensive — schema validation should reject unknown literals
        # before they reach this function. If a caller bypassed the
        # schema (e.g. an ad-hoc test fixture), surface the bypass loudly
        # and treat the request as ``independent`` to avoid silent
        # mis-inheritance.
        print(
            f"  [STRATEGY] WARNING: unknown strategy {formal_round_strategy!r} — "
            "treating as 'independent' (no inheritance)."
        )
        return plan

    print(
        f"  [STRATEGY] formal_round_strategy={canonical}"
        + (f" (alias_of:{formal_round_strategy})" if canonical != formal_round_strategy else "")
    )

    winner = trial_winner
    if winner is None:
        if canonical == "independent":
            # ``independent`` explicitly disclaims inheritance — a missing
            # winner is not a warning condition. Still emit one structured
            # log line so the audit trail is uniform.
            print(f"  [FORMAL OVERRIDE] strategy={canonical} winner=none inherited=(none)")
        else:
            print(
                "  [FORMAL OVERRIDE] WARNING: no successful trial round is HealthGate-valid "
                "in this iteration — planner's plan unchanged. "
                "Score may be unreliable."
            )
        return plan

    latest_record = (memory_history or [])[-1] if memory_history else None
    recovering_from_formal_oom = (
        canonical == "full_clone"
        and isinstance(latest_record, dict)
        and latest_record.get("status") == "error_training_oom"
        and (latest_record.get("memory") or {}).get("round_index")
        == (
            max(
                (
                    (record.get("memory") or {}).get("round_index", 0)
                    for record in (memory_history or [])
                ),
                default=0,
            )
        )
    )
    if recovering_from_formal_oom:
        # A full clone is the right first formal attempt, but repeatedly
        # restoring the winning architecture and batch size makes the
        # planner's OOM recovery proposal impossible to execute. Preserve
        # the validated loss surface and learning rate while allowing the
        # planner to reduce model capacity and/or batch size on retries.
        inherited = _strategy_hybrid_params(plan, winner)
        print(
            "  [FORMAL RECOVERY] prior formal attempt OOMed — "
            "preserving planner model_cfg/batch_size/epochs"
        )
    else:
        inherited = handler(plan, winner)
    print(
        f"  [FORMAL OVERRIDE] strategy={canonical} "
        f"winner={winner['exp_id']!r} score={winner['denoising_score']:.4f} "
        f"inherited={','.join(inherited) if inherited else '(none)'}"
    )
    return plan


def _apply_degeneracy_reaction(
    score_results: dict,
    plan: ExperimentPlan,
    penalty_score: float | None,
) -> tuple[bool, str | None]:
    """Generic policy reaction to tuner-side HealthGate evaluation.

    Post-commit-5b, the health-check verdict is produced by tuner-side
    gate evaluation (``get_gates_for_position`` → ``evaluate_gate`` →
    ``resolve_action``) and mapped to the legacy ``is_degenerate`` /
    ``failure_reason`` contract via ``_gate_results_to_score_meta``. By
    the time this helper runs, ``score_results`` already carries the
    mapping's output — ``is_degenerate=True`` on any non-``CONTINUE``
    gate action, ``failure_reason`` pipe-concatenated across failed
    gates prefixed by gate_id. See
    ``docs/design/pluggable_health_checks.md`` §4 and §8.

    The agent's role here is purely **policy** — translate the task-side
    health signal into the right tuner-level reaction:

    * Trial rounds are immune per policy (AMB-5b-A → A). The reaction
      never nulls the score when ``plan.is_trial`` is True, but the
      ``failure_reason`` and ``gate_action`` fields still propagate to
      the record so the next planner sees the diagnostic.
    * On a degenerate (or gate-flagged) **formal** round:

      - ``penalty_score is None`` → null ``denoising_score`` so the round
        cannot be picked as 'best' by the planner's max-score logic.
      - ``penalty_score`` is a float → use it as ``denoising_score`` so
        the planner's rank-ordering still includes the failure but
        strictly below any healthy success.

      In both cases the caller wraps the record with
      ``status='failed_mode_collapse'`` and preserves ``failure_reason``
      verbatim for the next iteration's planner.

    Args:
        score_results: Mutable dict — the ``score_res["results"]`` block
            written by the scoring branch. Must contain ``is_degenerate``
            and ``failure_reason`` keys (defensive defaults applied if
            absent). ``denoising_score`` is mutated in place when the
            reaction fires.
        plan: The current round's validated ``ExperimentPlan``. Only
            ``plan.is_trial`` is read.
        penalty_score: The operator-supplied
            ``HyperparamTuningInput.degenerate_penalty_score``.

    Returns:
        ``(is_degenerate, failure_reason)`` — the unmutated original
        signal so the caller can populate ``ExperimentRecord.status`` and
        ``ExperimentRecord.failure_reason`` independently of any score
        mutation.
    """
    is_degenerate = score_results.get("is_degenerate", False)
    failure_reason = score_results.get("failure_reason")
    if is_degenerate and not plan.is_trial:
        print(f"  [HEALTH CHECK] {failure_reason}")
        score_results["denoising_score"] = penalty_score
    return is_degenerate, failure_reason


def _gate_results_to_score_meta(
    gate_results: list[GateResult],
    resolved_action: GateAction,
) -> tuple[bool, str | None, str]:
    """Map gate evaluation output to the legacy score-meta contract.

    Contract: ``(is_degenerate, failure_reason, gate_action_str)`` — the
    first two feed the existing ``_apply_degeneracy_reaction`` policy;
    the third goes into ``ExperimentRecord.gate_action`` for observability.

    Semantic (M8 §3.2 revision, 2026-07-16):

      * ``is_degenerate`` reflects only **blocking** gate failures — a
        failed gate whose ``action`` is in ``BLOCKING_ACTIONS``
        (``INVALIDATE_ROUND``; the skip actions were retired, F-SCANC-1). A
        recording-only gate that returns ``passed=False`` with
        ``action=CONTINUE`` never sets ``is_degenerate=True``, so it
        cannot silently zero-out a formal round's score via
        ``_apply_degeneracy_reaction``.
      * ``failure_reason`` still concatenates ALL failed gates (blocking
        and recording) for observability — recording-only diagnostics
        remain visible in the round record without changing routing.
      * ``resolved_action`` controls only routing and is always returned
        unchanged for record observability.

    Pre-M8 behaviour flagged ``is_degenerate=True`` for any failed gate
    (including recording-only). See docs/design/m8_gate_coverage_and_diversity_metrics_execution_plan.md
    §3.2 and Caveat A discussion for the bug this fix addresses.
    """
    failed_gates = [gr for gr in gate_results if not gr.passed]
    if not failed_gates:
        return False, None, resolved_action.value

    # is_degenerate reflects blocking failures only (M8 §3.2 fix).
    failed_blocking = [gr for gr in failed_gates if gr.action in BLOCKING_ACTIONS]

    # failure_reason concatenates ALL failed gates for observability —
    # blocking AND recording. The tuner records this string in the
    # round's failure_reason field regardless of is_degenerate outcome.
    failure_reason: str | None = " | ".join(
        f"[{gr.gate_id}] {gr.failure_reason}" for gr in failed_gates if gr.failure_reason
    )
    if failed_blocking and not failure_reason:
        failure_reason = f"gate action {resolved_action.value} with no reason"
    elif not failure_reason:
        # No blocking failure AND every failed recording gate had an empty
        # reason. There is nothing degenerate to flag and no reason to
        # surface — clean pass-through with the CONTINUE routing.
        failure_reason = None

    is_degenerate = bool(failed_blocking)
    return is_degenerate, failure_reason, resolved_action.value


def _merge_score_validity_failure(
    denoising_score: float | None,
    *,
    is_degenerate: bool,
    failure_reason: str | None,
) -> tuple[bool, str | None]:
    """Treat a missing/non-finite scorer result as a completed collapse.

    HealthGates fire only at configured round positions. Numerical validity,
    however, is an invariant of every completed scoring attempt; otherwise a
    round without a configured gate can be persisted as ``success`` with a
    JSON-null score. This helper changes classification/feedback only and does
    not alter the frozen scoring formula or denominator policy.
    """
    if denoising_score is not None and math.isfinite(denoising_score):
        return is_degenerate, failure_reason
    validity_reason = (
        "[scoring_validity] denoising_score is None or non-finite; "
        "the model produced no valid denoising signal"
    )
    if failure_reason:
        validity_reason = f"{failure_reason} | {validity_reason}"
    return True, validity_reason


def _non_retryable_termination_message(
    *, scope_violation_reason: str | None, evidence_channel_failure: str | None
) -> str:
    """Operator-facing line for a non-retryable termination. The evidence
    channel outranks the scope violation (C9c): if the channel is broken,
    every other classification this run made is suspect."""
    if evidence_channel_failure:
        return (
            "  [RUNTIME] Evidence-channel failure (infrastructure) — terminating "
            f"the chain: {evidence_channel_failure}"
        )
    return (
        f"  [DATASCOPE] Non-retryable scope violation — terminating run: {scope_violation_reason}"
    )


def _compute_termination_state(
    *,
    completed_rounds: int,
    max_rounds: int,
    consecutive_fails: int,
    max_fail_rounds: int,
    scope_violation_reason: str | None = None,
    evidence_channel_failure: str | None = None,
) -> tuple[str, str]:
    """Compute ``(run_status, termination_reason)`` from loop-exit state.

    Precedence (highest → lowest):
     -1. ``evidence_channel_failure`` set (C9c) → ``("failed",
         "infrastructure_abort")``. Outranks everything, including a
         scope violation: when the evidence channel is broken we cannot
         even trust the classification of the other failures, and the
         chain must halt rather than retry into the same environment.
      0. ``scope_violation_reason`` set (DataScope DS5) → ``("failed",
         "scope_violation")``. A configuration/invariant failure —
         deterministic on retry: nothing about this run's results is
         trustworthy.
      1. ``completed_rounds >= max_rounds`` → ``("completed", "completed")``.
      2. ``consecutive_fails >= max_fail_rounds`` → ``("partial",
         "aborted_fail_rounds")``.
      3. Fallback → ``("partial", "completed")``.

    F-SCANC-1 (operator decision packet v1, 2026-08-26): the
    ``gate_aborted`` input and its ``("partial", "aborted_by_gate")``
    branch are RETIRED with the SKIP_ITER action. The flag's only writer
    was the run loop's unreachable SKIP_ITER branch (severed by the C7
    decomposition), so the branch could never fire; the
    ``aborted_by_gate`` Literal stays on the OUTPUT schema so historical
    records remain readable, with no current producer.

    See ``docs/design/pluggable_health_checks.md`` §4 and the audit
    Gap #3 fix in the follow-up to commit-5b.
    """
    if evidence_channel_failure:
        return "failed", "infrastructure_abort"
    if scope_violation_reason:
        return "failed", "scope_violation"
    if completed_rounds >= max_rounds:
        return "completed", "completed"
    if consecutive_fails >= max_fail_rounds:
        return "partial", "aborted_fail_rounds"
    return "partial", "completed"


def _resolve_sample_set_cfg(
    mode: str,
    agent_input: HyperparamTuningInput,
    plan: ExperimentPlan,
) -> dict:
    """Resolve sample-set config for one round based on trial/formal/single_file mode.

    Formal-mode eval strategy is locked to ``snapshot``; the portion defaults
    to 1.0 (full clone — Phase M §12.2 production contract for cross-arch
    score comparability) but is now operator-controllable via
    ``agent_input.formal_eval_portion`` for smoke / CI runs that need to fit
    a tight ``formal_time_budget_minutes`` (Phase R, §13). Formal training
    levers come from ``agent_input.formal_*``. Trial-mode values come from
    the planner. Single-file mode uses safe defaults.

    Args:
        mode: One of ``"trial"``, ``"formal"``, ``"single_file"``.
        agent_input: Carries the operator-configurable ``formal_*`` knobs.
        plan: Planner-produced ExperimentPlan (source of trial-mode values).

    Returns:
        A dict with exactly 5 keys — ``trial_strategy``, ``trial_portion``,
        ``train_portion``, ``eval_strategy``, ``eval_portion``.
    """
    if mode == "formal":
        return {
            "trial_strategy": agent_input.formal_strategy,
            "trial_portion": agent_input.formal_portion,
            "train_portion": agent_input.formal_train_portion,
            "eval_strategy": "snapshot",
            "eval_portion": agent_input.formal_eval_portion,
        }
    if mode == "trial":
        return {
            "trial_strategy": plan.trial_strategy,
            "trial_portion": plan.trial_portion,
            "train_portion": plan.train_portion,
            "eval_strategy": plan.eval_strategy,
            "eval_portion": plan.eval_portion,
        }
    # single_file
    return {
        "trial_strategy": "snapshot",
        "trial_portion": plan.trial_portion,
        "train_portion": plan.train_portion,
        "eval_strategy": "snapshot",
        "eval_portion": 1.0,
    }


def _apply_plan_overrides(plan: ExperimentPlan, overrides: dict[str, Any]) -> ExperimentPlan:
    """Merge operator ``plan_overrides`` over the LLM plan and revalidate.

    FU-10 — the override lock is a contract: keys were validated and
    alias-normalized at schema level (`HyperparamTuningInput`), so the merge
    over the ``by_alias`` dump replaces exactly the intended fields. An
    effective plan that fails validation raises ``PlanOverridesError``
    (run-terminating, never retried) — the lock is never silently released
    back to the unclamped LLM plan. Empty overrides return the plan as-is.
    """
    if not overrides:
        return plan
    merged = plan.model_dump(by_alias=True) | overrides
    try:
        effective = ExperimentPlan.model_validate(merged)
    except Exception as e:
        raise PlanOverridesError(
            f"plan_overrides produced an invalid effective plan: {e}\n"
            f"  overrides={overrides}\n"
            f"  Fix the operator configuration and rerun — the override "
            f"lock is never silently released."
        ) from e
    print(f"  Plan overrides applied: {list(overrides.keys())}")
    return effective


#: Which override keys each resolved mode DISCARDS (review NOTE-b — the B1
#: fix exempted ``is_trial=False`` from the refusal, which is exactly the
#: condition that reaches single_file, so single_file must DISCLOSE or F14's
#: class survives there). Per ``_resolve_sample_set_cfg``: the formal branch
#: replaces all six; the single_file branch forces ``trial_strategy`` /
#: ``eval_strategy`` to "snapshot" and ``eval_portion`` to 1.0 while READING
#: ``trial_portion`` / ``train_portion`` — and the mode chain's trial
#: lockout discards an ``is_trial`` override on the way there. Trial mode
#: discards nothing.
_DISCARDED_OVERRIDE_KEYS_BY_MODE: dict[str, frozenset[str]] = {
    "formal": TRIAL_SCOPED_OVERRIDE_KEYS,
    "single_file": frozenset({"is_trial", "trial_strategy", "eval_strategy", "eval_portion"}),
}


def _disclose_inapplicable_trial_overrides(
    mode: str, agent_input: HyperparamTuningInput
) -> str | None:
    """Lane F / F14 — the override lock's honesty at the mode boundary.

    ``_apply_plan_overrides`` prints "Plan overrides applied" for EVERY
    attempt, but the resolved mode can discard some of what was just
    applied: a FORMAL round sources its whole workload from
    ``agent_input.formal_*`` (plus the snapshot eval lock); a SINGLE_FILE
    round forces the strategies and ``eval_portion`` while reading the
    portions. Before this disclosure, that pairing let a
    ``--trial_portion 1.0`` request train on the 10% ``formal_portion``
    default with no trace (the F14 witness). Returns the disclosure line
    (also printed) when it applies, else ``None`` — a return value so the
    boundary is directly testable.
    """
    discarded_for_mode = _DISCARDED_OVERRIDE_KEYS_BY_MODE.get(mode)
    if discarded_for_mode is None:
        return None
    trial_scoped = discarded_for_mode & set(agent_input.plan_overrides or {})
    if not trial_scoped:
        return None
    if mode == "formal":
        governs = (
            f"formal workload comes from formal_strategy={agent_input.formal_strategy} "
            f"formal_portion={agent_input.formal_portion} "
            f"formal_train_portion={agent_input.formal_train_portion} "
            f"formal_eval_portion={agent_input.formal_eval_portion} "
            f"(eval_strategy locked to 'snapshot')"
        )
    else:
        governs = (
            "single_file locks trial_strategy/eval_strategy to 'snapshot' and "
            "eval_portion to 1.0 (trial_portion/train_portion still apply)"
        )
    line = (
        f"  [plan_overrides] NOTE: trial-scoped override key(s) "
        f"{sorted(trial_scoped)} do NOT govern this {mode.upper()} round — {governs}."
    )
    print(line)
    return line


class ScoringRoute(StrEnum):
    """WHICH scoring path an attempt takes — named, not inferred.

    Step 12 / PR-12d D4b (B4). The decision used to be spelled
    ``if anchor_map_data is not None:``, with an ``else`` commented "legacy
    single-file mode". Two things were wrong with that, and only the first was
    in the register:

    * **a task with no anchor artifact fell through silently.** Every composed
      contrast task has none — no contrast implementation declares trial
      anchoring — so a Pets or DAVIS run took a branch named for TIDMAD's
      legacy single-file mode.
    * **so did every un-composed NON-TRIAL run.** ``anchor_map_data`` is only
      ATTEMPTED when the run is a trial, so the ``else`` was never "legacy
      single-file" in the sense its comment claimed. The comment described a
      condition the code did not test.

    Naming the routes makes both facts visible at the call site, and makes the
    third route — a task scoring its OWN deliverable through its OWN metric —
    something the reader can see rather than infer from an absence.
    """

    ANCHOR_NORMALIZED = "anchor_normalized"
    """TIDMAD's in-process anchor-normalized scoring. REQUIRES an anchor map."""

    TASK_OWNED = "task_owned"
    """A composed task's own deliverable, scored through its own metric in the
    scoring subprocess, with the evaluation scope its ground truth needs."""

    SUBPROCESS_LEGACY = "subprocess_legacy"
    """TIDMAD scoring through the subprocess, with no anchor normalization."""


def resolve_scoring_route(anchor_map_data, task_scopes) -> ScoringRoute:
    """Decide the route from what each one actually REQUIRES.

    An explicit task scope is the strongest authority: the task that built an
    opaque evaluation scope must also decode and score it. The in-process
    anchor route remains the compatibility path for an uncomposed run with a
    legacy ``SampleSet`` and anchor map. The subprocess legacy route needs
    neither.
    """
    if getattr(task_scopes, "evaluation", None) is not None:
        return ScoringRoute.TASK_OWNED
    if anchor_map_data is not None:
        return ScoringRoute.ANCHOR_NORMALIZED
    return ScoringRoute.SUBPROCESS_LEGACY
