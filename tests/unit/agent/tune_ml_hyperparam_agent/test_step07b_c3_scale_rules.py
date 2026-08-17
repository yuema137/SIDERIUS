"""Step 07 PR 07b — C3: the SCALE-sensitive policy rules, classified and executable.

Design: ``docs/design/generic_framework_upgrade/step_07_tuner_policy_and_training_diagnostics/
pr_07b_tuner_policy.md`` §3.3 (the per-rule classification table), §3.5 (the
attempt-transition disposition), §6 rung **B-07b-1s**, §8 rows 3/4.

**Why this is a separate rung from B-07b-1.** Ordering and scale fail
differently. A consumer can face the right way and still resolve the wrong
number: a threshold that adds where it should subtract, a band computed as a
fraction of a raw score rather than of the observed range, a penalty whose
sign convention silently inverts. Every one of those passes an ordering
assertion. The parent design forbids claiming a scale-sensitive rule generic
merely because its comparison sign flips, so the two axes are tested apart.

**Why the fixtures are not TIDMAD-shaped.** TIDMAD scores sit around −3 in a
log space, which is exactly where a TIDMAD-tuned default *looks* right. The
rung uses an accuracy-like metric on [0, 1] and an MSE-like metric near 0 —
scales on which a `−1.0` margin or a raw `best − 0.05` band is visibly
nonsense — so a rule that quietly kept its old arithmetic cannot hide.

The classification each test exercises (§3.3):

| Rule | Class |
|---|---|
| declared skip / bypass margins | (ii) DECLARED — units are the metric's, orientation is the authority's |
| bootstrap reference | (i) generic — "no incumbent yet" is an ORDER fact |
| disabled sentinels | (i) generic |
| efficiency band | (i) generic — normalised by the run's OBSERVED range |
| collapse penalty | (ii) DECLARED, with (iv) inapplicable → FAIL CLOSED under `lower` |
"""

from __future__ import annotations

import pytest

from execute_tools.metric_order import MetricOrder
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    EFFICIENCY_BAND_FRACTION,
    _build_reflection_context,
    _resolve_formal_comparison_thresholds,
    _should_bypass_formal_time_budget,
    _should_skip_formal,
    _validate_penalty_for_direction,
)
from tests.helpers.metric_fixtures import accuracy_like_spec, error_like_spec, shipped_spec
from tests.helpers.tuner_source import tuner_lifecycle_source

ACCURACY = MetricOrder(accuracy_like_spec())  # higher, values in [0, 1]
MSE = MetricOrder(error_like_spec())  # lower, values near 0
TIDMAD = MetricOrder(shipped_spec())


def _resolve(order, reference, skip_delta, bypass_delta, *, gates_enabled=True):
    return _resolve_formal_comparison_thresholds(
        reference_score=reference,
        skip_min_delta=skip_delta,
        bypass_min_delta=bypass_delta,
        gates_enabled=gates_enabled,
        order=order,
    )


# ---------------------------------------------------------------------------
# Row 1 — the DECLARED margins
# ---------------------------------------------------------------------------


class TestDeclaredMargins:
    def test_tidmad_thresholds_are_numerically_unchanged(self):
        """The whole point of classifying rather than rewriting: the shipped
        campaign's resolved numbers must be the pre-07b ones, to the digit."""
        ref, skip_t, bypass_t, source = _resolve(TIDMAD, -2.5, -1.0, 0.0)
        assert (ref, skip_t, bypass_t) == (-2.5, -3.5, -2.5)
        assert source == "restored_valid_formal_incumbent"

    def test_the_margin_moves_toward_worse_under_both_directions(self):
        """A declared ``-1.0`` means "one unit of slack", not "subtract one".

        On the accuracy metric that is 0.90 → 0.89; on the MSE metric the
        equally-loose threshold is 0.010 → 0.011. A rule that kept ``ref +
        delta`` would resolve 0.009 there — TIGHTER than the incumbent, so a
        trial that genuinely regressed would still launch a formal round.
        """
        _r, skip_t, _b, _s = _resolve(ACCURACY, 0.90, -0.01, 0.0)
        assert skip_t == pytest.approx(0.89)
        _r, skip_t, _b, _s = _resolve(MSE, 0.010, -0.001, 0.0)
        assert skip_t == pytest.approx(0.011)

    def test_a_positive_margin_tightens_under_both_directions(self):
        _r, _s, bypass_t, _src = _resolve(ACCURACY, 0.90, -0.01, 0.02)
        assert bypass_t == pytest.approx(0.92)
        _r, _s, bypass_t, _src = _resolve(MSE, 0.010, -0.001, 0.002)
        assert bypass_t == pytest.approx(0.008)

    @pytest.mark.parametrize("order", [ACCURACY, MSE], ids=["higher", "lower"])
    def test_the_operator_disable_convention_keeps_its_meaning(self, order):
        """``skip_delta=-inf`` disables the skip gate and
        ``bypass_delta=+inf`` disables the bypass — documented for the shipped
        metric, and the operator should not have to learn a second convention
        when the campaign's metric is minimised.
        """
        _r, skip_t, bypass_t, _s = _resolve(order, 0.5, float("-inf"), float("inf"))
        assert skip_t == order.worst_sentinel
        assert bypass_t == order.best_sentinel
        winner = {"denoising_score": 0.5}
        assert not _should_skip_formal(winner, threshold=skip_t, gates_enabled=True, order=order)
        assert not _should_bypass_formal_time_budget(winner, threshold=bypass_t, order=order)


