"""Step 07 PR 07b — C2: every golden-metric ORDERING consumer asks the one authority.

Design: ``docs/design/generic_framework_upgrade/step_07_tuner_policy_and_training_diagnostics/
pr_07b_tuner_policy.md`` §3.2 (the consumer table), §3.4 (the invalidated
outcome), §6 rung **B-07b-1**, §8 rows 1/2/5/6.

Three distinct claims, three distinct failure classes:

1. **B-07b-1 — the strict ORDERING axis.** Identical records, only
   ``MetricSpec.direction`` flipped, and every ordinal consumer inverts
   EXACTLY: trial winner, skip/bypass orientation and their disabled
   sentinels, the reflector's best / worst / rank / new-best, and all five
   ``best_*`` finalization tracks. Expectations are literals, never
   recomputed from the authority (a test that asks ``MetricOrder`` what the
   answer is would pass for any implementation).

   Scale arithmetic is deliberately absent: the efficiency band, the declared
   margins and the collapse penalty are a different failure class and belong
   to C3's rung. Mixing them here is exactly how a scale mutation hides
   behind an ordering assertion.

2. **The loss rank does NOT move.** ``same_loss_loss_rank`` and
   ``best_same_loss_final_loss`` are lower-is-better by definition of a loss.
   If they flipped with the metric, the reflector would be told the worst
   training run of a loss family was its best.

3. **Reachability.** ``MetricOrder`` is swapped for a recording double in the
   production module and a real bounded tuner run is driven through it: a
   consumer left on a bare ``max`` would still produce the right answer under
   TIDMAD and would never call the authority. The behavioural rungs above
   cannot see that; only this can.
"""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path
from typing import ClassVar

import pytest

from execute_tools.metric_order import MetricOrder
from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    _best_trial_winner,
    _build_reflection_context,
    _select_best_records,
    _should_bypass_formal_time_budget,
    _should_skip_formal,
)
from tests.helpers.metric_fixtures import direction_only_spec, shipped_spec
from tests.helpers.tuner_source import tuner_node_source
from tests.unit.agent.tune_ml_hyperparam_agent.test_step07b_c1_selection_replay import (
    _CORPUS_PATH,
    _decode,
)

_TUNER = importlib.import_module("nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent")
_TUNER_SOURCE = tuner_node_source()

HIGHER = MetricOrder(shipped_spec())
LOWER = MetricOrder(direction_only_spec())

CORPUS = _decode(json.loads(_CORPUS_PATH.read_text(encoding="utf-8")))["histories"]


def _history(case_id: str) -> list:
    return CORPUS[case_id]["records"]


def _valid(exp_id: str, score: float, *, is_trial: bool = True, time_mode: str = "trial") -> dict:
    """A HealthGate-valid record (the DS5 self-describing disabled waiver)."""
    return {
        "exp_id": exp_id,
        "status": "success",
        "denoising_score": score,
        "is_trial": is_trial,
        "health_gate_enabled": False,
        "memory": {"time_mode": time_mode},
    }


# ---------------------------------------------------------------------------
# B-07b-1 — the trial winner
# ---------------------------------------------------------------------------


class TestTrialWinnerInverts:
    @pytest.mark.parametrize(
        ("case_id", "higher_id", "lower_id"),
        [
            ("h_simple_trials", "t_high", "t_low"),
            ("h_collapse_penalty", "t_ok2", "t_ok"),
            ("h_trial_formal_mix", "t_only", "t_only"),
            ("h_neg_inf", "t_ok", "t_ok"),
            ("h_pos_inf", "t_ok", "t_ok"),
        ],
    )
    def test_argmax_becomes_argmin(self, case_id, higher_id, lower_id):
        records = _history(case_id)
        assert _best_trial_winner(records, order=HIGHER)["exp_id"] == higher_id
        assert _best_trial_winner(records, order=LOWER)["exp_id"] == lower_id

    @pytest.mark.parametrize("order", [HIGHER, LOWER], ids=["higher", "lower"])
    def test_empty_and_no_success_histories_have_no_winner(self, order):
        assert _best_trial_winner(_history("h_empty"), order=order) is None
        assert _best_trial_winner(_history("h_no_successes"), order=order) is None

    @pytest.mark.parametrize("order", [HIGHER, LOWER], ids=["higher", "lower"])
    def test_a_tie_at_the_extreme_keeps_the_first_record(self, order):
        """Which config the forced-formal round inherits depends on this."""
        tied = [_valid("first", 1.0), _valid("second", 1.0)]
        assert _best_trial_winner(tied, order=order)["exp_id"] == "first"


