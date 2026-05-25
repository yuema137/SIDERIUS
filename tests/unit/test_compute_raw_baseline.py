"""
Unit tests for ``compute_raw_baseline._calculate_score`` — global-s_max
per-file aggregation under the Option B convention — and for
``_maybe_write_anchor_normalized_scalar``, the grand-mean aggregator.

The PSD/SNR primitives themselves are tested in ``test_scoring_utils.py``;
this test fixes the *aggregation* formula

    per_segment = (snr_sg[i] / s_max_GLOBAL) * snr_squid[i]
    log_score   = log_{5.27}(mean_i(per_segment))    [-inf if mean ≤ 0]
    linear_sum  = Σ_i per_segment[i]                  (unrounded, for grand-mean)
    n_segments  = n

Phase 6.7 dropped the legacy ``round(·, 2) + 1e-10`` quantization (see
``docs/phase67_infra_hardening_and_feedback_integrity.md`` Fix 4).

and the fixed segment counts — ``n = 200`` (fine) or ``n = 20`` (coarse,
every 10th segment). No HDF5 read — ``process_segment`` is the only
function mocked out.

See ``docs/align_denoising_score.md`` §4.1 and Decision 13 in
``docs/aggregated_score_table_awareness.md``.
"""

from __future__ import annotations

import json
import math
import os
from unittest.mock import patch

import pytest

import compute_raw_baseline

_TEST_S_MAX = 4.0  # pick a value that divides cleanly into snr_sg for hand math


# =============================================================================
# _calculate_score — fine mode (n = 200)
# =============================================================================


class TestCalculateScoreFine:
    def test_hand_computed_scalar(self):
        """Constant SNR pairs (snr_sg=2.0, snr_squid=3.0) for all 200 segments,
        s_max=4.0.

        per_segment = (2.0 / 4.0) * 3.0 = 1.5  (for every i)
        mean        = 1.5
        log_score   = log_{5.27}(1.5)
        linear_sum  = 1.5 * 200 = 300.0
        n_segments  = 200
        """

        def _const_process(i, data_dir, fname, coarse):
            return i, 2.0, 3.0

        with patch.object(compute_raw_baseline, "process_segment", side_effect=_const_process):
            log_score, linear_sum, n_segments = compute_raw_baseline._calculate_score(
                data_dir="/fake",
                fname="f.h5",
                s_max=_TEST_S_MAX,
                coarse=False,
                parallel=False,
                num_workers=1,
            )

        # ``+ 1e-10`` mirrors the production soft-floor offset
        # (compute_raw_baseline._calculate_score :131) — kept by Path-A
        # regen (commit 8947511); only the round(·,2) was dropped.
        expected_log = math.log(1.5 + 1e-10, 5.27)
        assert abs(log_score - expected_log) < 1e-12
        assert abs(linear_sum - 300.0) < 1e-9
        assert n_segments == 200

    def test_weak_signal_log_score_is_distinct_post_phase67(self):
        """Phase 6.7 ghost-score-killer regression guard.

        Pre-Phase-6.7, ``log_score`` quantized via ``round(mean, 2) + 1e-10``,
        which collapsed any weak-signal mean below 0.005 to ``log(1e-10) ≈
        -13.854`` and any mean in ``[0.005, 0.0149]`` to the ghost score
        ``-2.7708098959837675``. Post-fix, ``log_score = log_{5.27}(mean)``
        directly and weak signals get distinct, monotone scores.

        snr_sg=0.004, snr_squid=0.5, s_max=4.0, n=200.
          per_seg    = (0.004 / 4.0) * 0.5 = 5.0e-4
          mean       = 5.0e-4
          log_score  = log_{5.27}(5.0e-4) ≈ -4.575     (NOT -13.854, NOT -2.7708)
          linear_sum = 5.0e-4 * 200 = 0.1              (unrounded, precisely recoverable)
        """

        def _const_process(i, data_dir, fname, coarse):
            return i, 0.004, 0.5

        with patch.object(compute_raw_baseline, "process_segment", side_effect=_const_process):
            log_score, linear_sum, n_segments = compute_raw_baseline._calculate_score(
                data_dir="/fake",
                fname="f.h5",
                s_max=_TEST_S_MAX,
                coarse=False,
                parallel=False,
                num_workers=1,
            )

        # ``+ 1e-10`` soft floor (see :131) — at mean=5e-4 it shifts the
        # log by ~1.2e-7, well above the 1e-12 tolerance.
        expected_log = math.log(5.0e-4 + 1e-10, 5.27)
        assert abs(log_score - expected_log) < 1e-12
        # The ghost-score collapse must NOT happen.
        assert abs(log_score - (-2.7708098959837675)) > 0.5
        # The synthetic legacy floor must NOT happen.
        assert abs(log_score - math.log(1e-10, 5.27)) > 0.5
        # linear_sum retains full precision (unaffected by the formula change).
        assert abs(linear_sum - 0.1) < 1e-12
        assert n_segments == 200

    def test_fine_calls_process_segment_200_times(self):
        """Fine mode iterates over indices 0..199."""
        collected: list[int] = []

        def _collect(i, data_dir, fname, coarse):
            collected.append(i)
            return i, 1.0, 1.0

        with patch.object(compute_raw_baseline, "process_segment", side_effect=_collect):
            compute_raw_baseline._calculate_score(
                data_dir="/fake",
                fname="f.h5",
                s_max=_TEST_S_MAX,
                coarse=False,
                parallel=False,
                num_workers=1,
            )

        assert sorted(collected) == list(range(200))


