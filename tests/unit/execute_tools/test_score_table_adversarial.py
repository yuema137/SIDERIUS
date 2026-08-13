"""
Adversarial probes for ``execute_tools.scoring_helpers`` +
``agent.schemas.score_table`` — promoted from the throwaway
``/tmp/adversarial_score_table.py`` script that ran in the pre-Phase-5
audit.

Covers three fronts:

  1. Schema validator robustness against LLM-style junk values
     (``"n/a"``, ``"-"``, ``"N/A"``, ``""``, wrong types, bounds).
  2. ``build_score_table`` subset edge cases (all-None fv, single file,
     all-negative scores, wrong fv length).
  3. The **below-baseline relabel guard** in ``render_comparison_table``:
     when ``model_scalar < raw_baseline_scalar`` the markdown must NOT
     quote a negative "% of ceiling" — it must carry the honest
     ``Recovery: < 0% (Model performance is below raw baseline).`` line.

The probes intentionally do not exercise the legacy path — they target
inputs that an LLM or a brittle upstream consumer could realistically
produce.
"""

from __future__ import annotations

import math
from typing import Optional

import pytest
from pydantic import ValidationError

from agent.schemas.score_table import (
    AggregateScalars,
    PerFileRow,
    ScoreComparisonTable,
)
from execute_tools.scoring_helpers import (
    _LOG_BASE,
    build_score_table,
    render_comparison_table,
)
from nodes.scoring_reference import ReferenceScores

# -----------------------------------------------------------------------------
# Reference bundle helper — mirror of the one in test_scoring_helpers.py so
# these two files stay independently runnable (per the "each module testable
# individually" CLAUDE.md rule).
# -----------------------------------------------------------------------------


def _make_reference(
    *,
    raw_linear_sum: list[float] | None = None,
    gt_linear_sum: list[float] | None = None,
    n_segments: int = 200,
    s_max: float = 295_715_680.14,
) -> ReferenceScores:
    raw_linear_sum = raw_linear_sum or [2.0] * 20
    gt_linear_sum = gt_linear_sum or [20.0] * 20

    def _log_or_neg_inf(x: float) -> float:
        if x > 0 and math.isfinite(x):
            return math.log(x, _LOG_BASE)
        return float("-inf")

    raw_per_file_log = [_log_or_neg_inf(ls / n_segments) for ls in raw_linear_sum]
    gt_per_file_log = [_log_or_neg_inf(ls / n_segments) for ls in gt_linear_sum]
    raw_gm = sum(raw_linear_sum) / (n_segments * 20)
    gt_gm = sum(gt_linear_sum) / (n_segments * 20)
    raw_scalar_full = _log_or_neg_inf(raw_gm)
    gt_scalar_full = _log_or_neg_inf(gt_gm)
    return ReferenceScores(
        raw_per_file_log=raw_per_file_log,
        gt_per_file_log=gt_per_file_log,
        raw_per_file_linear_sum=list(raw_linear_sum),
        raw_per_file_n_segments=[n_segments] * 20,
        gt_per_file_linear_sum=list(gt_linear_sum),
        gt_per_file_n_segments=[n_segments] * 20,
        raw_scalar_full=raw_scalar_full,
        gt_scalar_full=gt_scalar_full,
        s_max=s_max,
    )


def _good_row_kwargs(**overrides) -> dict:
    base = dict(
        file_index=0,
        raw_baseline=0.1,
        ground_truth=100.0,
        model=5.5,
        gain_vs_raw=5.4,
        headroom_vs_gt=94.5,
    )
    base.update(overrides)
    return base


def _good_table_dict(fv: list[float | None]) -> dict:
    rows = [
        dict(
            file_index=i,
            raw_baseline=0.1,
            ground_truth=100.0,
            model=v,
            gain_vs_raw=None,
            headroom_vs_gt=None,
        )
        for i, v in enumerate(fv)
    ]
    return dict(
        rows=rows,
        aggregate=dict(
            raw_baseline_scalar=0.1,
            ground_truth_scalar=100.0,
            model_scalar=5.0,
            percent_of_ceiling_log=0.05,
            num_sampled_files=20,
        ),
        s_max_global=1.0,
        reference_source="adversarial_probe",
        rendered_markdown="| test |",
    )


