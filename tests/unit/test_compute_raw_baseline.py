"""
Unit tests for ``compute_raw_baseline._calculate_score`` — global-s_max
per-file aggregation under the Option B convention.

The PSD/SNR primitives themselves are tested in ``test_scoring_utils.py``;
this test fixes the *aggregation* formula

    per_segment = (snr_sg[i] / s_max_GLOBAL) * snr_squid[i]
    score       = log_{5.27}(round(mean_i(per_segment), 2) + 1e-10)

and the fixed segment counts — ``n = 200`` (fine) or ``n = 20`` (coarse,
every 10th segment). No HDF5 read — ``process_segment`` is the only
function mocked out.

See ``docs/align_denoising_score.md`` §4.1.
"""
from __future__ import annotations

import math
from unittest.mock import patch

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
        round(1.5, 2) = 1.5
        score       = 1.5 + 1e-10
        return        log_{5.27}(1.5 + 1e-10)
        """
        def _const_process(i, data_dir, fname, coarse):
            return i, 2.0, 3.0

        with patch.object(compute_raw_baseline, "process_segment",
                          side_effect=_const_process):
            got = compute_raw_baseline._calculate_score(
                data_dir="/fake", fname="f.h5",
                s_max=_TEST_S_MAX,
                coarse=False, parallel=False, num_workers=1,
            )

        expected = math.log(1.5 + 1e-10, 5.27)
        assert abs(got - expected) < 1e-12

    def test_fine_calls_process_segment_200_times(self):
        """Fine mode iterates over indices 0..199."""
        collected: list[int] = []

        def _collect(i, data_dir, fname, coarse):
            collected.append(i)
            return i, 1.0, 1.0

        with patch.object(compute_raw_baseline, "process_segment",
                          side_effect=_collect):
            compute_raw_baseline._calculate_score(
                data_dir="/fake", fname="f.h5",
                s_max=_TEST_S_MAX,
                coarse=False, parallel=False, num_workers=1,
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

        with patch.object(compute_raw_baseline, "process_segment",
                          side_effect=_collect):
            compute_raw_baseline._calculate_score(
                data_dir="/fake", fname="f.h5",
                s_max=_TEST_S_MAX,
                coarse=True, parallel=False, num_workers=1,
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
          s_max=4.0  -> per_seg = 1.0·2.0 = 2.0  -> mean=2.0 -> log(2.0+eps)
          s_max=8.0  -> per_seg = 0.5·2.0 = 1.0  -> mean=1.0 -> log(1.0+eps)
        Δ = log(2) / log(5.27) — independent of snr values.
        """
        def _const_process(i, data_dir, fname, coarse):
            return i, 4.0, 2.0

        with patch.object(compute_raw_baseline, "process_segment",
                          side_effect=_const_process):
            got_small = compute_raw_baseline._calculate_score(
                data_dir="/fake", fname="f.h5",
                s_max=4.0, coarse=True, parallel=False, num_workers=1,
            )
            got_large = compute_raw_baseline._calculate_score(
                data_dir="/fake", fname="f.h5",
                s_max=8.0, coarse=True, parallel=False, num_workers=1,
            )

        # smaller s_max -> larger per_segment -> larger score
        assert got_small > got_large
        # Δ should equal log_{5.27}(2) to ~1e-10
        import math as _m
        expected_delta = _m.log(2.0, 5.27)
        assert abs((got_small - got_large) - expected_delta) < 1e-9