# ---------------------------------------------------------------------------
# B-07b-1 — the skip / bypass orientation and their sentinels
# ---------------------------------------------------------------------------


class TestGateOrientationInverts:
    WINNER = _valid("w", -2.5)

    def test_skip_fires_on_the_worse_side_of_the_threshold(self):
        winner = [self.WINNER]
        # higher: -2.5 is WORSE than -2.0 -> skip; better than -3.0 -> run.
        assert _should_skip_formal(
            _best_trial_winner(winner, order=HIGHER),
            threshold=-2.0,
            gates_enabled=True,
            order=HIGHER,
        )
        assert not _should_skip_formal(
            _best_trial_winner(winner, order=HIGHER),
            threshold=-3.0,
            gates_enabled=True,
            order=HIGHER,
        )
        # lower: the verdicts swap on the SAME numbers.
        assert not _should_skip_formal(
            _best_trial_winner(winner, order=LOWER),
            threshold=-2.0,
            gates_enabled=True,
            order=LOWER,
        )
        assert _should_skip_formal(
            _best_trial_winner(winner, order=LOWER),
            threshold=-3.0,
            gates_enabled=True,
            order=LOWER,
        )

    def test_bypass_clears_on_the_better_side_and_admits_the_tie(self):
        winner = _best_trial_winner([self.WINNER], order=HIGHER)
        assert _should_bypass_formal_time_budget(winner, threshold=-2.5, order=HIGHER)
        assert _should_bypass_formal_time_budget(winner, threshold=-3.0, order=HIGHER)
        assert not _should_bypass_formal_time_budget(winner, threshold=-2.0, order=HIGHER)
        assert _should_bypass_formal_time_budget(winner, threshold=-2.5, order=LOWER)
        assert _should_bypass_formal_time_budget(winner, threshold=-2.0, order=LOWER)
        assert not _should_bypass_formal_time_budget(winner, threshold=-3.0, order=LOWER)

    @pytest.mark.parametrize("order", [HIGHER, LOWER], ids=["higher", "lower"])
    def test_the_disabled_sentinels_follow_the_direction(self, order):
        """The literal ``-inf``/``+inf`` the pre-07b code compared against are
        the WORST and BEST values of a higher-is-better metric. Under
        ``lower`` they change places, and a sentinel left literal would leave
        the skip gate permanently armed and the bypass permanently disabled.
        """
        winner = _best_trial_winner([self.WINNER], order=order)
        assert not _should_skip_formal(
            winner, threshold=order.worst_sentinel, gates_enabled=True, order=order
        )
        assert not _should_bypass_formal_time_budget(
            winner, threshold=order.best_sentinel, order=order
        )
        # ... and the OPPOSITE sentinel is a live threshold, not a disable.
        assert _should_skip_formal(
            winner, threshold=order.best_sentinel, gates_enabled=True, order=order
        )
        assert _should_bypass_formal_time_budget(
            winner, threshold=order.worst_sentinel, order=order
        )

    @pytest.mark.parametrize("order", [HIGHER, LOWER], ids=["higher", "lower"])
    def test_no_valid_winner_still_skips_under_either_direction(self, order):
        assert _should_skip_formal(None, threshold=-2.0, gates_enabled=True, order=order)
        assert not _should_bypass_formal_time_budget(None, threshold=-2.0, order=order)


# ---------------------------------------------------------------------------
# B-07b-1 — the reflection context
# ---------------------------------------------------------------------------

_REFLECT_HISTORY = [
    _valid("baseline_run", -3.0, is_trial=False, time_mode="formal"),
    _valid("mid", -2.7, is_trial=False, time_mode="formal"),
    _valid("edge", -2.4, is_trial=False, time_mode="formal"),
]


def _reflect(order: MetricOrder, current_score: float | None) -> dict:
    return _build_reflection_context(
        memory_history=_REFLECT_HISTORY,
        current_score=current_score,
        current_loss_type="focal",
        current_final_loss=None,
        current_params=None,
        current_epochs=None,
        train_psd_segments=200,
        eval_psd_segments=200,
        trial_config=_TrialConfigStub(),
        score_table=None,
        order=order,
    )


