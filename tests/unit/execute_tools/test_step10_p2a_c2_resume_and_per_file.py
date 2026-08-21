"""Step 10 / P2a — C2: resume selection and per-file best, direction-aware.

Design: ``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p2a_golden_metric_order_closure.md`` §4.2a (the resume four-case matrix),
§4.3 (the site-5 ruling), §6; deviation D-P2a-1 (the chain fold).

Why this module exists in the shape it does
-------------------------------------------
The two helpers C2 migrates are small pure functions with RICH tie-breaking, so
a careless migration changes tie behaviour while looking like a one-line diff.
Every tie class therefore gets its own assertion, compared against the C0
golden captured BEFORE the migration, and the score comparison is exercised
under both directions.

The four resume cases are asserted on the RESTORED RESULT, not on stdout: a
notice that prints while the wrong record is still selected would otherwise
read as success.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.resume import _chain_fold_order, _pick_best, _rankable_pool
from execute_tools.evaluation_metric import (
    METRIC_IDENTITY_UNAVAILABLE,
    MetricIdentityConflictError,
    MetricIdentityKey,
    metric_identity_from_record,
)
from execute_tools.metric_order import MetricOrder
from execute_tools.per_file_best import LOG_BASE, _log, _row_beats
from tests.helpers.metric_fixtures import error_like_spec, shipped_spec
from tests.unit.execute_tools.test_step10_p2a_c0_ordering_goldens import (
    ROW_BEATS_PROBES,
    TIDMAD_PICK_BEST_POOL,
    TIDMAD_PICK_BEST_TRAJECTORY,
    TIE_PICK_BEST_POOL,
    TIE_PICK_BEST_TRAJECTORY,
    _row,
)

TIDMAD = shipped_spec()
DAVIS = error_like_spec()
HIGHER = MetricOrder(TIDMAD)
LOWER = MetricOrder(DAVIS)


# ---------------------------------------------------------------------------
# Site 4 — _pick_best
# ---------------------------------------------------------------------------


def _trajectory(pool, order: MetricOrder) -> tuple[str, ...]:
    out: list[str] = []
    for size in range(1, len(pool) + 1):
        best = _pick_best([dict(r) for r in pool[:size]], order=order)
        assert best is not None
        out.append(str(best["exp_id"]))
    return tuple(out)


class TestPickBestIsDirectionAware:
    def test_tidmad_trajectory_is_byte_equal_to_the_c0_golden(self):
        """Backward parity: the pre-migration sequence, unchanged."""
        assert _trajectory(TIDMAD_PICK_BEST_POOL, HIGHER) == TIDMAD_PICK_BEST_TRAJECTORY

    def test_under_lower_the_minimum_is_selected(self):
        """The same pool, opposite direction: -7.9 is now the best score."""
        assert _trajectory(TIDMAD_PICK_BEST_POOL, LOWER) == ("exp_a", "exp_a", "exp_c")

    def test_the_two_directions_actually_disagree_on_this_pool(self):
        """Anti-vacuity — a fixture on which both directions agree proves
        nothing about direction."""
        assert _trajectory(TIDMAD_PICK_BEST_POOL, HIGHER) != _trajectory(
            TIDMAD_PICK_BEST_POOL, LOWER
        )

    def test_the_exp_id_tie_break_is_unchanged_under_BOTH_directions(self):
        """The tie rule is direction-INDEPENDENT and must survive byte-equal."""
        for order in (HIGHER, LOWER):
            assert _trajectory(TIE_PICK_BEST_POOL, order) == TIE_PICK_BEST_TRAJECTORY

    def test_an_empty_pool_selects_nothing(self):
        assert _pick_best([], order=HIGHER) is None

    def test_order_is_keyword_only_and_has_no_default(self):
        """A caller that never reconciled an identity must not reach a ranking
        by simply omitting the argument."""
        with pytest.raises(TypeError):
            _pick_best([dict(TIDMAD_PICK_BEST_POOL[0])])  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# §4.2a — the resume four-case identity matrix
# ---------------------------------------------------------------------------


def _rec(exp_id: str, score: float, *, identity: tuple[str, str] | None) -> dict[str, Any]:
    record: dict[str, Any] = {"exp_id": exp_id, "denoising_score": score}
    if identity is not None:
        record["metric_result"] = {
            "metric_id": identity[0],
            "direction": identity[1],
            "scalar": score,
        }
    return record


class _Parsed:
    """Minimal stand-in for a validated HyperparamTuningOutput."""

    def __init__(self, metric_spec, run_name: str = "iter_001"):
        self.metric_spec = metric_spec
        self.run_name = run_name


TIDMAD_ID = (TIDMAD.id, "higher")
DAVIS_ID = (DAVIS.id, "lower")


class TestTheResumeIdentityMatrix:
    """All four §4.2 cases, asserted on WHICH records survive to be ranked."""

    def test_case_A_all_known_and_compatible_ranks_normally(self):
        records = [
            _rec("a", -3.2, identity=TIDMAD_ID),
            _rec("b", -1.4, identity=TIDMAD_ID),
        ]
        rankable, order = _rankable_pool(records, _Parsed(TIDMAD), context="formal")
        assert len(rankable) == 2
        assert order is not None
        best = _pick_best(rankable, order=order)
        assert best is not None and best["exp_id"] == "b"

    def test_case_B_known_plus_missing_ranks_the_known_SUBSET(self, capsys):
        """One legacy row must not poison a compatible corpus.

        The missing row is excluded INDIVIDUALLY and — critically — its score
        does not influence the winner, even though it is numerically the best.
        """
        records = [
            _rec("a", -3.2, identity=TIDMAD_ID),
            _rec("legacy", -0.1, identity=None),
            _rec("c", -1.4, identity=TIDMAD_ID),
        ]
        rankable, order = _rankable_pool(records, _Parsed(TIDMAD), context="formal")
        assert [r["exp_id"] for r in rankable] == ["a", "c"]
        assert order is not None
        best = _pick_best(rankable, order=order)
        assert best is not None and best["exp_id"] == "c", (
            "the identity-less row won despite never being rankable"
        )
        assert METRIC_IDENTITY_UNAVAILABLE in capsys.readouterr().out

    def test_case_C_all_missing_yields_no_rankable_pool(self, capsys):
        records = [_rec("a", -3.2, identity=None), _rec("b", -1.4, identity=None)]
        rankable, order = _rankable_pool(records, _Parsed(TIDMAD), context="formal")
        assert rankable == []
        assert order is None
        assert METRIC_IDENTITY_UNAVAILABLE in capsys.readouterr().out

    def test_case_D_conflicting_KNOWN_identities_FAIL_CLOSED(self):
        records = [
            _rec("a", -3.2, identity=TIDMAD_ID),
            _rec("b", 0.017, identity=DAVIS_ID),
        ]
        with pytest.raises(MetricIdentityConflictError):
            _rankable_pool(records, _Parsed(TIDMAD), context="formal")

    def test_a_record_conflicting_with_the_RUN_stamp_fails_closed(self):
        """The bound-vs-stamp row of the truth table, at record granularity."""
        records = [_rec("a", 0.017, identity=DAVIS_ID)]
        with pytest.raises(MetricIdentityConflictError):
            _rankable_pool(records, _Parsed(TIDMAD), context="formal")

    def test_records_agreeing_but_output_unstamped_is_a_named_refusal(self, capsys):
        """Parent §8: an absent spec is a NAMED refusal, never a re-derivation.

        The records agree on an identity, but nothing carries the declaration
        the order would be built from, and P2a may not synthesise one.
        """
        records = [_rec("a", -3.2, identity=TIDMAD_ID)]
        rankable, order = _rankable_pool(records, _Parsed(None), context="formal")
        assert rankable == []
        assert order is None
        assert METRIC_IDENTITY_UNAVAILABLE in capsys.readouterr().out

    def test_the_order_comes_from_the_run_spec_direction(self):
        records = [_rec("a", 0.017, identity=DAVIS_ID)]
        _, order = _rankable_pool(records, _Parsed(DAVIS), context="formal")
        assert order is not None and order.direction == "lower"


class TestRecordIdentityProjection:
    """``metric_identity_from_record`` reads only what Step 06 persisted."""

    def test_a_scored_record_yields_its_persisted_pair(self):
        got = metric_identity_from_record(_rec("a", -1.0, identity=TIDMAD_ID))
        assert got == MetricIdentityKey(id=TIDMAD.id, direction="higher")

    def test_a_record_without_metric_result_is_a_named_absence(self):
        assert metric_identity_from_record(_rec("a", -1.0, identity=None)) is None

    def test_a_malformed_direction_is_an_absence_not_a_guess(self):
        """An unknown direction must never resolve to a default."""
        record = {"exp_id": "a", "metric_result": {"metric_id": "m", "direction": "sideways"}}
        assert metric_identity_from_record(record) is None

    def test_a_missing_metric_id_is_an_absence(self):
        record = {"exp_id": "a", "metric_result": {"direction": "higher"}}
        assert metric_identity_from_record(record) is None

    def test_identity_is_never_inferred_from_the_score_sign(self):
        """A negative score must not imply anything about direction."""
        assert metric_identity_from_record({"exp_id": "a", "denoising_score": -9.9}) is None
        assert metric_identity_from_record({"exp_id": "b", "denoising_score": 9.9}) is None


class TestTheChainFoldOrder:
    """Deviation D-P2a-1 — the two sites the C0 scanner found."""

    def test_a_stamped_output_yields_its_declared_direction(self):
        order = _chain_fold_order(_Parsed(DAVIS))
        assert order is not None and order.direction == "lower"

    def test_an_unstamped_output_refuses_by_name(self, capsys):
        assert _chain_fold_order(_Parsed(None)) is None
        assert METRIC_IDENTITY_UNAVAILABLE in capsys.readouterr().out


class TestTheResumePathIsActuallyReached:
    """Reachability: the production walk must go THROUGH the new boundary.

    Without this, a future edit could restore a raw comparison in
    ``_candidates_from_persisted_verdicts`` and every test above would still
    pass, because they all call the helpers directly.
    """

    def test_candidates_from_persisted_verdicts_consults_the_rankable_pool(self, monkeypatch):
        import core.resume as resume

        seen: list[str] = []
        real = resume._rankable_pool

        def spy(records, parsed, *, context):
            seen.append(context)
            return real(records, parsed, context=context)

        monkeypatch.setattr(resume, "_rankable_pool", spy)

        parsed = _Parsed(TIDMAD)
        parsed.all_records = [  # type: ignore[attr-defined]
            {**_rec("a", -3.2, identity=TIDMAD_ID), "is_trial": False, "status": "success"}
        ]
        monkeypatch.setattr(
            resume, "_classify_commit_time", lambda *a, **k: resume.CandidateHealthValidity.VALID
        )
        monkeypatch.setattr(resume, "_round_provenance", lambda rec: (1, "persisted"))

        resume._candidates_from_persisted_verdicts(parsed, frozenset(), want_trial=False)
        assert seen == ["formal"], "the persisted-verdicts path bypassed the identity boundary"


# ---------------------------------------------------------------------------
# Site 5 — _row_beats, and the §4.3 monotonicity ruling
# ---------------------------------------------------------------------------


class TestRowBeatsIsDirectionAware:
    def test_every_c0_probe_is_byte_equal_under_higher(self):
        """Backward parity, tie class by tie class."""
        mismatches = [
            name
            for name, new, cur, want in ROW_BEATS_PROBES
            if _row_beats(new, cur, order=HIGHER) is not want
        ]
        assert not mismatches, f"a tie rule changed during the migration: {mismatches}"

    def test_the_seven_tie_probes_are_IDENTICAL_under_lower(self):
        """Tie rules are direction-independent; only the two score probes move."""
        for name, new, cur, want in ROW_BEATS_PROBES:
            if new.best_linear == cur.best_linear:
                assert _row_beats(new, cur, order=LOWER) is want, (
                    f"the direction-independent tie rule {name!r} moved under `lower`"
                )

    def test_the_two_score_probes_INVERT_under_lower(self):
        score_probes = [
            (name, new, cur, want)
            for name, new, cur, want in ROW_BEATS_PROBES
            if new.best_linear != cur.best_linear
        ]
        assert len(score_probes) == 2
        for name, new, cur, want in score_probes:
            assert _row_beats(new, cur, order=LOWER) is (not want), (
                f"the score comparison {name!r} did not follow the metric direction"
            )

    def test_under_lower_the_smaller_linear_value_wins(self):
        assert _row_beats(_row(best_linear=4.0), _row(best_linear=9.0), order=LOWER) is True
        assert _row_beats(_row(best_linear=9.0), _row(best_linear=4.0), order=LOWER) is False


class TestTheCurrentTransformIsMonotone:
    """§4.3 — a TIDMAD FACT about the CURRENT transform, not a generic contract.

    ``best_linear`` holds the persisted ``file_vector`` values and
    ``best_log_score`` is the derived display. Ranking in linear space is only
    equivalent to ranking in log space because ``_log`` is strictly increasing,
    which is true because ``LOG_BASE`` > 1. These tests pin THAT, and nothing
    wider: P2a claims no generic capability to assert an arbitrary future
    transform's monotonicity, and pretending otherwise would be a fake guard.
    """

    def test_the_log_base_is_greater_than_one(self):
        """The whole equivalence rests on this single hand-checked fact."""
        assert LOG_BASE == 5.27
        assert LOG_BASE > 1.0

    def test_linear_order_equals_log_order_on_tidmad_shaped_values(self):
        """Hand-computed: log base 5.27 is strictly increasing, so the ranking
        is the same in both spaces."""
        linear = [0.5, 1.0, 2.0, 5.27, 27.7729, 100.0]
        logged = [_log(value) for value in linear]
        assert logged == sorted(logged), "the transform is not increasing on this range"
        assert sorted(linear) == linear
        # spot-check two exact points rather than trusting the sweep alone
        assert _log(1.0) == 0.0
        assert _log(LOG_BASE) == pytest.approx(1.0)

    def test_the_pairwise_equivalence_holds_for_every_pair(self):
        linear = [0.25, 0.9, 1.0, 3.3, 5.27, 41.0]
        for a in linear:
            for b in linear:
                assert (a > b) == (_log(a) > _log(b)), (
                    f"linear and log ranking disagree for {a} vs {b}"
                )

    def test_a_hypothetical_base_below_one_would_INVERT(self):
        """States the boundary the guard actually depends on.

        Not a test of production — a demonstration that the equivalence is a
        property of THIS base and would genuinely break for another, which is
        why §4.3 records a future non-monotone transform as a named capability
        requirement rather than something guarded here.
        """
        import math

        inverted = lambda x: math.log(x) / math.log(0.5)  # noqa: E731
        assert (2.0 > 1.0) != (inverted(2.0) > inverted(1.0))
