"""
Unit tests for ``compute_raw_baseline._calculate_score`` — byte-strict legacy
per-file aggregation.

The PSD/SNR primitives themselves are tested in ``test_scoring_utils.py``;
this test fixes the *aggregation* formula
``math.log(round(Σ snr_sg·snr_squid / n, 2) + 1e-10, 5.27)`` and the
``snr_sg / np.amax(snr_sg)`` file-local normalization. Both ``process_segment``
and ``h5py.File`` are mocked so the test runs in milliseconds without any
HDF5 on disk.

See ``docs/align_denoising_score.md`` §4.1.
"""
from __future__ import annotations

import math
from unittest.mock import patch, MagicMock

import pytest

import compute_raw_baseline


class _FakeH5:
    """Minimal stand-in for ``h5py.File(..., 'r')``'s context-manager return."""

    def __init__(self, length: int):
        self._length = length

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __getitem__(self, key):
        assert key == "/timeseries/channel0001/timeseries"
        ds = MagicMock()
        ds.shape = (self._length,)
        return ds


def _mock_process_segment(i, data_dir, fname, coarse):
    """Return predictable SNR pairs: both channels carry ``i + 1``."""
    return i, float(i + 1), float(i + 1)


# =============================================================================
# _calculate_score — fine mode
# =============================================================================


class TestCalculateScoreFine:

    def test_hand_computed_scalar(self):
        """length = 40_000_000 → n = 4 segments, fine mode.

        snr_sg    = [1, 2, 3, 4]
        snr_squid = [1, 2, 3, 4]
        max_sg    = 4.0
        snr_sg /= 4 = [0.25, 0.5, 0.75, 1.0]
        Σ snr_sg·snr_squid = 0.25 + 1.0 + 2.25 + 4.0 = 7.5
        mean      = 7.5 / 4 = 1.875
        round(1.875, 2) = 1.88
        score     = 1.88 + 1e-10
        return      log_{5.27}(1.88 + 1e-10)
        """
        fake = _FakeH5(length=40_000_000)
        with patch.object(compute_raw_baseline.h5py, "File", return_value=fake), \
             patch.object(compute_raw_baseline, "process_segment",
                          side_effect=_mock_process_segment):
            got = compute_raw_baseline._calculate_score(
                data_dir="/fake", fname="f.h5",
                coarse=False, parallel=False, num_workers=1,
            )

        expected = math.log(1.88 + 1e-10, 5.27)
        assert abs(got - expected) < 1e-12


# =============================================================================
# _calculate_score — coarse mode (n = int(length / 10_000_000 / 10))
# =============================================================================


class TestCalculateScoreCoarse:

    def test_coarse_stride_uses_int_divide_by_10(self):
        """length = 2_000_000_000 → fine n = 200, coarse n = 20.

        Legacy uses ``int(n / 10)`` — **not** ``max(1, n // 10)``. For
        n=200 the result is 20 either way. This test documents the
        legacy form for drift protection.
        """
        fake = _FakeH5(length=2_000_000_000)
        collected_indices = []

        def _collect(i, data_dir, fname, coarse):
            collected_indices.append((i, coarse))
            return i, 1.0, 1.0  # constants so aggregation is deterministic

        with patch.object(compute_raw_baseline.h5py, "File", return_value=fake), \
             patch.object(compute_raw_baseline, "process_segment",
                          side_effect=_collect):
            compute_raw_baseline._calculate_score(
                data_dir="/fake", fname="f.h5",
                coarse=True, parallel=False, num_workers=1,
            )

        # Expect exactly 20 coarse iterations (n = int(200/10)).
        assert len(collected_indices) == 20
        # Every call carried coarse=True.
        assert all(c is True for (_, c) in collected_indices)
        # Indices are 0..19 (process_segment handles the ×10 stride internally).
        assert sorted(i for (i, _) in collected_indices) == list(range(20))

    def test_coarse_short_file_no_min_guard(self):
        """Legacy has no ``max(1, ·)`` guard. If length < 100_000_000 the
        coarse ``n = int(n/10)`` rounds to 0 and the aggregation divides
        by zero — byte-strict legacy behavior. We simply assert this
        branch reaches the aggregation without the pre-refactor guard
        silently rewriting n to 1.
        """
        fake = _FakeH5(length=50_000_000)  # fine n = 5, coarse n = int(5/10) = 0
        with patch.object(compute_raw_baseline.h5py, "File", return_value=fake), \
             patch.object(compute_raw_baseline, "process_segment",
                          side_effect=_mock_process_segment):
            # n=0 → snr_sg empty → np.amax raises ValueError. Legacy would
            # also raise here; we assert we do NOT silently promote n to 1.
            with pytest.raises(ValueError):
                compute_raw_baseline._calculate_score(
                    data_dir="/fake", fname="f.h5",
                    coarse=True, parallel=False, num_workers=1,
                )