class _TrialConfigStub:
    """The two fields the context reads, without dragging in the real schema."""

    mode = "single_file"
    trial_portion = None
    eval_portion = None


class TestReflectionContextInverts:
    def test_best_and_worst_swap(self):
        higher = _reflect(HIGHER, -2.7)
        lower = _reflect(LOWER, -2.7)
        assert higher["best_score_so_far"] == -2.4
        assert lower["best_score_so_far"] == -3.0
        assert higher["best_config_so_far"] is lower["best_config_so_far"] is None

    def test_rank_counts_the_records_that_are_actually_better(self):
        assert _reflect(HIGHER, -2.4)["rank"] == 1
        assert _reflect(HIGHER, -2.7)["rank"] == 2
        assert _reflect(HIGHER, -3.0)["rank"] == 3
        assert _reflect(LOWER, -3.0)["rank"] == 1
        assert _reflect(LOWER, -2.7)["rank"] == 2
        assert _reflect(LOWER, -2.4)["rank"] == 3

    def test_a_score_outside_the_successful_set_has_no_rank(self):
        """The pre-07b ``in sorted_scores`` guard, preserved: a failed round
        gets ``rank: None`` rather than an invented position."""
        assert _reflect(HIGHER, -9.9)["rank"] is None
        assert _reflect(HIGHER, None)["rank"] is None

    def test_is_new_best_flips(self):
        assert _reflect(HIGHER, -2.0)["is_new_best"] is True
        assert _reflect(HIGHER, -5.0)["is_new_best"] is False
        assert _reflect(LOWER, -5.0)["is_new_best"] is True
        assert _reflect(LOWER, -2.0)["is_new_best"] is False

    @pytest.mark.parametrize("order", [HIGHER, LOWER], ids=["higher", "lower"])
    def test_a_tie_with_the_incumbent_is_not_a_new_best(self, order):
        assert _reflect(order, -2.4 if order is HIGHER else -3.0)["is_new_best"] is False

    @pytest.mark.parametrize("order", [HIGHER, LOWER], ids=["higher", "lower"])
    def test_the_key_set_is_the_wf2_surface_under_both_directions(self, order):
        """WF-2 pins 23 context keys. A rewire that dropped or added one would
        change the reflector prompt without touching a prompt file."""
        assert len(_reflect(order, -2.7)) == 23


class TestLossRankDoesNotMove:
    HISTORY: ClassVar[list[dict]] = [
        {
            **_valid("a", -3.0, is_trial=False, time_mode="formal"),
            "final_loss": 0.5,
            "params": {"loss_config": {"loss_type": "focal"}},
        },
        {
            **_valid("b", -2.4, is_trial=False, time_mode="formal"),
            "final_loss": 0.2,
            "params": {"loss_config": {"loss_type": "focal"}},
        },
    ]

    def _context(self, order):
        return _build_reflection_context(
            memory_history=self.HISTORY,
            current_score=-2.7,
            current_loss_type="focal",
            current_final_loss=0.35,
            current_params=None,
            current_epochs=None,
            train_psd_segments=None,
            eval_psd_segments=None,
            trial_config=_TrialConfigStub(),
            score_table=None,
            order=order,
        )

    def test_loss_rank_and_best_loss_are_identical_under_both_directions(self):
        """A loss is lower-is-better BY DEFINITION. Routing it through the
        metric's order authority would make the reflector call the worst
        training run of a loss family its best the moment a task declares a
        lower-is-better metric."""
        higher = self._context(HIGHER)
        lower = self._context(LOWER)
        assert higher["same_loss_loss_rank"] == 2  # 0.2 < 0.35 < 0.5
        assert higher["best_same_loss_final_loss"] == 0.2
        assert lower["same_loss_loss_rank"] == higher["same_loss_loss_rank"]
        assert lower["best_same_loss_final_loss"] == higher["best_same_loss_final_loss"]
        assert lower["same_loss_total"] == higher["same_loss_total"] == 3


# ---------------------------------------------------------------------------
# B-07b-1 — the five best_* finalization tracks
# ---------------------------------------------------------------------------

_TRACK_RECORDS = [
    _valid("trial_worst", -4.0),
    _valid("trial_best", -1.0),
    _valid("formal_worst", -3.5, is_trial=False, time_mode="formal"),
    _valid("formal_best", -1.5, is_trial=False, time_mode="formal"),
]


