"""
Unit tests for ``compute_ground_truth.py`` — perfect-denoiser ceiling formulas
under the **Option B global-s_max convention**.

The script is a thin CLI wrapper around two pure helpers, both driven by the
global ``s_max`` from ``segment_anchors.json``:

* ``_global_per_file_ceiling`` — per-file log score for one file.
* ``_anchor_normalized_ceiling`` — SIDERIUS grand-mean ceiling across all
  files. Phase 6.7 dropped the legacy ``round(·, 2)`` quantization; the
  ``+ 1e-10`` soft floor was preserved (commit ``8947511``, 2026-05-01),
  giving ``log_{5.27}(1e-10) ≈ -13.854`` as the "no signal" floor instead
  of ``float('-inf')``. The floor is negligible for any value ``≫ 1e-10``
  and only matters on all-zero / near-zero files. See
  ``docs/phase67_infra_hardening_and_feedback_integrity.md`` Fix 4 and
  the production docstring on ``_global_per_file_ceiling``.

These tests drive both helpers on hand-computed inputs so any drift in the
formula (missing/extra round, wrong aggregation, wrong log base, wrong
ruler, dropped floor) fails loudly.
"""

from __future__ import annotations

import math

# Root-level script import — pytest runs from repo root.
from compute_ground_truth import (
    _anchor_normalized_ceiling,
    _global_per_file_ceiling,
)

# =============================================================================
# _global_per_file_ceiling — per-file ceiling under the global s_max ruler
# =============================================================================


class TestGlobalPerFileCeiling:
    def test_hand_computed_scalar(self):
        """Anchors [1, 2, 3, 4], s_max=4:

        per_file_linear = (1² + 2² + 3² + 4²) / (4 · 4) = 30/16 = 1.875
        return            log_{5.27}(1.875 + 1e-10)  (no rounding; +1e-10
                                                     soft floor preserved
                                                     per commit 8947511)
        """
        anchors = [1.0, 2.0, 3.0, 4.0]
        log_score, linear_sum, n = _global_per_file_ceiling(anchors, s_max=4.0)
        expected = math.log(1.875 + 1e-10, 5.27)
        assert abs(log_score - expected) < 1e-12
        # The tuple companion fields preserve full precision for the
        # subset-aware grand-mean aggregator (Decision 13).
        assert abs(linear_sum - 30.0 / 4.0) < 1e-12
        assert n == 4

    def test_all_zero_anchors_returns_soft_floor(self):
        """All-zero anchors → per_file_linear = 0 → ``log(1e-10, 5.27)`` floor.

        Commit ``8947511`` (2026-05-01) restated that the ``+ 1e-10`` soft
        floor is intentionally preserved: zero / near-zero signals resolve
        to ``log_{5.27}(1e-10) ≈ -13.854`` rather than ``float('-inf')``.
        The legacy ``round(·, 2)`` quantization (the actual "ghost score"
        culprit) is the only thing that was dropped. The floor is
        negligible relative to any real linear score. (No div-by-zero path:
        s_max is the GLOBAL max, strictly positive by construction on real
        data.)
        """
        log_score, linear_sum, n = _global_per_file_ceiling([0.0, 0.0, 0.0], s_max=10.0)
        expected = math.log(1e-10, 5.27)
        assert abs(log_score - expected) < 1e-12
        assert linear_sum == 0.0
        assert n == 3

    def test_uses_global_smax_not_local_max(self):
        """Per-file ceiling must divide by the passed-in s_max, NOT by
        max(anchors). Two runs with the same anchors but different s_max
        must differ by ``log_{5.27}((large_lin + 1e-10) / (small_lin + 1e-10))``;
        for inputs far above the 1e-10 floor this collapses to
        ``log_{5.27}(ratio)`` up to ~1e-11 from the floor offset.

        Anchors [2, 4], n=2:
          s_max=4:  per_file_linear = (4+16)/(2·4) = 2.5 → log_{5.27}(2.5 + 1e-10)
          s_max=2:  per_file_linear = (4+16)/(2·2) = 5.0 → log_{5.27}(5.0 + 1e-10)
        Δ = log_{5.27}((5.0 + 1e-10) / (2.5 + 1e-10)) ≈ log_{5.27}(2).
        """
        anchors = [2.0, 4.0]
        log_small, _, _ = _global_per_file_ceiling(anchors, s_max=2.0)  # larger lin
        log_large, _, _ = _global_per_file_ceiling(anchors, s_max=4.0)  # smaller lin

        assert log_small > log_large
        # Match the production formula exactly so the assertion stays
        # bit-tight; the +1e-10 floor shifts the delta by ~1e-11.
        expected_delta = math.log((5.0 + 1e-10) / (2.5 + 1e-10), 5.27)
        assert abs((log_small - log_large) - expected_delta) < 1e-12


# =============================================================================
# _anchor_normalized_ceiling — grand-mean + TIDMAD round (unchanged behaviour)
# =============================================================================


