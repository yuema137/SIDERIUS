"""V21 PR C5a — a valid trial winner really becomes the formal plan.

**The segment PR A did not prove.** Its Gate 2C persisted a genuinely
formal record for a generated model — `scientific_authority` present,
`is_trial` absent, numeric score — so this chain is already real:

    measurement -> admission -> formal executes -> formal record

But that run logged *"no successful trial round is HealthGate-valid in
this iteration"*, so formal ran on the **planner's unvalidated plan**. The
head was never exercised:

    HealthGate-valid trial -> winner -> winner's params inherited -> formal

That is what this module proves, and it proves it as a **state-machine**
property, never a model-quality one:

    PROVE   "if a valid trial exists, the winner drives formal"
    NOT     "this model trains well enough to produce a valid trial"

**No training happens here, by operator decision.** Whether a real model
happens to reach HealthGate-valid is a *scientific outcome*, and a
scientific outcome must never be a state-machine acceptance oracle —
tuning a workload until the science cooperates is the V20 Case A error.
The trial's validity is therefore **dictated**: `is_valid_candidate` is a
pure predicate over a record dict, so a valid trial is *constructed*.

`[FORMAL OVERRIDE]` alone is NOT an error signal — the healthy path prints
it too, because the name refers to overriding the *planner's* plan with the
*winner's* parameters, which is exactly what should happen. The assertion
is two-sided:

    ABSENT   :1798  "no successful trial round is HealthGate-valid"
    PRESENT  :1834  strategy=... winner='<exp_id>' score=... inherited=...
"""

from __future__ import annotations

import pytest

from agent.schemas.hyperparam_tuning import ExperimentPlan
from execute_tools.health_checks.candidate_eligibility import (
    is_valid_candidate,
    required_blocking_gate_ids,
)
from execute_tools.metric_order import MetricOrder
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    _apply_mode_override_chain,
    _best_trial_winner,
)
from tests.helpers.metric_fixtures import direction_only_spec, shipped_spec

#: Step 07 PR 07b — the selection helpers consume the run's ONE order
#: authority (``MetricSpec.direction`` interpreted in exactly one place).
#: The SHIPPED higher-is-better order is this module's default, so every
#: assertion below states exactly the property it stated before 07b.
HIGHER_ORDER = MetricOrder(shipped_spec())
LOWER_ORDER = MetricOrder(direction_only_spec())


_GENERATED_MODEL = "c5a_generated_candidate_model"

_WARNING_LINE = "no successful trial round is HealthGate-valid"
_WINNER_LINE = "[FORMAL OVERRIDE] strategy="


def _passing_gate(gate_name: str) -> dict:
    """One blocking gate result in its passing shape."""
    return {
        "gate_name": gate_name,
        "execution_status": "passed",
        "check_passed": True,
        "would_invalidate_under_production_policy": False,
    }


def _valid_trial_record(exp_id: str, score: float, *, batch_size: int, lr: float) -> dict:
    """A HealthGate-VALID trial record, constructed rather than trained for.

    Satisfies every condition `classify_candidate_health` checks: success
    status, a finite numeric score, and every **required blocking gate**
    present, executed, passed, and not production-invalidating. The gate
    list is read from `required_blocking_gate_ids()` rather than hardcoded,
    so adding a blocking gate to the shipped policy makes this fixture
    follow rather than silently stop being valid.
    """
    return {
        "exp_id": exp_id,
        "status": "success",
        "denoising_score": score,
        "is_trial": True,
        "memory": {"time_mode": "trial", "round_index": 1},
        "model_type": _GENERATED_MODEL,
        # The inheritance handlers read the record's ``params`` block --
        # ``winner["params"]["train_config"]`` etc. Using the production
        # shape rather than a convenient one is the point: a fixture that
        # invented its own layout would prove nothing about inheritance.
        "params": {
            "model_config": {"segmentation_size": 64},
            "train_config": {
                "batch_size": batch_size,
                "lr": lr,
                "epochs": 1,
                "optimizer": "adam",
            },
            "loss_config": {"loss_type": "focal"},
        },
        "health_gate_results": [_passing_gate(g) for g in sorted(required_blocking_gate_ids())],
    }


@pytest.fixture
def winner_record() -> dict:
    return _valid_trial_record("c5a_iter_001_002", -2.5, batch_size=8, lr=3e-4)


@pytest.fixture
def loser_record() -> dict:
    return _valid_trial_record("c5a_iter_001_001", -4.0, batch_size=2, lr=9e-9)


class TestTheConstructedTrialIsGenuinelyValid:
    """If the fixture is not actually valid, everything below is vacuous."""

    def test_the_constructed_record_passes_the_real_predicate(self, winner_record):
        """Asserted against production's own predicate, not a local copy."""
        assert is_valid_candidate(winner_record) is True

    def test_a_failing_blocking_gate_makes_it_invalid(self, winner_record):
        """The fixture is valid for a REASON, not by accident.

        Without this, a fixture that happened to satisfy the predicate for
        some unrelated reason would make the whole module pass while
        proving nothing about HealthGate validity.
        """
        winner_record["health_gate_results"][0]["check_passed"] = False
        assert is_valid_candidate(winner_record) is False


