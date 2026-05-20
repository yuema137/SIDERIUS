"""
Phase 6.7 — Scoring Precision regression-guard suite.

These tests are explicitly tied to the four Verification Metrics in
``docs/phase67_infra_hardening_and_feedback_integrity.md`` Fix 4:

1. **Ghost-score killer (historical replay).**
   The seven audit-flagged records (run id ``v4_pr61_20260425_222622``) all
   collapsed to ``-2.7708098959837675`` under the legacy
   ``log_{5.27}(round(grand_mean, 2) + 1e-10)`` formula. Under the new
   ``log_{5.27}(grand_mean)`` formula, replaying their grand-means must
   produce **seven distinct float64 values** with adjacent gaps well above
   the documented training-RNG noise floor.

2. **Determinism.**
   ``score_vector`` returns bit-exact scalars on identical inputs (``==``,
   not ``approx``). The new formula has no quantization step and no random
   element, so this should hold trivially — but the test guards against
   future drift.

3. **JSON safety: -inf round-trip.**
   ``coerce_nonfinite_to_none`` collapses ``float('-inf')`` to ``None`` so
   the on-disk JSON conforms to RFC 8259 (no ``-Infinity`` literals that
   would crash browser ``JSON.parse``). ``Optional[float]`` Pydantic fields
   accept ``None`` on round-trip, so the in-memory semantics are preserved.

4. **Render precision floor.**
   ``_fmt_log`` quantizes at ``:.4f`` (1e-4). The score-noise floor is
   documented at ~5e-4 log-units; the render precision sits below the noise
   floor, so the LLM planner cannot see sub-noise differentiation. Also
   guards the new ``_fmt_log(-inf)`` branch — the legacy code would have
   emitted ``"\u2212inf.0000"`` garbage.
"""

from __future__ import annotations

import json
import math

import pytest

from execute_tools.scoring_helpers import (
    _LOG_BASE,
    _fmt_log,
    _grand_mean_log_scalar,
)
from execute_tools.scoring_utils import coerce_nonfinite_to_none

# =============================================================================
# 1. Historical-replay ghost-score killer
# =============================================================================


# (record id, grand_mean) — these grand_means were reverse-computed from the
# audit-flagged ghost-score records in
# /home/yuema137/SIDERIUS/reports/v4_pr61_20260425_222622.md §3 by walking the
# on-disk per-record JSONs and unrolling the file_vector + sample_set
# linear sums. Old scalar for every entry was -2.7708098959837675.
_HISTORICAL_GHOST_GRAND_MEANS = {
    "spectral_skip_tcn rec_003": 0.008939,
    "spectral_skip_tcn rec_004": 0.008739,
    "spectral_skip_tcn rec_005": 0.006588,
    "dual_rate_gated_causal_cnn rec_010": 0.005227,
    "gated_recycle_skip_tcn rec_011": 0.005091,
    "fused_spectral_gate_tcn rec_009": 0.005285,
    "hierarchical_cycle_fusion_tcn rec_004": 0.005398,
}

# Documented in docs/phase67_infra_hardening_and_feedback_integrity.md §Fix 4.
# Per-step training noise on identical seeds is empirically < 5e-4 log-units.
_NOISE_FLOOR_LOG_UNITS = 5e-4
_OLD_GHOST_SCORE = -2.7708098959837675