class TestAnchorNormalizedCeiling:
    def test_uniform_files_grand_mean_equals_simple_mean(self):
        """Two files, 2 segments each, s_max = 4.

        f=0 anchors [1, 2]:  file_sum = (1 + 4)/4   = 1.25,
                             file_vector[0] = 1.25/2 = 0.625
        f=1 anchors [3, 4]:  file_sum = (9 + 16)/4  = 6.25,
                             file_vector[1] = 6.25/2 = 3.125
        total_weighted = 7.5, total_count = 4
        grand_mean     = 7.5 / 4 = 1.875
        scalar         = log_{5.27}(1.875 + 1e-10)  (round-2dp dropped;
                                                    +1e-10 soft floor kept)

        Since |S_f|=2 for both files, the grand mean equals mean_f(file_vector).
        """
        anchors = {"0": [1.0, 2.0], "1": [3.0, 4.0]}
        s_max = 4.0
        file_vector, scalar = _anchor_normalized_ceiling(anchors, s_max)

        assert file_vector == [0.625, 3.125]
        expected_scalar = math.log(1.875 + 1e-10, 5.27)
        assert abs(scalar - expected_scalar) < 1e-12

        # Cross-check: under uniform |S_f|, grand mean == simple mean.
        simple_mean = sum(file_vector) / len(file_vector)
        assert abs(simple_mean - 1.875) < 1e-12

    def test_nonuniform_files_grand_mean_differs_from_simple_mean(self):
        """Non-uniform |S_f| is the case where the grand mean matters.

        f=0 anchors [10] (|S|=1):  file_sum = 100/10 = 10.0,
                                   file_vector[0] = 10.0/1 = 10.0
        f=1 anchors [1, 1, 1, 1] (|S|=4):
                                   file_sum = 4/10 = 0.4,
                                   file_vector[1] = 0.4/4 = 0.1
        total_weighted = 10.4, total_count = 5
        grand_mean     = 10.4 / 5 = 2.08
        simple_mean    = (10.0 + 0.1) / 2 = 5.05   ← would be legacy-INCOMPATIBLE
        scalar         = log_{5.27}(2.08 + 1e-10)  (round-2dp dropped;
                                                   +1e-10 soft floor kept)
        """
        anchors = {"0": [10.0], "1": [1.0, 1.0, 1.0, 1.0]}
        s_max = 10.0
        file_vector, scalar = _anchor_normalized_ceiling(anchors, s_max)

        assert file_vector == [10.0, 0.1]
        expected_scalar = math.log(2.08 + 1e-10, 5.27)
        assert abs(scalar - expected_scalar) < 1e-12

    def test_weak_signal_is_not_collapsed_to_ghost_score(self):
        """Phase 6.7 ghost-score-killer regression guard.

        Under the legacy formula, ``grand_mean = 0.0009`` would collapse to
        ``log_{5.27}(round(0.0009, 2) + 1e-10) = log_{5.27}(1e-10) ≈ -13.854``,
        and any grand_mean in ``[0.005, 0.0149]`` would all be quantized to
        ``log_{5.27}(0.01 + 1e-10) ≈ -2.7708098959837675`` — the same ghost
        score, regardless of true signal strength.

        Post Phase 6.7 + commit ``8947511`` we take
        ``log_{5.27}(grand_mean + 1e-10)`` (no rounding, soft floor only),
        so weak signals get distinct, monotone scores. ``grand_mean = 0.0009``
        gives ``log_{5.27}(0.0009 + 1e-10) ≈ -4.219`` (NOT the ghost score;
        the floor's contribution is negligible at this magnitude).
        """
        anchors = {"0": [0.03]}
        s_max = 1.0
        _, scalar = _anchor_normalized_ceiling(anchors, s_max)

        # No round-2dp quantization; +1e-10 soft floor included.
        expected = math.log(0.0009 + 1e-10, 5.27)
        assert abs(scalar - expected) < 1e-12

        # The ghost-score collapse must NOT happen.
        ghost = -2.7708098959837675
        assert abs(scalar - ghost) > 0.5

    def test_log_base_is_5_27(self):
        """Sanity: the log base is the TIDMAD constant 5.27, not e or 10."""
        # Construct anchors s.t. grand_mean is exactly 2.0.
        anchors = {"0": [math.sqrt(2.0)]}
        s_max = 1.0
        _, scalar = _anchor_normalized_ceiling(anchors, s_max)

        # grand_mean = 2.0 / 1 = 2.0; +1e-10 soft floor preserved.
        expected = math.log(2.0 + 1e-10, 5.27)
        assert abs(scalar - expected) < 1e-12
        # Sanity guards against accidental base swaps:
        assert abs(scalar - math.log(2.0)) > 1e-3  # not ln
        assert abs(scalar - math.log10(2.0)) > 1e-3  # not log10


# =============================================================================
# Cross-consistency — per-file and scalar paths agree on uniform |S_f|.
# =============================================================================


class TestCrossConsistency:
    def test_per_file_agrees_with_file_vector(self):
        """Under the Option B global-s_max convention, the per-file log score
        is ``log_{5.27}(file_vector[f] + 1e-10)``. Phase 6.7 dropped the
        ``round(·, 2)`` quantization (the actual ghost-score culprit); the
        ``+ 1e-10`` soft floor was preserved (commit ``8947511``) and must
        be applied identically on both sides for the bit-tight equivalence
        to hold.
        """
        anchors = {"0": [2.0, 4.0], "1": [1.0, 3.0]}
        s_max = 2.0

        file_vector, _ = _anchor_normalized_ceiling(anchors, s_max)

        for f_str, fv in zip(sorted(anchors, key=int), file_vector, strict=True):
            direct_log, _, _ = _global_per_file_ceiling(anchors[f_str], s_max)
            via_fv = math.log(fv + 1e-10, 5.27)
            assert abs(direct_log - via_fv) < 1e-12