# =============================================================================
# _calculate_score — coarse mode (n = 20)
# =============================================================================


class TestCalculateScoreCoarse:
    def test_coarse_stride_uses_20_segments(self):
        """Coarse mode runs exactly 20 iterations (every 10th segment).

        ``process_segment`` internally multiplies the segment index by 10
        when ``coarse=True``, so the worker is called with indices 0..19
        but reads segments 0, 10, 20, ..., 190 of the underlying file.
        """
        collected: list[tuple[int, bool]] = []

        def _collect(i, data_dir, fname, coarse):
            collected.append((i, coarse))
            return i, 1.0, 1.0

        with patch.object(compute_raw_baseline, "process_segment", side_effect=_collect):
            compute_raw_baseline._calculate_score(
                data_dir="/fake",
                fname="f.h5",
                s_max=_TEST_S_MAX,
                coarse=True,
                parallel=False,
                num_workers=1,
            )

        assert len(collected) == 20
        assert all(c is True for (_, c) in collected)
        assert sorted(i for (i, _) in collected) == list(range(20))

    def test_coarse_uses_same_global_s_max(self):
        """Coarse mode must divide by the passed-in global s_max — not by a
        file-local ``amax(snr_sg)``. Two runs at different s_max values on
        the same synthetic pairs must differ by ``log_{5.27}(s_max_ratio)``
        (before the TIDMAD round, which we avoid by choosing nice values).

        snr_sg=4.0, snr_squid=2.0, 20 segments.
          s_max=4.0  -> per_seg = 1.0·2.0 = 2.0  -> mean=2.0 -> log(2.0)
          s_max=8.0  -> per_seg = 0.5·2.0 = 1.0  -> mean=1.0 -> log(1.0)
        Δ = log(2) / log(5.27) — independent of snr values.
        """

        def _const_process(i, data_dir, fname, coarse):
            return i, 4.0, 2.0

        with patch.object(compute_raw_baseline, "process_segment", side_effect=_const_process):
            log_small, _, _ = compute_raw_baseline._calculate_score(
                data_dir="/fake",
                fname="f.h5",
                s_max=4.0,
                coarse=True,
                parallel=False,
                num_workers=1,
            )
            log_large, _, _ = compute_raw_baseline._calculate_score(
                data_dir="/fake",
                fname="f.h5",
                s_max=8.0,
                coarse=True,
                parallel=False,
                num_workers=1,
            )

        # smaller s_max -> larger per_segment -> larger score
        assert log_small > log_large
        # Both sides carry the production soft-floor offset (+1e-10);
        # the offset does not cancel exactly because
        # log(a+ε) − log(b+ε) ≠ log(a/b) when ε > 0.
        expected_delta = math.log(2.0 + 1e-10, 5.27) - math.log(1.0 + 1e-10, 5.27)
        assert abs((log_small - log_large) - expected_delta) < 1e-12


# =============================================================================
# _maybe_write_anchor_normalized_scalar — grand-mean aggregator over the 20
# fine per-file JSONs. Symmetric with
# ``compute_ground_truth._anchor_normalized_ceiling``.
# =============================================================================


def _write_fine_json(
    output_dir: str,
    idx: int,
    *,
    score: float = 1.0,
    linear_sum: float | None = 100.0,
    n_segments: int | None = 200,
    s_max: float = 4.0,
) -> None:
    """Helper to synthesize one per-file JSON fixture. If linear_sum or
    n_segments is None, that key is omitted (legacy-without-fields case)."""
    payload: dict = {
        "file_index": idx,
        "score": score,
        "mode": "fine",
        "data_file": f"abra_validation_{idx:04d}.h5",
        "s_max": s_max,
        "formula": "option_b_global_s_max",
        "computed_at": "test",
    }
    if linear_sum is not None:
        payload["linear_sum"] = linear_sum
    if n_segments is not None:
        payload["n_segments"] = n_segments
    with open(os.path.join(output_dir, f"raw_baseline_score_file_{idx:04d}.json"), "w") as f:
        json.dump(payload, f)