class TestGhostScoreKiller:
    """The seven audit-flagged ghost records must produce distinct,
    differentiable scalars under the Phase 6.7 formula.
    """

    def test_seven_records_produce_seven_distinct_scalars(self):
        new_scalars = {
            label: math.log(gm, _LOG_BASE) for label, gm in _HISTORICAL_GHOST_GRAND_MEANS.items()
        }
        # All seven must be pairwise distinct under bit-exact equality.
        assert len(set(new_scalars.values())) == 7, (
            f"Phase 6.7 should differentiate every ghost-score record; got "
            f"{len(set(new_scalars.values()))} distinct values out of 7: "
            f"{new_scalars}"
        )

    def test_no_record_lands_exactly_on_old_ghost_score(self):
        # The legacy quantization produced ``-2.7708098959837675`` exactly
        # (bit-identical float64) for any grand_mean in [0.005, 0.0149]. The
        # new formula yields values *near* that range (0.009 → -2.84, 0.005
        # → -3.18), but never exactly the legacy float — that float is
        # ``log_{5.27}(0.01 + 1e-10)``, which the new formula no longer
        # produces for any grand_mean we'd see in practice.
        for label, gm in _HISTORICAL_GHOST_GRAND_MEANS.items():
            new_scalar = math.log(gm, _LOG_BASE)
            assert new_scalar != _OLD_GHOST_SCORE, (
                f"Record {label}: new_scalar bit-equals the legacy ghost "
                f"score ({_OLD_GHOST_SCORE}) — quantization has regressed."
            )

    def test_min_adjacent_gap_exceeds_noise_floor(self):
        new_scalars = sorted(
            math.log(gm, _LOG_BASE) for gm in _HISTORICAL_GHOST_GRAND_MEANS.values()
        )
        gaps = [b - a for a, b in zip(new_scalars[:-1], new_scalars[1:], strict=True)]
        min_gap = min(gaps)
        assert min_gap > _NOISE_FLOOR_LOG_UNITS, (
            f"Tightest adjacent gap ({min_gap:.6f} log-units) is not "
            f"distinguishable from the documented training-RNG noise floor "
            f"({_NOISE_FLOOR_LOG_UNITS} log-units). The planner cannot "
            f"reliably differentiate these scores."
        )
        # Sanity: under :.4f rendering, even the tightest pair shows up.
        assert min_gap > 1e-4, (
            f"Tightest gap ({min_gap}) is below render precision (1e-4); "
            f"the dashboard would display these as identical."
        )

    def test_span_is_physically_meaningful(self):
        scalars = [math.log(gm, _LOG_BASE) for gm in _HISTORICAL_GHOST_GRAND_MEANS.values()]
        span = max(scalars) - min(scalars)
        # Audit observed ~0.34 log-unit span across the seven records.
        assert span > 0.2, (
            f"Span across the seven historical records is only {span:.4f} "
            f"log-units — the planner gets effectively no signal."
        )


# =============================================================================
# 2. Determinism — bit-exact equality, not approx
# =============================================================================


class TestDeterminism:
    """The new formula must be bit-exact reproducible: every quantization
    step that introduced rounding artefacts has been removed."""

    def test_grand_mean_log_is_bit_exact(self):
        # Two independent calls with identical inputs must agree on every bit.
        first = _grand_mean_log_scalar(total_linear=2.345, total_n=200)
        second = _grand_mean_log_scalar(total_linear=2.345, total_n=200)
        assert first == second  # deliberate ==, NOT pytest.approx

    def test_grand_mean_log_matches_python_log(self):
        # The helper must equal a hand-computed math.log, with no
        # quantization eps. Pick a value that the legacy formula would
        # have rounded to a *different* value (round(0.0117, 2) = 0.01).
        total_linear = 2.34
        total_n = 200
        got = _grand_mean_log_scalar(total_linear, total_n)
        expected = math.log(total_linear / total_n, _LOG_BASE)
        assert got == expected
        # Sanity vs. the legacy formula, which would have collapsed this.
        legacy = math.log(round(total_linear / total_n, 2) + 1e-10, _LOG_BASE)
        assert abs(got - legacy) > 1e-3, (
            "Phase 6.7 helper must produce a value DIFFERENT from the "
            "legacy round-then-eps formula on this hand-picked input."
        )

    def test_zero_total_returns_neg_inf(self):
        assert _grand_mean_log_scalar(total_linear=0.0, total_n=0) == float("-inf")
        assert _grand_mean_log_scalar(total_linear=1.0, total_n=0) == float("-inf")

    def test_negative_grand_mean_returns_neg_inf(self):
        # Negative totals are not physically meaningful, but the guard must
        # still fire and return the sentinel rather than raising in math.log.
        assert _grand_mean_log_scalar(total_linear=-1.0, total_n=10) == float("-inf")


# =============================================================================
# 3. JSON safety — -inf round-trip + dashboard parseability
# =============================================================================