class TestBestTracksInvert:
    def test_every_track_is_the_argmax_then_the_argmin(self):
        higher = _select_best_records(_TRACK_RECORDS, order=HIGHER)
        lower = _select_best_records(_TRACK_RECORDS, order=LOWER)
        assert (
            higher.top["exp_id"],
            higher.formal["exp_id"],
            higher.valid["exp_id"],
            higher.valid_formal["exp_id"],
            higher.valid_trial["exp_id"],
        ) == ("trial_best", "formal_best", "trial_best", "formal_best", "trial_best")
        assert (
            lower.top["exp_id"],
            lower.formal["exp_id"],
            lower.valid["exp_id"],
            lower.valid_formal["exp_id"],
            lower.valid_trial["exp_id"],
        ) == ("trial_worst", "formal_worst", "trial_worst", "formal_worst", "trial_worst")

    @pytest.mark.parametrize("order", [HIGHER, LOWER], ids=["higher", "lower"])
    def test_all_tracks_are_none_when_nothing_succeeded(self, order):
        tracks = _select_best_records(_history("h_no_successes"), order=order)
        assert (
            tracks.top,
            tracks.formal,
            tracks.valid,
            tracks.valid_formal,
            tracks.valid_trial,
        ) == (None, None, None, None, None)


# ---------------------------------------------------------------------------
# §3.4 — an invalidated result never becomes an incumbent, either direction
# ---------------------------------------------------------------------------


class TestInvalidatedResultsNeverWin:
    @pytest.mark.parametrize("order", [HIGHER, LOWER], ids=["higher", "lower"])
    def test_a_collapsed_record_scored_to_win_never_wins(self, order):
        """The penalty ``-5.0`` reads as the WORST score under ``higher`` and
        as the BEST under ``lower``; ``+9.0`` does the opposite. Whichever
        direction is bound, the collapsed record is scored so that a naive
        ordering would elect it.
        """
        winning_score = 9.0 if order is HIGHER else -5.0
        collapsed = {
            **_valid("collapsed", winning_score),
            "status": "failed_mode_collapse",
            "failure_reason": "amplitude_collapse",
        }
        records = [collapsed, _valid("healthy", -2.5)]
        assert _best_trial_winner(records, order=order)["exp_id"] == "healthy"
        tracks = _select_best_records(records, order=order)
        assert tracks.top["exp_id"] == "healthy"
        assert tracks.valid["exp_id"] == "healthy"
        assert tracks.valid_trial["exp_id"] == "healthy"
        context = _build_reflection_context(
            memory_history=records,
            current_score=-2.5,
            current_loss_type="focal",
            current_final_loss=None,
            current_params=None,
            current_epochs=None,
            train_psd_segments=None,
            eval_psd_segments=None,
            trial_config=_TrialConfigStub(),
            score_table=None,
            order=order,
        )
        assert context["best_score_so_far"] == -2.5
        assert context["total_experiments"] == 1

    @pytest.mark.parametrize("order", [HIGHER, LOWER], ids=["higher", "lower"])
    def test_a_gate_failed_record_scored_to_win_never_wins(self, order):
        """Validity is a FILTER, not part of the comparison — an
        ``is_valid_candidate`` failure must exclude the record before any
        ordering sees its score."""
        winning_score = 9.0 if order is HIGHER else -9.0
        cheater = {
            "exp_id": "cheater",
            "status": "success",
            "denoising_score": winning_score,
            "is_trial": True,
            "health_gate_enabled": True,
            "health_gate_results": [
                {
                    "gate_name": "output_diversity_blocking",
                    "execution_status": "passed",
                    "check_passed": False,
                    "would_invalidate_under_production_policy": True,
                }
            ],
            "memory": {"time_mode": "trial"},
        }
        records = [cheater, _valid("healthy", -2.5)]
        assert _best_trial_winner(records, order=order)["exp_id"] == "healthy"
        tracks = _select_best_records(records, order=order)
        assert tracks.valid["exp_id"] == "healthy"
        assert tracks.valid_trial["exp_id"] == "healthy"
        # ...but the UNFILTERED `top` track deliberately still admits it: that
        # track's contract is "best successful record", and 07b changes no
        # filter. Asserting otherwise would silently move Step 08's boundary.
        assert tracks.top["exp_id"] == "cheater"

    @pytest.mark.parametrize("order", [HIGHER, LOWER], ids=["higher", "lower"])
    def test_non_finite_scores_never_win_even_when_they_are_the_extreme(self, order):
        """``+inf`` is unbeatable under ``higher`` and ``-inf`` under
        ``lower``. Both are filtered as non-finite before ordering."""
        case = "h_pos_inf" if order is HIGHER else "h_neg_inf"
        records = _history(case)
        assert _best_trial_winner(records, order=order)["exp_id"] == "t_ok"
        assert _select_best_records(records, order=order).top["exp_id"] == "t_ok"