class TestMaybeWriteAnchorNormalizedScalar:
    def test_writes_scalar_when_all_20_fine_present(self, tmp_path):
        """Complete set of 20 fine JSONs with linear_sum + n_segments — the
        aggregator must emit scalar_anchor_normalized.json with the exact
        shape of ceiling_anchor_normalized.json.

        Uniform per-file linear_sum=100, n_segments=200:
          grand_mean = (100 * 20) / (200 * 20) = 0.5
          scalar     = log_{5.27}(0.5)  (Phase 6.7: no rounding, no eps)
        """
        for i in range(20):
            _write_fine_json(str(tmp_path), i, linear_sum=100.0, n_segments=200)

        compute_raw_baseline._maybe_write_anchor_normalized_scalar(
            output_dir=str(tmp_path),
            s_max=_TEST_S_MAX,
            anchor_src="segment_anchors.json",
        )

        scalar_path = tmp_path / "scalar_anchor_normalized.json"
        assert scalar_path.exists()
        with open(scalar_path) as f:
            got = json.load(f)

        # Exact key parity with ceiling_anchor_normalized.json.
        assert set(got.keys()) == {
            "scalar_score",
            "file_vector",
            "formula",
            "s_max",
            "num_files",
            "source",
            "computed_at",
        }
        assert got["num_files"] == 20
        assert got["formula"] == "anchor_normalized_raw_baseline"
        assert got["s_max"] == _TEST_S_MAX
        assert got["source"] == "segment_anchors.json"
        assert len(got["file_vector"]) == 20
        # file_vector is linear per-file means (linear_sum / n_segments).
        for v in got["file_vector"]:
            assert abs(v - 0.5) < 1e-12
        # ``+ 1e-10`` soft-floor offset on the grand mean
        # (compute_raw_baseline._maybe_write_anchor_normalized_scalar :199).
        expected_scalar = math.log(0.5 + 1e-10, 5.27)
        assert abs(got["scalar_score"] - expected_scalar) < 1e-12

    def test_skip_when_any_fine_index_missing(self, tmp_path, capsys):
        """If any of files 0..19 is missing, the scalar file must NOT be
        written, and the missing indices must be printed."""
        for i in range(19):  # omit file 19
            _write_fine_json(str(tmp_path), i)

        compute_raw_baseline._maybe_write_anchor_normalized_scalar(
            output_dir=str(tmp_path),
            s_max=_TEST_S_MAX,
            anchor_src="segment_anchors.json",
        )

        assert not (tmp_path / "scalar_anchor_normalized.json").exists()
        captured = capsys.readouterr()
        assert "missing fine indices" in captured.out
        assert "[19]" in captured.out

    def test_skip_when_legacy_json_lacks_new_fields(self, tmp_path, capsys):
        """If a per-file JSON predates Decision 13 (no linear_sum /
        n_segments), the aggregator must NOT silently use the lossy ``score``
        — it must skip and prompt the user to re-run with --override."""
        for i in range(19):
            _write_fine_json(str(tmp_path), i)
        # File 5 is a legacy JSON — missing the new fields.
        _write_fine_json(str(tmp_path), 19, linear_sum=None, n_segments=None)

        compute_raw_baseline._maybe_write_anchor_normalized_scalar(
            output_dir=str(tmp_path),
            s_max=_TEST_S_MAX,
            anchor_src="segment_anchors.json",
        )

        assert not (tmp_path / "scalar_anchor_normalized.json").exists()
        captured = capsys.readouterr()
        assert "linear_sum/n_segments" in captured.out
        assert "[19]" in captured.out

    def test_grand_mean_weights_by_n_segments(self, tmp_path):
        """When per-file n_segments varies, the grand mean weighs linear_sums
        by their segment counts. Hand-compute with two distinct counts:

          10 files at n=100, linear_sum=10  (per-file mean = 0.1)
          10 files at n=300, linear_sum=90  (per-file mean = 0.3)
          total_linear = 10*10 + 10*90 = 1000
          total_n      = 10*100 + 10*300 = 4000
          grand_mean   = 1000 / 4000 = 0.25
          scalar       = log_{5.27}(0.25 + 1e-10)
                         (Path-A regen: rounding dropped, soft-floor +1e-10 kept.)
        """
        for i in range(10):
            _write_fine_json(str(tmp_path), i, linear_sum=10.0, n_segments=100)
        for i in range(10, 20):
            _write_fine_json(str(tmp_path), i, linear_sum=90.0, n_segments=300)

        compute_raw_baseline._maybe_write_anchor_normalized_scalar(
            output_dir=str(tmp_path),
            s_max=_TEST_S_MAX,
            anchor_src="segment_anchors.json",
        )

        scalar_path = tmp_path / "scalar_anchor_normalized.json"
        assert scalar_path.exists()
        with open(scalar_path) as f:
            got = json.load(f)

        # ``+ 1e-10`` soft-floor offset (see production formula at
        # compute_raw_baseline._maybe_write_anchor_normalized_scalar :199).
        expected_scalar = math.log(0.25 + 1e-10, 5.27)
        assert abs(got["scalar_score"] - expected_scalar) < 1e-12

        # Per-file linear means preserve both groups.
        assert got["file_vector"][:10] == pytest.approx([0.1] * 10, abs=1e-12)
        assert got["file_vector"][10:] == pytest.approx([0.3] * 10, abs=1e-12)