# =============================================================================
# 1. Schema robustness — LLM-style junk values on PerFileRow.model
# =============================================================================


class TestPerFileRowModelValue:
    """The ``model`` field must reject LLM string nulls loudly, but preserve
    the canonical None / NaN / Inf floats for unsampled and failure markers."""

    @pytest.mark.parametrize("bad", ["n/a", "N/A", "-", ""])
    def test_llm_string_null_rejected(self, bad):
        with pytest.raises(ValidationError) as exc_info:
            PerFileRow(**_good_row_kwargs(model=bad))
        err = exc_info.value.errors()[0]
        assert err["loc"] == ("model",)
        assert "number" in err["msg"].lower()

    def test_none_accepted_as_unsampled_marker(self):
        row = PerFileRow(**_good_row_kwargs(model=None))
        assert row.model is None

    def test_nan_accepted(self):
        row = PerFileRow(**_good_row_kwargs(model=float("nan")))
        assert math.isnan(row.model)

    def test_inf_accepted(self):
        row = PerFileRow(**_good_row_kwargs(model=float("inf")))
        assert math.isinf(row.model)

    def test_list_rejected(self):
        with pytest.raises(ValidationError):
            PerFileRow(**_good_row_kwargs(model=[]))

    def test_file_index_out_of_bounds_rejected(self):
        with pytest.raises(ValidationError):
            PerFileRow(**_good_row_kwargs(file_index=20))

    def test_extra_field_rejected(self):
        # extra="forbid" — guards against silent field drift.
        with pytest.raises(ValidationError):
            PerFileRow(**_good_row_kwargs(), foo=1)


class TestScoreComparisonTableValidation:
    """Validation should reject malformed tables end-to-end when loading
    a serialized dict — this is the path the cache round-trip takes."""

    # PR-02a (OD-02a-1) moved the row-count rule off the static
    # ``min_length``/``max_length`` field constraints, which were evaluated at
    # import against TIDMAD's 20 files and made any other topology
    # unrepresentable, onto a validator resolved from the Dataset Profile.
    # The RULE is unchanged and these two cases still guard it; the
    # assertions now name the diagnostic the validator emits instead of
    # Pydantic's built-in constraint wording.

    def test_rows_below_declared_file_count_rejected(self):
        bad = _good_table_dict([0.1] * 19)
        bad["rows"] = bad["rows"][:19]
        with pytest.raises(ValidationError) as exc_info:
            ScoreComparisonTable.model_validate(bad)
        message = str(exc_info.value)
        assert "exactly one row per validation file" in message
        # Diagnostic: it must name BOTH the count it got and the count it
        # expected, or an operator cannot tell which side is wrong.
        assert "got 19 rows" in message
        assert "20 files" in message

    def test_rows_above_declared_file_count_rejected(self):
        bad = _good_table_dict([0.1] * 20)
        bad["rows"] = bad["rows"] + [bad["rows"][0]]
        with pytest.raises(ValidationError) as exc_info:
            ScoreComparisonTable.model_validate(bad)
        message = str(exc_info.value)
        assert "exactly one row per validation file" in message
        assert "got 21 rows" in message
        assert "20 files" in message

    def test_num_sampled_files_zero_rejected(self):
        # ge=1 — a run with zero sampled files should have returned None
        # from build_score_table, not produced a table.
        bad = _good_table_dict([0.1] * 20)
        bad["aggregate"]["num_sampled_files"] = 0
        with pytest.raises(ValidationError):
            ScoreComparisonTable.model_validate(bad)

    def test_one_n_a_row_fails_whole_table(self):
        bad_fv = [0.1] * 19 + ["n/a"]
        with pytest.raises(ValidationError) as exc_info:
            ScoreComparisonTable.model_validate(_good_table_dict(bad_fv))
        err = exc_info.value.errors()[0]
        assert err["loc"] == ("rows", 19, "model")

    def test_one_none_row_accepted(self):
        fv_with_none = [0.1] * 19 + [None]
        tbl = ScoreComparisonTable.model_validate(_good_table_dict(fv_with_none))
        assert tbl.rows[19].model is None


# =============================================================================
# 2. build_score_table subset edge cases
# =============================================================================