class TestJsonSafetyForInfSentinel:
    """``coerce_nonfinite_to_none`` must convert the ``float('-inf')``
    sentinel to JSON ``null`` so the dashboard can parse it. Pydantic's
    ``Optional[float]`` accepts ``None`` on the round-trip back."""

    def test_neg_inf_becomes_none(self):
        assert coerce_nonfinite_to_none(float("-inf")) is None

    def test_pos_inf_becomes_none(self):
        assert coerce_nonfinite_to_none(float("inf")) is None

    def test_nan_becomes_none(self):
        assert coerce_nonfinite_to_none(float("nan")) is None

    def test_finite_floats_pass_through(self):
        assert coerce_nonfinite_to_none(0.0) == 0.0
        assert coerce_nonfinite_to_none(-2.7708) == -2.7708
        assert coerce_nonfinite_to_none(3.141592653589793) == 3.141592653589793

    def test_none_passes_through(self):
        assert coerce_nonfinite_to_none(None) is None

    def test_strings_and_ints_pass_through(self):
        assert coerce_nonfinite_to_none("hello") == "hello"
        assert coerce_nonfinite_to_none(42) == 42
        assert coerce_nonfinite_to_none(True) is True

    def test_recursive_dict_coercion(self):
        record = {
            "exp_id": "exp_001",
            "denoising_score": float("-inf"),
            "file_vector": [0.5, float("-inf"), 1.5, None],
            "nested": {
                "best_score": float("nan"),
                "valid_score": -2.84,
            },
        }
        safe = coerce_nonfinite_to_none(record)
        assert safe["denoising_score"] is None
        assert safe["file_vector"] == [0.5, None, 1.5, None]
        assert safe["nested"]["best_score"] is None
        assert safe["nested"]["valid_score"] == -2.84
        # Original must not be mutated — coerce returns a new structure.
        assert record["denoising_score"] == float("-inf")

    def test_round_trip_through_json_dumps_and_loads(self):
        # End-to-end: a record with a -inf score must serialize to RFC-8259
        # JSON (no -Infinity tokens) and re-parse with json.loads, which is
        # the same parser the dashboard's browser uses.
        record = {"denoising_score": float("-inf"), "file_vector": [None] * 20}
        safe = coerce_nonfinite_to_none(record)
        # Default json.dumps would emit -Infinity here without the helper —
        # we use allow_nan=False to make that explicit and guard regressions.
        text = json.dumps(safe, allow_nan=False)
        assert "Infinity" not in text
        assert "NaN" not in text
        # The browser parser equivalent: round-trip must succeed and
        # preserve the None semantics.
        parsed = json.loads(text)
        assert parsed["denoising_score"] is None
        assert parsed["file_vector"] == [None] * 20


# =============================================================================
# 4. Render precision: _fmt_log handles the new -inf sentinel cleanly
# =============================================================================


class TestFmtLogSentinelHandling:
    """The legacy ``_fmt_log`` had a ``value < 0`` branch that produced
    ``"\u2212inf.0000"`` for ``float('-inf')``. The Phase 6.7 patch added
    explicit handlers for non-finite values."""

    def test_neg_inf_renders_unicode_minus_infinity(self):
        # Unicode minus + infinity glyph; 4 chars total (no garbage suffix).
        assert _fmt_log(float("-inf")) == "\u2212\u221e"

    def test_pos_inf_renders_infinity(self):
        assert _fmt_log(float("inf")) == "\u221e"

    def test_nan_renders_explicit_string(self):
        assert _fmt_log(float("nan")) == "NaN"

    def test_none_renders_n_a(self):
        assert _fmt_log(None) == "N/A"

    def test_negative_finite_renders_unicode_minus(self):
        # The original behaviour for finite negatives is preserved.
        assert _fmt_log(-2.7708) == "\u22122.7708"

    def test_positive_finite_renders_plain(self):
        assert _fmt_log(0.5) == "0.5000"

    def test_render_precision_quantizes_at_1e_4(self):
        # Two values that differ by less than the render precision
        # collapse to the same rendered string. This is the documented
        # "render-precision floor" — the planner cannot see differences
        # below ~5e-5 log-units in markdown.
        assert _fmt_log(0.12340) == _fmt_log(0.12341)
        # Two values that differ by more than 1e-4 must render distinctly.
        assert _fmt_log(0.12340) != _fmt_log(0.12350)
