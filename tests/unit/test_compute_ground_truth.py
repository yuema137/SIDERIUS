"""
Unit tests for ``compute_ground_truth.py`` — perfect-denoiser ceiling formulas
under the **Option B global-s_max convention**.

The script is a thin CLI wrapper around two pure helpers, both driven by the
global ``s_max`` from ``segment_anchors.json``:

* ``_global_per_file_ceiling`` — per-file log score for one file.
* ``_anchor_normalized_ceiling`` — SIDERIUS grand-mean ceiling across all
  files, with the TIDMAD ``round(·, 2) + 1e-10`` step applied before
  ``log_{5.27}`` (see ``docs/align_denoising_score.md`` §C).

These tests drive both helpers on hand-computed inputs so any drift in the
formula (missing round, wrong aggregation, wrong log base, wrong ruler)
fails loudly.
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
        score_lin       = round(1.875, 2) + 1e-10 = 1.88 + 1e-10
        return            log_{5.27}(1.88 + 1e-10)
        """
        anchors = [1.0, 2.0, 3.0, 4.0]
        got = _global_per_file_ceiling(anchors, s_max=4.0)
        expected = math.log(1.88 + 1e-10, 5.27)
        assert abs(got - expected) < 1e-12

    def test_all_zero_anchors_clips_to_log_of_eps(self):
        """All-zero anchors → per_file_linear=0 → round(0, 2) + 1e-10 = 1e-10
        → log_{5.27}(1e-10). (No div-by-zero path: s_max is the GLOBAL max, by
        construction strictly positive on real data.)"""
        got = _global_per_file_ceiling([0.0, 0.0, 0.0], s_max=10.0)
        expected = math.log(1e-10, 5.27)
        assert abs(got - expected) < 1e-12

    def test_uses_global_smax_not_local_max(self):
        """Per-file ceiling must divide by the passed-in s_max, NOT by
        max(anchors). Two runs with the same anchors but different s_max must
        differ by log_{5.27}(ratio) (when ratio keeps both values on the same
        side of the TIDMAD round).

        Anchors [2, 4], n=2:
          s_max=4:  per_file_linear = (4+16)/(2·4)  = 2.5 → round=2.5 → log(2.5)
          s_max=2:  per_file_linear = (4+16)/(2·2)  = 5.0 → round=5.0 → log(5.0)
        Δ = log_{5.27}(5.0 / 2.5) = log_{5.27}(2).
        """
        anchors = [2.0, 4.0]
        got_small = _global_per_file_ceiling(anchors, s_max=2.0)  # larger lin
        got_large = _global_per_file_ceiling(anchors, s_max=4.0)  # smaller lin

        assert got_small > got_large
        expected_delta = math.log(2.0, 5.27)
        # Delta is not exactly log_{5.27}(2) because of the +1e-10 offset
        # inside each log; 1e-9 tolerance is plenty for double precision.
        assert abs((got_small - got_large) - expected_delta) < 1e-9


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
        scalar         = log_{5.27}(round(1.875, 2) + 1e-10) = log_{5.27}(1.88 + 1e-10)

        Since |S_f|=2 for both files, the grand mean equals mean_f(file_vector).
        """
        anchors = {"0": [1.0, 2.0], "1": [3.0, 4.0]}
        s_max = 4.0
        file_vector, scalar = _anchor_normalized_ceiling(anchors, s_max)

        assert file_vector == [0.625, 3.125]
        expected_scalar = math.log(1.88 + 1e-10, 5.27)
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
        scalar         = log_{5.27}(round(2.08, 2) + 1e-10) = log_{5.27}(2.08 + 1e-10)
        """
        anchors = {"0": [10.0], "1": [1.0, 1.0, 1.0, 1.0]}
        s_max = 10.0
        file_vector, scalar = _anchor_normalized_ceiling(anchors, s_max)

        assert file_vector == [10.0, 0.1]
        expected_scalar = math.log(2.08 + 1e-10, 5.27)
        assert abs(scalar - expected_scalar) < 1e-12

    def test_tidmad_round_is_applied(self):
        """Grand mean that round-to-2dp collapses to 0 → scalar = log(1e-10).

        Single file with anchor=0.03, s_max=1:
            file_sum    = 0.0009
            grand_mean  = 0.0009
            round(0.0009, 2) = 0.0
            score_lin   = 0 + 1e-10 = 1e-10
            scalar      = log_{5.27}(1e-10)
        """
        anchors = {"0": [0.03]}
        s_max = 1.0
        _, scalar = _anchor_normalized_ceiling(anchors, s_max)

        expected = math.log(1e-10, 5.27)
        assert abs(scalar - expected) < 1e-12

    def test_log_base_is_5_27(self):
        """Sanity: the log base is the TIDMAD constant 5.27, not e or 10."""
        # Construct anchors s.t. grand_mean rounds to exactly 2.0.
        anchors = {"0": [math.sqrt(2.0)]}
        s_max = 1.0
        _, scalar = _anchor_normalized_ceiling(anchors, s_max)

        # grand_mean = 2.0 / 1 = 2.0; round(2.0, 2) = 2.0
        expected = math.log(2.0 + 1e-10, 5.27)
        assert abs(scalar - expected) < 1e-12
        # Sanity guards against accidental base swaps:
        assert abs(scalar - math.log(2.0 + 1e-10)) > 1e-3     # not ln
        assert abs(scalar - math.log10(2.0 + 1e-10)) > 1e-3   # not log10


# =============================================================================
# Cross-consistency — per-file and scalar paths agree on uniform |S_f|.
# =============================================================================


class TestCrossConsistency:

    def test_per_file_agrees_with_file_vector_under_tidmad_round(self):
        """Under the Option B global-s_max convention, the per-file log score
        is ``log_{5.27}(round(file_vector[f], 2) + 1e-10)``. When all files
        have the same segment count, this is exactly what the grand-mean
        helper stores in ``file_vector`` before aggregation.

        Picks values that survive the TIDMAD round cleanly.
        """
        anchors = {"0": [2.0, 4.0], "1": [1.0, 3.0]}
        s_max = 2.0

        file_vector, _ = _anchor_normalized_ceiling(anchors, s_max)

        # Apply the TIDMAD round + log that _global_per_file_ceiling applies.
        for f_str, fv in zip(sorted(anchors, key=int), file_vector):
            direct = _global_per_file_ceiling(anchors[f_str], s_max)
            via_fv = math.log(round(fv, 2) + 1e-10, 5.27)
            assert abs(direct - via_fv) < 1e-12
