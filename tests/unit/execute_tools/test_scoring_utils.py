"""
Unit tests for execute_tools/scoring_utils.py — anchor-normalized scoring functions.

Tests score_segments() and score_vector() with mocked SNR computation.
No real HDF5 files or TIDMAD data required.
"""
import math
import pytest
from unittest.mock import patch, MagicMock

import numpy as np

from execute_tools.scoring_utils import (
    NUM_FILES,
    SEGMENTS_PER_FILE,
    score_segments,
    score_vector,
    SampleSet,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Simple anchor map: file i, segment j → SNR = (i + 1) * (j + 1)
# s_max = 20 * 200 = 4000 (file 19, segment 199)
MOCK_S_MAX = 4000.0
MOCK_ANCHOR_MAP = {
    str(i): [(i + 1) * (j + 1) for j in range(SEGMENTS_PER_FILE)]
    for i in range(NUM_FILES)
}


def _mock_get_one_sec_psd(data_dir, files, ch, start=0):
    """Return dummy freq/psd arrays that produce predictable SNR.

    Uses small arrays (1000 elements) since get_snr is also mocked —
    the actual array content doesn't matter for scoring unit tests.
    """
    freq = np.linspace(0, 5e6, 1000)
    psd = np.ones(1000) * 0.001
    psd[100] = 10.0  # dominant peak
    return freq, psd


def _mock_get_snr_fixed(freq, pwr, target=0):
    """Return a fixed SNR of 2.0 for any input."""
    return 2.0, freq[100] if target == 0 else target


# ---------------------------------------------------------------------------
# score_segments
# ---------------------------------------------------------------------------

class TestScoreSegments:

    @patch("execute_tools.scoring_utils.get_snr", side_effect=_mock_get_snr_fixed)
    @patch("execute_tools.scoring_utils.get_one_sec_psd", side_effect=_mock_get_one_sec_psd)
    def test_single_segment(self, mock_psd, mock_snr):
        """Score one segment: snr_squid=2.0, weight=anchor/s_max."""
        # File 0, segment 0: anchor = (0+1)*(0+1) = 1, weight = 1/4000
        result = score_segments(
            data_dir="/fake",
            denoised_filename="denoised_0000.h5",
            file_index=0,
            segment_indices=[0],
            anchor_map=MOCK_ANCHOR_MAP,
            s_max=MOCK_S_MAX,
        )
        expected_weight = 1.0 / 4000.0
        expected = 2.0 * expected_weight  # snr * weight
        assert abs(result - expected) < 1e-10

    @patch("execute_tools.scoring_utils.get_snr", side_effect=_mock_get_snr_fixed)
    @patch("execute_tools.scoring_utils.get_one_sec_psd", side_effect=_mock_get_one_sec_psd)
    def test_multiple_segments_averaged(self, mock_psd, mock_snr):
        """Score two segments: result is the mean of their weighted SNRs."""
        # File 5, segments [0, 9]:
        # seg 0: anchor = 6*1 = 6,  weight = 6/4000,  weighted_snr = 2.0 * 6/4000
        # seg 9: anchor = 6*10 = 60, weight = 60/4000, weighted_snr = 2.0 * 60/4000
        result = score_segments(
            data_dir="/fake",
            denoised_filename="denoised_0005.h5",
            file_index=5,
            segment_indices=[0, 9],
            anchor_map=MOCK_ANCHOR_MAP,
            s_max=MOCK_S_MAX,
        )
        w0 = 2.0 * (6.0 / 4000.0)
        w9 = 2.0 * (60.0 / 4000.0)
        expected = (w0 + w9) / 2.0
        assert abs(result - expected) < 1e-10

    def test_empty_segments_returns_nan(self):
        """Empty segment list should return NaN without any I/O."""
        result = score_segments(
            data_dir="/fake",
            denoised_filename="denoised.h5",
            file_index=0,
            segment_indices=[],
            anchor_map=MOCK_ANCHOR_MAP,
            s_max=MOCK_S_MAX,
        )
        assert math.isnan(result)

    @patch("execute_tools.scoring_utils.get_snr", side_effect=_mock_get_snr_fixed)
    @patch("execute_tools.scoring_utils.get_one_sec_psd", side_effect=_mock_get_one_sec_psd)
    def test_high_anchor_produces_higher_score(self, mock_psd, mock_snr):
        """A segment with higher anchor SNR should produce a higher weighted score."""
        # File 19, segment 199: anchor = 20*200 = 4000, weight = 1.0
        high = score_segments(
            data_dir="/fake",
            denoised_filename="denoised_0019.h5",
            file_index=19,
            segment_indices=[199],
            anchor_map=MOCK_ANCHOR_MAP,
            s_max=MOCK_S_MAX,
        )
        # File 0, segment 0: anchor = 1, weight = 1/4000
        low = score_segments(
            data_dir="/fake",
            denoised_filename="denoised_0000.h5",
            file_index=0,
            segment_indices=[0],
            anchor_map=MOCK_ANCHOR_MAP,
            s_max=MOCK_S_MAX,
        )
        assert high > low


# ---------------------------------------------------------------------------
# score_vector
# ---------------------------------------------------------------------------

class TestScoreVector:

    def _filename_fn(self, file_index):
        return f"denoised_{file_index:04d}.h5"

    @patch("execute_tools.scoring_utils.get_snr", side_effect=_mock_get_snr_fixed)
    @patch("execute_tools.scoring_utils.get_one_sec_psd", side_effect=_mock_get_one_sec_psd)
    def test_vector_length_is_20(self, mock_psd, mock_snr):
        sample_set: SampleSet = {0: [0, 1], 6: [0]}
        vector, scalar = score_vector(
            data_dir="/fake",
            sample_set=sample_set,
            anchor_map=MOCK_ANCHOR_MAP,
            s_max=MOCK_S_MAX,
            denoised_filename_fn=self._filename_fn,
        )
        assert len(vector) == NUM_FILES

    @patch("execute_tools.scoring_utils.get_snr", side_effect=_mock_get_snr_fixed)
    @patch("execute_tools.scoring_utils.get_one_sec_psd", side_effect=_mock_get_one_sec_psd)
    def test_excluded_files_are_none(self, mock_psd, mock_snr):
        sample_set: SampleSet = {6: [0]}
        vector, _ = score_vector(
            data_dir="/fake",
            sample_set=sample_set,
            anchor_map=MOCK_ANCHOR_MAP,
            s_max=MOCK_S_MAX,
            denoised_filename_fn=self._filename_fn,
        )
        # File 6 should have a real numeric score
        assert vector[6] is not None and not math.isnan(vector[6])
        # All other files should be None (not in sample_set, so not scored)
        for i in range(NUM_FILES):
            if i != 6:
                assert vector[i] is None, f"File {i} should be None, got {vector[i]}"

    @patch("execute_tools.scoring_utils.get_snr", side_effect=_mock_get_snr_fixed)
    @patch("execute_tools.scoring_utils.get_one_sec_psd", side_effect=_mock_get_one_sec_psd)
    def test_scalar_is_log_of_mean(self, mock_psd, mock_snr):
        """final_scalar_score = log_{5.27}(mean_of_non_nan + 1e-10)"""
        sample_set: SampleSet = {6: [0]}
        vector, scalar = score_vector(
            data_dir="/fake",
            sample_set=sample_set,
            anchor_map=MOCK_ANCHOR_MAP,
            s_max=MOCK_S_MAX,
            denoised_filename_fn=self._filename_fn,
        )
        expected = math.log(vector[6] + 1e-10, 5.27)
        assert abs(scalar - expected) < 1e-10

    @patch("execute_tools.scoring_utils.get_snr", side_effect=_mock_get_snr_fixed)
    @patch("execute_tools.scoring_utils.get_one_sec_psd", side_effect=_mock_get_one_sec_psd)
    def test_multiple_files_averaged(self, mock_psd, mock_snr):
        """Scalar averages non-NaN file scores before log."""
        sample_set: SampleSet = {0: [0], 19: [199]}
        vector, scalar = score_vector(
            data_dir="/fake",
            sample_set=sample_set,
            anchor_map=MOCK_ANCHOR_MAP,
            s_max=MOCK_S_MAX,
            denoised_filename_fn=self._filename_fn,
        )
        mean_score = (vector[0] + vector[19]) / 2.0
        expected = math.log(mean_score + 1e-10, 5.27)
        assert abs(scalar - expected) < 1e-10

    def test_raises_without_filename_fn(self):
        with pytest.raises(ValueError, match="denoised_filename_fn is required"):
            score_vector(
                data_dir="/fake",
                sample_set={0: [0]},
                anchor_map=MOCK_ANCHOR_MAP,
                s_max=MOCK_S_MAX,
                denoised_filename_fn=None,
            )

    @patch("execute_tools.scoring_utils.get_snr", side_effect=_mock_get_snr_fixed)
    @patch("execute_tools.scoring_utils.get_one_sec_psd", side_effect=_mock_get_one_sec_psd)
    def test_empty_sample_set(self, mock_psd, mock_snr):
        """Empty sample set: all-None vector, -inf scalar."""
        vector, scalar = score_vector(
            data_dir="/fake",
            sample_set={},
            anchor_map=MOCK_ANCHOR_MAP,
            s_max=MOCK_S_MAX,
            denoised_filename_fn=self._filename_fn,
        )
        assert all(v is None for v in vector)
        assert scalar == float("-inf")

    @patch("execute_tools.scoring_utils.get_snr", side_effect=_mock_get_snr_fixed)
    @patch("execute_tools.scoring_utils.get_one_sec_psd", side_effect=_mock_get_one_sec_psd)
    def test_normal_mode_single_file(self, mock_psd, mock_snr):
        """Normal mode: single file with all segments — 1 real value, 19 None."""
        all_segments = list(range(SEGMENTS_PER_FILE))
        sample_set: SampleSet = {6: all_segments}
        vector, scalar = score_vector(
            data_dir="/fake",
            sample_set=sample_set,
            anchor_map=MOCK_ANCHOR_MAP,
            s_max=MOCK_S_MAX,
            denoised_filename_fn=self._filename_fn,
        )
        present = [v for v in vector if v is not None]
        assert len(present) == 1
        assert vector[6] is not None and not math.isnan(vector[6])