# ---------------------------------------------------------------------------
# Reachability — the production path really goes through the authority
# ---------------------------------------------------------------------------


class _RecordingOrder:
    """A ``MetricOrder`` that records which members production actually used."""

    calls: ClassVar[list[str]] = []

    def __init__(self, spec):
        self._inner = MetricOrder(spec)
        _RecordingOrder.calls = []

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if callable(attr):

            def recorded(*args, **kwargs):
                _RecordingOrder.calls.append(name)
                return attr(*args, **kwargs)

            return recorded
        _RecordingOrder.calls.append(name)
        return attr


def test_the_production_run_reaches_the_order_authority(tmp_path, monkeypatch):
    """MUTATION TARGET: a consumer left on a bare ``max``/``<``.

    Under TIDMAD such a consumer returns the right answer, so no behavioural
    assertion in this file can see it. Swapping the authority for a recorder
    and driving a REAL bounded tuner iteration can: the members below are
    recorded only if production asked for them.
    """
    from tests.helpers.step00_pseudo_iteration import run_bounded_pseudo_iteration

    preflight = json.loads(
        (Path(__file__).parent / "fixtures" / "step00_preflight_results.json").read_text(
            encoding="utf-8"
        )
    )["results"]
    monkeypatch.setattr(_TUNER, "MetricOrder", _RecordingOrder)
    run_bounded_pseudo_iteration(tmp_path, monkeypatch, preflight_results=preflight)

    used = set(_RecordingOrder.calls)
    # `best`        — the trial winner, the planner's score-table incumbent and
    #                 all five best_* tracks;
    # `worst`       — the reflector's score range;
    # `rank` / `is_better` — the reflector's rank and new-best;
    # `is_at_least` — the efficiency band's "clears the bar" comparison (C3).
    assert used == {"best", "worst", "rank", "is_better", "is_at_least"}, sorted(used)
    # Deliberately ABSENT, each for a reason this run makes true — asserting a
    # path the run does not take would be a false reachability claim:
    #   * the SENTINELS: this harness runs with
    #     `enable_chain_incumbent_formal_gates` off, so `_should_skip_formal`
    #     short-circuits before comparing against `worst_sentinel` and the
    #     resolver never bootstraps. Pinned by `TestGateOrientationInverts`,
    #     and in production by Gate 1's `--enable_chain_incumbent_formal_gates`.
    #   * `toward_better`: the same switch — no incumbent reference is resolved.
    #   * `toward_worse`: both rounds score 0.65, so the observed range is empty
    #     and the band falls to its single-score path. Pinned by the C3 rung.
    assert not {"worst_sentinel", "best_sentinel", "toward_better", "toward_worse"} & used


def test_no_bare_extremum_over_the_golden_metric_survives_in_the_tuner():
    """MUTATION TARGET: a 22nd ordering site nobody migrated.

    The §0.1 census found 21 golden-metric ordering expressions. A literal
    ``max(...)``/``min(...)``/``sorted(...)`` keyed on ``denoising_score``
    anywhere in the tuner is, by that census, a consumer that did not join
    the authority — and it would be invisible to every behavioural test as
    long as TIDMAD is the bound metric.
    """
    offenders = [
        line.strip()
        for line in _TUNER_SOURCE.splitlines()
        if re.search(r"\b(max|min|sorted)\s*\(", line) and "denoising_score" in line
    ]
    assert offenders == [], offenders

    # ...and the same-loss LOSS ordering is still a bare ascending sort,
    # because a loss is lower-is-better by definition and must NOT migrate.
    assert "sorted_finals = sorted(all_same_loss_finals)" in _TUNER_SOURCE