# ---------------------------------------------------------------------------
# Rows 2 / 3 — the sentinels
# ---------------------------------------------------------------------------


class TestSentinels:
    @pytest.mark.parametrize("order", [ACCURACY, MSE], ids=["higher", "lower"])
    def test_the_bootstrap_is_the_orders_worst_value(self, order):
        """ "No incumbent yet, so anything clears it" is an ORDER fact. A
        literal ``-inf`` under a minimised metric would be the BEST possible
        reference, so nothing would ever clear the bypass and the first valid
        trial of a fresh chain would be budget-blocked — the exact v15 failure
        the bootstrap was written to prevent."""
        ref, skip_t, bypass_t, source = _resolve(order, None, -1.0, 0.0)
        assert ref == skip_t == bypass_t == order.worst_sentinel
        assert source == "negative_infinity_bootstrap"
        winner = {"denoising_score": 0.5}
        assert not _should_skip_formal(winner, threshold=skip_t, gates_enabled=True, order=order)
        assert _should_bypass_formal_time_budget(winner, threshold=bypass_t, order=order)

    def test_the_provenance_label_is_stable_across_directions(self):
        """``negative_infinity_bootstrap`` is persisted on records, so it stays
        a stable LABEL even where the value is ``+inf``; renaming it would be a
        record-vocabulary change (D1-adjacent, not authorised in 07b)."""
        assert _resolve(MSE, None, -1.0, 0.0)[3] == "negative_infinity_bootstrap"

    @pytest.mark.parametrize("order", [ACCURACY, MSE], ids=["higher", "lower"])
    def test_gates_off_resolves_nothing_at_all(self, order):
        assert _resolve(order, None, -1.0, 0.0, gates_enabled=False) == (
            None,
            None,
            None,
            "gates_disabled",
        )


# ---------------------------------------------------------------------------
# Row 4 — the efficiency band
# ---------------------------------------------------------------------------


class _TrialConfigStub:
    mode = "single_file"
    trial_portion = None
    eval_portion = None


def _context(order, history, current_score, *, current_params=None, current_epochs=None):
    return _build_reflection_context(
        memory_history=history,
        current_score=current_score,
        current_loss_type="focal",
        current_final_loss=None,
        current_params=current_params,
        current_epochs=current_epochs,
        train_psd_segments=None,
        eval_psd_segments=None,
        trial_config=_TrialConfigStub(),
        score_table=None,
        order=order,
    )


def _rec(exp_id, score, *, params=None, epochs=1):
    return {
        "exp_id": exp_id,
        "status": "success",
        "denoising_score": score,
        "health_gate_enabled": False,
        "model_params": params,
        "params": {"train_config": {"epochs": epochs}, "loss_config": {"loss_type": "focal"}},
        "memory": {"time_mode": "formal"},
    }


class TestEfficiencyBand:
    def test_the_constant_is_one_symbol(self):
        """The prompts tell the LLM "within 5% of the current best" and the
        policy applies the band. Two literals could drift and the agent would
        be optimising against a rule the tuner does not use."""
        assert EFFICIENCY_BAND_FRACTION == 0.05

    def test_the_band_is_a_fraction_of_the_observed_range_not_of_the_score(self):
        """On an accuracy metric the run's best is 0.90 and its worst 0.50, so
        the band is 0.90 − 0.05·0.40 = 0.88. A raw ``best − 0.05`` would give
        0.85 — a band eight times wider than the policy states, admitting
        clearly worse configurations as "efficient". The values are hardcoded,
        never recomputed from the constant.
        """
        history = [_rec("worst", 0.50, params=1000), _rec("best", 0.90, params=1000)]
        # 0.88 clears the band, 0.87 does not; both are far above a raw 0.85.
        assert _context(ACCURACY, history, 0.88, current_params=500)["is_more_efficient"] is True
        assert _context(ACCURACY, history, 0.87, current_params=500)["is_more_efficient"] is False

    def test_the_band_opens_toward_worse_on_a_minimised_metric(self):
        """Best 0.010, worst 0.050 → range 0.040 → threshold 0.010 + 0.002 =
        0.012. A raw ``best − 0.05·range`` would give 0.008, which is BETTER
        than the run's best — no result could ever clear it, so the efficiency
        signal would be permanently dead on every minimised metric."""
        history = [_rec("worst", 0.050, params=1000), _rec("best", 0.010, params=1000)]
        assert _context(MSE, history, 0.012, current_params=500)["is_more_efficient"] is True
        assert _context(MSE, history, 0.013, current_params=500)["is_more_efficient"] is False

    def test_tidmad_band_values_are_unchanged(self):
        """Best −2.0, worst −4.0 → range 2.0 → threshold −2.1, exactly the
        pre-07b ``best − 0.05·(best − worst)``."""
        history = [_rec("worst", -4.0, params=1000), _rec("best", -2.0, params=1000)]
        assert _context(TIDMAD, history, -2.1, current_params=500)["is_more_efficient"] is True
        assert _context(TIDMAD, history, -2.11, current_params=500)["is_more_efficient"] is False

    @pytest.mark.parametrize("order", [ACCURACY, MSE, TIDMAD], ids=["higher", "lower", "tidmad"])
    def test_a_single_distinct_score_falls_back_to_the_best_itself(self, order):
        """``range is None`` — the pre-07b path, unchanged: with nothing to
        normalise by, the threshold IS the best score."""
        history = [_rec("a", 0.5, params=1000), _rec("b", 0.5, params=1000)]
        assert _context(order, history, 0.5, current_params=500)["is_more_efficient"] is True

    def test_efficiency_still_requires_a_smaller_or_shorter_configuration(self):
        """Clearing the band is necessary, not sufficient — 07b changes the
        threshold's arithmetic and nothing else about the predicate."""
        history = [_rec("worst", 0.50, params=1000), _rec("best", 0.90, params=1000)]
        assert _context(ACCURACY, history, 0.89, current_params=2000)["is_more_efficient"] is False


