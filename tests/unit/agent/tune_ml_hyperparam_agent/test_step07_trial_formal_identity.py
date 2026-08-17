"""Step 07 correction — trial/formal candidate identity is time-budget independent.

**The defect.** ``_best_trial_winner`` required trial metadata to agree in
BOTH the typed ``record.is_trial`` field and the persisted
``memory.time_mode`` field. ``memory.time_mode`` is written by the record
builder only ``if time_check is not None``
(``records.py``), and ``time_check`` is ``None`` whenever the active mode's
time budget is unset (``execution.py``: ``chosen_time_budget is None``).
So a campaign launched with

```text
--enable_chain_incumbent_formal_gates      (incumbent formal gates ON)
trial_time_budget_minutes  = None          (time budgets OFF)
formal_time_budget_minutes = None
```

produced a round-1 record that was a valid trial by every other measure
(``status == "success"``, finite score, ``is_trial is True``,
HealthGate-valid) and was still invisible to the trial-winner selection —
``_best_trial_winner`` returned ``None``, ``_should_skip_formal`` read that
as *no evidence*, and the forced formal round was skipped. Surfaced by
Step 07 PR 07b's Gate 1; the coupling predates 07b, which was not permitted
to change round semantics.

**The correction (CASE 1).** ``record.is_trial`` is the role authority — it
is written unconditionally from ``plan.is_trial`` (via
``trial_config.is_trial``) and is already the ONLY role field
``core/resume.py`` consults across runs. ``memory.time_mode`` is time-gate
metadata ("which budget was active"), and it is removed from role
eligibility. Its POPULATION is deliberately unchanged.

The defect this file catches, per assertion group:

* ``TestNoBudgetRegression`` — the exact Gate-1 shape. Deleting it lets the
  time-budget coupling return: a valid trial invisible to the winner.
* ``TestBudgetParity`` — role classification identical with budgets on and
  off. Deleting it lets the fix change the configuration that already worked.
* ``TestRoleFiltersUnchanged`` — formal / failed / non-finite / gate-invalid
  records still excluded. Deleting it lets the fix weaken candidate validity
  instead of only dropping the time condition.
* ``TestDirectionUnaffected`` — 07b's ``MetricOrder`` still picks WHICH trial
  wins; it never decides WHETHER a record is a trial.
* ``TestTimeMetadataNonInterference`` — the timing subsystem is untouched:
  budgets off still means no time fields on the record.
* ``TestProductionControlPath`` — the real ``HyperparamTuningAgent.run``
  reaches round 2 and emits a formal record under the corrected posture.
  Deleting it lets a helper-level fix pass while the production path still
  breaks at the formal boundary.
* ``TestPersistedRecords`` — persisted/resumed records with and without
  ``memory.time_mode`` classify identically.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from execute_tools.metric_order import MetricOrder
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    _best_trial_winner,
    _build_trial_validity_feedback,
    _should_bypass_formal_time_budget,
    _should_skip_formal,
)
from tests.helpers.metric_fixtures import direction_only_spec, shipped_spec
from tests.helpers.step00_pseudo_iteration import run_bounded_pseudo_iteration

HIGHER = MetricOrder(shipped_spec())
LOWER = MetricOrder(direction_only_spec())

_FIXTURES = Path(__file__).parent / "fixtures"
_PREFLIGHT_FIXTURE = _FIXTURES / "step00_preflight_results.json"


def _trial(
    exp_id: str,
    score: float,
    *,
    time_mode: str | None = None,
    is_trial: bool = True,
    status: str = "success",
) -> dict:
    """A HealthGate-valid record (DS5 self-describing disabled waiver).

    ``time_mode=None`` is the NO-BUDGET shape the record builder actually
    produces when the active mode has no time budget: the key is absent
    from ``memory`` entirely, not present-and-null.
    """
    memory: dict = {}
    if time_mode is not None:
        memory["time_mode"] = time_mode
    record: dict = {
        "exp_id": exp_id,
        "status": status,
        "denoising_score": score,
        "health_gate_enabled": False,
        "memory": memory,
    }
    if is_trial:
        record["is_trial"] = True
    return record


# ---------------------------------------------------------------------------
# 1 — the no-budget regression (PRIMARY acceptance)
# ---------------------------------------------------------------------------


class TestNoBudgetRegression:
    """Incumbent formal gates ON, trial/formal time budgets OFF."""

    def test_valid_trial_without_time_mode_is_the_winner(self):
        winner = _best_trial_winner([_trial("t_no_budget", -2.5)], order=HIGHER)
        assert winner is not None, (
            "a successful, finite, HealthGate-valid trial must be eligible "
            "whether or not the time gate ran"
        )
        assert winner["exp_id"] == "t_no_budget"

    def test_formal_boundary_receives_the_winner_not_no_evidence(self):
        """The consequence the defect actually had: SkipFormal fired."""
        winner = _best_trial_winner([_trial("t_no_budget", -2.5)], order=HIGHER)
        # `-inf` is the no-chain-incumbent bootstrap threshold the gates
        # resolve to (`_resolve_formal_comparison_thresholds`), i.e. the
        # exact production value under `--enable_chain_incumbent_formal_gates`
        # with no restored incumbent.
        assert not _should_skip_formal(
            winner,
            threshold=HIGHER.worst_sentinel,
            gates_enabled=True,
            order=HIGHER,
        )

    def test_no_valid_trial_still_skips(self):
        """The D-C3 correction is preserved: absence of evidence still skips."""
        assert _should_skip_formal(
            _best_trial_winner([], order=HIGHER),
            threshold=HIGHER.worst_sentinel,
            gates_enabled=True,
            order=HIGHER,
        )

    def test_trial_validity_feedback_sees_the_same_trials(self):
        """`_build_trial_validity_feedback` mirrors the winner predicate.

        Left on the two-field rule it would find NO trials at all under
        no-budget and return None — the planner would lose the
        "everything collapsed" report precisely when SkipFormal fired.
        """
        collapsed = {
            **_trial("t_collapsed", -2.5),
            "health_gate_enabled": True,
            "health_gate_results": [
                {
                    "gate_name": "output_diversity_blocking",
                    "execution_status": "passed",
                    "check_passed": False,
                    "would_invalidate_under_production_policy": True,
                }
            ],
        }
        feedback = _build_trial_validity_feedback(
            [collapsed],
            formal_skipped_for_no_valid_winner=True,
            healthgate_mode="blocking",
        )
        assert feedback is not None
        assert feedback.trial_records_considered == 1
        # A single persisted gate result does not cover the required
        # scientific set, so D-C6 classifies this UNKNOWN rather than
        # INVALID. That classification is not what this test is about —
        # what matters is that the record was SEEN as a trial at all.
        assert feedback.unknown_validity_count == 1
        assert feedback.formal_skipped_for_no_valid_winner is True

    def test_gates_disabled_path_is_untouched(self):
        """With the feature switch off nothing skips, winner or not."""
        for records in ([], [_trial("t_no_budget", -2.5)]):
            assert not _should_skip_formal(
                _best_trial_winner(records, order=HIGHER),
                threshold=HIGHER.worst_sentinel,
                gates_enabled=False,
                order=HIGHER,
            )


# ---------------------------------------------------------------------------
# 2 — budgets ON vs OFF: role classification is identical
# ---------------------------------------------------------------------------


class TestBudgetParity:
    """Only time evidence may differ between the two postures — not role."""

    _SCORES = (-3.0, -2.5, -2.9)

    def _history(self, time_mode: str | None) -> list:
        return [
            _trial(f"t{i}", score, time_mode=time_mode)
            for i, score in enumerate(self._SCORES, start=1)
        ]

    @pytest.mark.parametrize("order", [HIGHER, LOWER], ids=["higher", "lower"])
    @pytest.mark.parametrize(
        "threshold",
        [None, -3.0, -2.5, -2.0, float("-inf"), float("inf")],
    )
    def test_winner_and_gate_verdicts_match_budget_on_and_off(self, order, threshold):
        on = _best_trial_winner(self._history("trial"), order=order)
        off = _best_trial_winner(self._history(None), order=order)
        assert on is not None and off is not None
        assert on["exp_id"] == off["exp_id"]
        assert on["denoising_score"] == off["denoising_score"]
        for gates_enabled in (True, False):
            assert _should_skip_formal(
                on, threshold=threshold, gates_enabled=gates_enabled, order=order
            ) is _should_skip_formal(
                off, threshold=threshold, gates_enabled=gates_enabled, order=order
            )
        assert _should_bypass_formal_time_budget(
            on, threshold=threshold, order=order
        ) is _should_bypass_formal_time_budget(off, threshold=threshold, order=order)


# ---------------------------------------------------------------------------
# 3/4 — the role and validity filters that must NOT move
# ---------------------------------------------------------------------------


class TestRoleFiltersUnchanged:
    @pytest.mark.parametrize("order", [HIGHER, LOWER], ids=["higher", "lower"])
    def test_a_formal_record_never_becomes_the_trial_winner(self, order):
        """Both formal shapes: no ``is_trial`` key at all, and an explicit
        ``is_trial=False``. Neither carries a ``time_mode`` either, so a fix
        that merely dropped the condition without keeping the role filter
        would elect one of them."""
        no_key = _trial("f_no_key", 9.0, is_trial=False)
        explicit_false = {**_trial("f_false", 9.0, is_trial=False), "is_trial": False}
        for formal in (no_key, explicit_false):
            assert _best_trial_winner([formal], order=order) is None
            winner = _best_trial_winner([formal, _trial("t_ok", -2.5)], order=order)
            assert winner["exp_id"] == "t_ok"

    @pytest.mark.parametrize("order", [HIGHER, LOWER], ids=["higher", "lower"])
    @pytest.mark.parametrize(
        ("label", "record"),
        [
            ("failed", {**_trial("bad", 9.0, status="error")}),
            ("collapsed", {**_trial("bad", 9.0, status="failed_mode_collapse")}),
            ("none_score", {**_trial("bad", 0.0), "denoising_score": None}),
            ("pos_inf", {**_trial("bad", float("inf"))}),
            ("neg_inf", {**_trial("bad", float("-inf"))}),
            ("nan", {**_trial("bad", float("nan"))}),
            (
                "gate_invalid",
                {
                    **_trial("bad", 9.0),
                    "health_gate_enabled": True,
                    "health_gate_results": [
                        {
                            "gate_name": "output_diversity_blocking",
                            "execution_status": "passed",
                            "check_passed": False,
                            "would_invalidate_under_production_policy": True,
                        }
                    ],
                },
            ),
        ],
    )
    def test_ineligible_trials_stay_ineligible_without_a_time_mode(self, order, label, record):
        """Every one of these is scored to win under at least one direction
        and none carries a ``time_mode``. The old rule excluded them twice
        over; only the candidate-validity half may survive."""
        assert _best_trial_winner([record], order=order) is None, label


# ---------------------------------------------------------------------------
# 5 — MetricOrder decides WHICH trial wins, never WHETHER it is a trial
# ---------------------------------------------------------------------------


class TestDirectionUnaffected:
    def test_direction_moves_the_winner_but_not_the_candidate_set(self):
        history = [_trial("t_low", -3.0), _trial("t_high", -2.5)]
        assert _best_trial_winner(history, order=HIGHER)["exp_id"] == "t_high"
        assert _best_trial_winner(history, order=LOWER)["exp_id"] == "t_low"


# ---------------------------------------------------------------------------
# 6/11 — the timing subsystem is not touched
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def no_budget_run(tmp_path_factory):
    """One bounded pseudo tuner run under the corrected posture.

    ``enable_chain_incumbent_formal_gates=True`` with BOTH time budgets left
    at ``None`` — the exact configuration 07b's Gate 1 could not complete
    without temporarily enabling the budgets.
    """
    from _pytest.monkeypatch import MonkeyPatch

    preflight = json.loads(_PREFLIGHT_FIXTURE.read_text(encoding="utf-8"))["results"]
    mp = MonkeyPatch()
    tmp = tmp_path_factory.mktemp("step07_identity")
    try:
        return run_bounded_pseudo_iteration(
            tmp,
            mp,
            preflight_results=preflight,
            input_overrides={
                "enable_chain_incumbent_formal_gates": True,
                "trial_time_budget_minutes": None,
                "formal_time_budget_minutes": None,
            },
        )
    finally:
        mp.undo()


class TestTimeMetadataNonInterference:
    def test_no_budget_records_still_carry_no_time_fields(self, no_budget_run):
        """The fix is at ROLE CONSUMPTION. Nothing started writing time
        metadata into a run whose time gate never ran — that would change
        planner-visible history and the record surface."""
        output, _bridge, _sandbox, _workspace = no_budget_run
        records = [r if isinstance(r, dict) else r.model_dump() for r in (output.all_records or [])]
        assert records
        for record in records:
            memory = record.get("memory") or {}
            assert memory.get("time_mode") is None, record.get("exp_id")
            assert memory.get("time_estimate_minutes") is None
            assert memory.get("time_budget_minutes") is None


# ---------------------------------------------------------------------------
# 10 — the REAL production control path reaches the formal round
# ---------------------------------------------------------------------------


class TestProductionControlPath:
    def test_round_one_trial_promotes_to_a_round_two_formal_record(self, no_budget_run):
        """round 1 valid trial → trial-winner resolution → formal boundary →
        round 2 formal record, with both time budgets disabled.

        Pre-fix this run stopped after round 1: the SkipFormal gate broke out
        of the round loop with ``reason=no_valid_trial_winner``.
        """
        output, _bridge, _sandbox, _workspace = no_budget_run
        records = [r if isinstance(r, dict) else r.model_dump() for r in (output.all_records or [])]
        successes = [r for r in records if r.get("status") == "success"]
        trials = [r for r in successes if r.get("is_trial") is True]
        # A round-1 pre-flight skip also lacks `is_trial`, so "formal" here
        # must mean an EXECUTED formal round, not merely a record without
        # the trial key.
        formals = [r for r in successes if not r.get("is_trial")]
        assert trials, (
            "the fixture's round-1 trial must succeed for this regression to mean anything"
        )
        assert formals, (
            "no successful formal record — the forced formal round was skipped, "
            "which is the Step-07 trial/time-budget coupling defect"
        )
        assert output.completed_rounds >= 2


# ---------------------------------------------------------------------------
# 9 — persisted / resumed records
# ---------------------------------------------------------------------------


class TestPersistedRecords:
    def test_persisted_records_classify_by_is_trial_alone(self):
        """A record persisted by a budget-ON run and one persisted by a
        budget-OFF run must classify identically once read back. Legacy
        records with NO ``is_trial`` key remain formal, as before."""
        with_mode = _trial("legacy_with_mode", -2.5, time_mode="trial")
        without_mode = _trial("new_without_mode", -2.5)
        legacy_no_is_trial = {**_trial("legacy_no_role", -2.5, time_mode="trial")}
        legacy_no_is_trial.pop("is_trial")

        round_tripped = json.loads(json.dumps([with_mode, without_mode, legacy_no_is_trial]))
        assert _best_trial_winner(round_tripped[:1], order=HIGHER)["exp_id"] == "legacy_with_mode"
        assert _best_trial_winner(round_tripped[1:2], order=HIGHER)["exp_id"] == "new_without_mode"
        assert _best_trial_winner(round_tripped[2:], order=HIGHER) is None
