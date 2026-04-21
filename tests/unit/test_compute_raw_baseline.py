"""
Unit tests for ``compute_raw_baseline._calculate_score`` — byte-strict legacy
per-file aggregation.

The PSD/SNR primitives themselves are tested in ``test_scoring_utils.py``;
this test fixes the *aggregation* formula
``math.log(round(Σ snr_sg·snr_squid / n, 2) + 1e-10, 5.27)`` and the
``snr_sg / np.amax(snr_sg)`` file-local normalization.

``n`` is hardcoded to ``_LEGACY_LIST_PATH_N = 200`` (fine) or ``20`` (coarse),
mirroring the legacy ``calculateBenchmark`` LIST-input shortcut
``n = 200 * len(file_list)``. No HDF5 read — ``process_segment`` is the
only function mocked out.

See ``docs/align_denoising_score.md`` §4.1.
"""
from __future__ import annotations

import math
from unittest.mock import patch

import compute_raw_baseline


# =============================================================================
# _calculate_score — fine mode (n = 200)
# =============================================================================


class TestCalculateScoreFine:

    def test_hand_computed_scalar(self):
        """Constant SNR pairs (snr_sg=2.0, snr_squid=3.0) for all 200 segments.

        snr_sg    = [2.0] * 200
        snr_squid = [3.0] * 200
        max_sg    = 2.0
        snr_sg /= 2  = [1.0] * 200
        Σ snr_sg·snr_squid = Σ 1.0·3.0 = 600
        mean      = 600 / 200 = 3.0
        round(3.0, 2) = 3.0
        score     = 3.0 + 1e-10
        return      log_{5.27}(3.0 + 1e-10)
        """
        def _const_process(i, data_dir, fname, coarse):
            return i, 2.0, 3.0

        with patch.object(compute_raw_baseline, "process_segment",
                          side_effect=_const_process):
            got = compute_raw_baseline._calculate_score(
                data_dir="/fake", fname="f.h5",
                coarse=False, parallel=False, num_workers=1,
            )

        expected = math.log(3.0 + 1e-10, 5.27)
        assert abs(got - expected) < 1e-12

    def test_fine_calls_process_segment_200_times(self):
        """Fine mode iterates over indices 0..199 — the legacy list-path cap."""
        collected: list[int] = []

        def _collect(i, data_dir, fname, coarse):
            collected.append(i)
            return i, 1.0, 1.0

        with patch.object(compute_raw_baseline, "process_segment",
                          side_effect=_collect):
            compute_raw_baseline._calculate_score(
                data_dir="/fake", fname="f.h5",
                coarse=False, parallel=False, num_workers=1,
            )

        assert sorted(collected) == list(range(200))


# =============================================================================
# _calculate_score — coarse mode (n = int(200 / 10) = 20)
# =============================================================================


class TestCalculateScoreCoarse:

    def test_coarse_stride_uses_int_divide_by_10(self):
        """Coarse mode runs exactly 20 iterations — ``int(200/10) = 20``.

        Legacy uses ``int(n / 10)`` — **not** ``max(1, n // 10)``. For
        n=200 the result is 20 either way. This test documents the
        legacy form for drift protection.
        """
        collected: list[tuple[int, bool]] = []

        def _collect(i, data_dir, fname, coarse):
            collected.append((i, coarse))
            return i, 1.0, 1.0

        with patch.object(compute_raw_baseline, "process_segment",
                          side_effect=_collect):
            compute_raw_baseline._calculate_score(
                data_dir="/fake", fname="f.h5",
                coarse=True, parallel=False, num_workers=1,
            )

        assert len(collected) == 20
        assert all(c is True for (_, c) in collected)
        assert sorted(i for (i, _) in collected) == list(range(20))