class TestBuildScoreTableEdges:
    def test_none_scalar_returns_none(self):
        # Fully-failed run: no scalar, no table. Graceful skip.
        ref = _make_reference()
        assert build_score_table([None] * 20, model_scalar=None, reference=ref) is None

    def test_non_none_scalar_with_empty_fv_raises(self):
        # score_vector can't produce a scalar from zero inputs — this is an
        # upstream inconsistency and must surface loudly.
        ref = _make_reference()
        with pytest.raises(ValueError) as exc_info:
            build_score_table([None] * 20, model_scalar=5.0, reference=ref)
        assert "all-None" in str(exc_info.value)

    def test_single_file_sample_works(self):
        ref = _make_reference()
        fv = [None] * 20
        fv[7] = 3.0
        tbl = build_score_table(fv, model_scalar=3.0, reference=ref)
        assert tbl is not None
        assert tbl.aggregate.num_sampled_files == 1
        # Only row 7 should have a model value; all others are None.
        assert tbl.rows[7].model == 3.0
        assert all(r.model is None for i, r in enumerate(tbl.rows) if i != 7)

    def test_fv_length_19_raises(self):
        ref = _make_reference()
        with pytest.raises(ValueError) as exc_info:
            build_score_table([0.1] * 19, model_scalar=1.0, reference=ref)
        assert "length 20" in str(exc_info.value)

    def test_fv_length_21_raises(self):
        ref = _make_reference()
        with pytest.raises(ValueError) as exc_info:
            build_score_table([0.1] * 21, model_scalar=1.0, reference=ref)
        assert "length 20" in str(exc_info.value)


# =============================================================================
# 3. Below-baseline relabel guard in render_comparison_table
# =============================================================================


class TestBelowBaselineRelabel:
    """When model_scalar < raw_baseline_scalar, the Recovery line must
    render as the honest "< 0%" one-liner — not as a negative percentage.
    """

    def test_below_baseline_renders_honest_line(self):
        # Default reference: raw_baseline ≈ -2.771, gt ≈ -1.386.
        # model_scalar=-7.5 sits clearly below the raw baseline.
        ref = _make_reference()
        fv = [-7.5] * 20
        tbl = build_score_table(fv, model_scalar=-7.5, reference=ref)
        assert tbl is not None
        assert tbl.aggregate.model_scalar < tbl.aggregate.raw_baseline_scalar

        md = render_comparison_table(tbl)
        assert "Recovery: < 0% (Model performance is below raw baseline)." in md
        # Negative percent line MUST NOT appear — that was the whole bug.
        assert "of ceiling" not in md

    def test_above_baseline_renders_percentage(self):
        # Regression guard: normal positive-model runs keep the % framing.
        ref = _make_reference()
        fv = [2.0] * 20
        tbl = build_score_table(fv, model_scalar=5.5763, reference=ref)
        assert tbl is not None
        md = render_comparison_table(tbl)
        assert "of ceiling" in md
        # The "< 0%" sentinel must not leak into the happy path.
        assert "< 0%" not in md

    def test_equal_to_baseline_renders_percentage(self):
        # Strict "<": exactly-equal stays on the normal branch. Models
        # that merely tie the baseline aren't worse; we keep the ratio.
        ref = _make_reference()
        equal_scalar = ref.raw_scalar_full
        fv = [equal_scalar] * 20
        tbl = build_score_table(fv, model_scalar=equal_scalar, reference=ref)
        assert tbl is not None
        md = render_comparison_table(tbl)
        assert "of ceiling" in md
        assert "< 0%" not in md

    def test_machine_readable_scalars_preserved(self):
        # Only the LLM-facing markdown is sanitized. The Pydantic object
        # must still carry the raw scalars so programmatic consumers see
        # the true model/baseline/ceiling ordering. (The `% ceiling` ratio
        # itself is mathematically useless in this regime — a double-
        # negative can even flip it back to positive, which is exactly
        # why the markdown relabel is needed.)
        ref = _make_reference()
        fv = [-7.5] * 20
        tbl = build_score_table(fv, model_scalar=-7.5, reference=ref)
        assert tbl is not None
        agg = tbl.aggregate
        # The fundamental invariant that triggers the relabel:
        assert agg.model_scalar < agg.raw_baseline_scalar
        # And the scalars themselves are untouched by the render guard.
        assert agg.model_scalar == -7.5
        assert agg.raw_baseline_scalar == ref.raw_scalar_full