class TestWinnerSelection:
    """`_best_trial_winner` — the first step of the head."""

    def test_the_highest_scoring_valid_trial_wins(self, winner_record, loser_record):
        got = _best_trial_winner([loser_record, winner_record], order=HIGHER_ORDER)
        assert got is not None
        assert got["exp_id"] == "c5a_iter_001_002"

    def test_an_invalid_trial_is_never_the_winner(self, winner_record, loser_record):
        """A higher-scoring but gate-INVALID record must not win.

        This is the V19/V20 pathology in miniature: a good-looking scalar
        from a collapsed run outranking a legitimate one.
        """
        cheater = _valid_trial_record("c5a_cheater", 9.9, batch_size=1, lr=1.0)
        cheater["health_gate_results"][0]["check_passed"] = False

        got = _best_trial_winner([loser_record, winner_record, cheater], order=HIGHER_ORDER)
        assert got is not None
        assert got["exp_id"] == "c5a_iter_001_002"

    def test_no_valid_trial_yields_no_winner(self, winner_record):
        """The precondition of the :1798 pathology."""
        winner_record["health_gate_results"][0]["check_passed"] = False
        assert _best_trial_winner([winner_record], order=HIGHER_ORDER) is None


class TestTheWinnerDrivesTheFormalPlan:
    """The property PR A never exercised."""

    def _drive(self, capsys, plan, winner, history, strategy="full_clone"):
        out_plan = _apply_mode_override_chain(
            plan,
            trial_allowed=False,
            is_formal_round=True,
            force_formal_round=True,
            formal_round_strategy=strategy,
            memory_history=history,
            trial_winner=winner,
        )
        return out_plan, capsys.readouterr().out

    def test_valid_winner_produces_the_inheritance_line_and_no_warning(
        self, capsys, winner_record, loser_record
    ):
        """The two-sided assertion, stated in §0.1 of the PR C design doc.

        `[FORMAL OVERRIDE]` on its own proves nothing — the healthy path
        prints it too. What distinguishes the states is which variant.
        """
        history = [loser_record, winner_record]
        winner = _best_trial_winner(history, order=HIGHER_ORDER)
        plan = ExperimentPlan(
            model_type=_GENERATED_MODEL,
            train_cfg={"batch_size": 1, "lr": 1e-9, "epochs": 1, "optimizer": "adam"},
            is_trial=True,
        )

        out_plan, printed = self._drive(capsys, plan, winner, history)

        assert _WARNING_LINE not in printed, (
            "the no-valid-winner WARNING fired even though a valid trial "
            "winner was supplied — this is the state PR A's Gate 2C was in"
        )
        assert _WINNER_LINE in printed
        assert "winner='c5a_iter_001_002'" in printed
        assert "winner=none" not in printed
        assert "inherited=(none)" not in printed
        assert out_plan.is_trial is False

    def test_the_inherited_values_are_the_winners_own(self, capsys, winner_record, loser_record):
        """Naming the winner in a log line is not the same as using it.

        The plan starts with deliberately absurd hyperparameters. If
        inheritance is real, they are replaced by the winner's.
        """
        history = [loser_record, winner_record]
        winner = _best_trial_winner(history, order=HIGHER_ORDER)
        plan = ExperimentPlan(
            model_type=_GENERATED_MODEL,
            train_cfg={"batch_size": 1, "lr": 1e-9, "epochs": 1, "optimizer": "adam"},
            is_trial=True,
        )

        out_plan, _ = self._drive(capsys, plan, winner, history)

        assert out_plan.train_cfg["batch_size"] == 8
        assert out_plan.train_cfg["lr"] == pytest.approx(3e-4)

    def test_no_winner_produces_the_warning_and_leaves_the_plan_alone(self, capsys):
        """The pathology, reproduced deliberately.

        Fails if the WARNING stops firing when there is genuinely no valid
        winner — that would hide the exact condition PR C exists to detect.
        """
        plan = ExperimentPlan(
            model_type=_GENERATED_MODEL,
            train_cfg={"batch_size": 1, "lr": 1e-9, "epochs": 1, "optimizer": "adam"},
            is_trial=True,
        )
        out_plan, printed = self._drive(capsys, plan, None, [])

        assert _WARNING_LINE in printed
        assert out_plan.train_cfg["batch_size"] == 1  # planner's plan, unchanged

    def test_independent_strategy_would_make_the_assertion_vacuous(self, capsys, winner_record):
        """Why C5 must not run with ``formal_round_strategy="independent"``.

        ``independent`` deliberately disclaims inheritance, so it prints a
        third `[FORMAL OVERRIDE]` variant and inherits nothing. A Gate that
        asserted only on the tag would pass here while proving the
        opposite of the intended property.
        """
        history = [winner_record]
        winner = _best_trial_winner(history, order=HIGHER_ORDER)
        plan = ExperimentPlan(
            model_type=_GENERATED_MODEL,
            train_cfg={"batch_size": 1, "lr": 1e-9, "epochs": 1, "optimizer": "adam"},
            is_trial=True,
        )

        out_plan, printed = self._drive(capsys, plan, winner, history, strategy="independent")

        assert _WARNING_LINE not in printed
        assert out_plan.train_cfg["batch_size"] == 1, (
            "'independent' inherited the winner's parameters — the strategy "
            "that disclaims inheritance must not inherit"
        )