# ---------------------------------------------------------------------------
# Row 5 — the collapse penalty: DECLARED, and inapplicable under `lower`
# ---------------------------------------------------------------------------


class _Input:
    def __init__(self, penalty):
        self.degenerate_penalty_score = penalty


class TestPenaltyGuard:
    @pytest.mark.parametrize("order", [ACCURACY, MSE, TIDMAD], ids=["higher", "lower", "tidmad"])
    def test_none_is_direction_free_and_always_accepted(self, order):
        _validate_penalty_for_direction(_Input(None), order)

    @pytest.mark.parametrize("penalty", [-5.0, 0.0, -1e9])
    def test_a_finite_penalty_is_accepted_under_a_maximised_metric(self, penalty):
        """Today's documented behaviour, unchanged — 07b must not tighten the
        shipped campaign's configuration surface."""
        _validate_penalty_for_direction(_Input(penalty), TIDMAD)
        _validate_penalty_for_direction(_Input(penalty), ACCURACY)

    def test_a_finite_penalty_is_REFUSED_under_a_minimised_metric(self):
        """Fail closed, with the reason. Negating it would be inventing policy
        the operator never declared, and accepting it verbatim would hand the
        planner a collapsed round that reads as the campaign's best result."""
        with pytest.raises(ValueError) as excinfo:
            _validate_penalty_for_direction(_Input(-5.0), MSE)
        message = str(excinfo.value)
        assert "degenerate_penalty_score=-5.0" in message
        assert "lower" in message
        assert "degenerate_penalty_score=None" in message

    def test_the_refusal_is_reached_from_production_startup(self):
        """Reachability: a guard nobody calls is a comment.

        The tuner must refuse BEFORE any LLM call or file I/O, on the same
        startup path as every other illegal operator flag.
        """
        import inspect

        from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
            HyperparamTuningAgent,
        )

        source = tuner_lifecycle_source()
        assert "_validate_penalty_for_direction(agent_input, run_order)" in source
        # ...and it sits with the other startup refusals, not somewhere in the
        # round loop where an LLM call would already have been paid for.
        guard = source.index("_validate_penalty_for_direction(agent_input, run_order)")
        assert guard < source.index("while completed_rounds < max_rounds")


# ---------------------------------------------------------------------------
# §3.5 — the removed types
# ---------------------------------------------------------------------------


def test_the_attempt_transition_types_are_gone_from_production():
    """They had zero production consumers and could not be wired without
    changing round outcomes, which 07b may not do (§3.5, Q-07b-1)."""
    import importlib

    tuner = importlib.import_module(
        "nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent"
    )

    assert not hasattr(tuner, "AttemptTransition")
    assert not hasattr(tuner, "AttemptDecision")
    # The round-outcome consumer that IS wired stays.
    assert hasattr(tuner, "RoundDecision")
    assert hasattr(tuner, "_decide_round_outcome")


def test_the_resolved_action_hazard_is_recorded_beside_the_declaration():
    """The defect the removed types described is real and unfixed. Deleting
    them without leaving the hazard where the next reader of ``run()`` will
    meet it would have destroyed the only record of it."""
    import inspect

    from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
        HyperparamTuningAgent,
    )

    source = tuner_lifecycle_source()
    declaration = source.index("resolved_action: GateAction = GateAction.CONTINUE")
    note = source[max(0, declaration - 1400) : declaration]
    assert "KNOWN DEFECT" in note
    assert "never reset between attempts" in note
