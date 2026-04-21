"""
Unit tests for ``compute_ground_truth.py`` — perfect-denoiser ceiling formulas.

The script is a thin CLI wrapper around two pure helpers:

* ``_legacy_per_file_ceiling`` — byte-strict legacy formula on one file.
* ``_anchor_normalized_ceiling`` — SIDERIUS grand-mean ceiling across all files,
  with the TIDMAD ``round(·, 2) + 1e-10`` step applied before ``log_{5.27}``
  (see ``docs/align_denoising_score.md`` §C).

These tests drive both helpers on hand-computed inputs so any drift in the
formula (missing round, wrong aggregation, wrong log base) fails loudly.
"""
from __future__ import annotations

import math

import pytest

# Root-level script import — pytest runs from repo root.
from compute_ground_truth import (
    _anchor_normalized_ceiling,
    _legacy_per_file_ceiling,
)


# =============================================================================
# _legacy_per_file_ceiling — byte-strict legacy single-file formula
# =============================================================================


class TestLegacyPerFileCeiling:

    def test_hand_computed_scalar(self):
        """Anchors [1, 2, 3, 4], max_sg=4:

        raw   = (1² + 2² + 3² + 4²) / (4 · 4) = 30/16 = 1.875
        score = round(1.875, 2) + 1e-10 = 1.88 + 1e-10
        return  log_{5.27}(1.88 + 1e-10)
        """
        anchors = [1.0, 2.0, 3.0, 4.0]
        got = _legacy_per_file_ceiling(anchors)
        expected = math.log(1.88 + 1e-10, 5.27)
        assert abs(got - expected) < 1e-12

    def test_all_zero_anchors_uses_one_as_max(self):
        """If max(anchors) == 0 the implementation substitutes 1.0 to avoid
        div-by-zero. raw = 0 / (n · 1) = 0 → round(0, 2) + 1e-10 = 1e-10."""
        got = _legacy_per_file_ceiling([0.0, 0.0, 0.0])
        expected = math.log(1e-10, 5.27)
        assert abs(got - expected) < 1e-12

    def test_constant_anchors(self):
        """Anchors [5, 5, 5]: max=5, raw = 75/(3·5) = 5.0,
        score = round(5.0, 2) + 1e-10, log_{5.27}(5.0+1e-10)."""
        got = _legacy_per_file_ceiling([5.0, 5.0, 5.0])
        expected = math.log(round(5.0, 2) + 1e-10, 5.27)
        assert abs(got - expected) < 1e-12


# =============================================================================
# _anchor_normalized_ceiling — grand-mean + TIDMAD round
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

        Single file with |S|=1 anchor=0.1, s_max=1:
            file_sum    = 0.01 / 1 = 0.01
            grand_mean  = 0.01
            round(0.01, 2) = 0.01
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
