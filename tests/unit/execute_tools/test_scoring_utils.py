"""
Unit tests for execute_tools/scoring_utils.py — anchor-normalized scoring functions.

Tests score_segments() and score_vector() with mocked SNR computation.
No real HDF5 files or TIDMAD data required.
"""

import math
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from execute_tools.scoring_utils import (
    NUM_FILES,
    SEGMENTS_PER_FILE,
    SampleSet,
    get_snr,
    score_segments,
    score_vector,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Simple anchor map: file i, segment j → SNR = (i + 1) * (j + 1)
# s_max = 20 * 200 = 4000 (file 19, segment 199)
MOCK_S_MAX = 4000.0
MOCK_ANCHOR_MAP = {
    str(i): [(i + 1) * (j + 1) for j in range(SEGMENTS_PER_FILE)] for i in range(NUM_FILES)
}


@pytest.mark.parametrize(
    ("noise", "expect_valid"),
    [(0.5e-10, False), (1.0e-10, False), (1.5e-10, True)],
)
def test_get_snr_noise_validity_boundary(noise, expect_valid):
    """The frozen scorer rejects noise at and below 1e-10 only."""
    freq = np.arange(201, dtype=float)
    pwr = np.zeros(201, dtype=float)
    center = 100
    pwr[center - 10] = noise
    snr, center_freq = get_snr(freq, pwr, target=freq[center])
    assert center_freq == freq[center]
    if expect_valid:
        assert np.isfinite(snr)
        assert snr == 0.0
    else:
        assert np.isnan(snr)


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

    # Note on ``parallel=False``: the new ``score_vector`` dispatches to
    # ``ProcessPoolExecutor`` whenever there is more than one file AND
    # ``parallel=True``. ``@patch`` decorators cannot cross process
    # boundaries — the workers re-import ``execute_tools.scoring_utils``
    # and see the unmocked functions. All tests here pass
    # ``parallel=False`` to keep execution in the main process so mocks
    # take effect.

    @patch("execute_tools.scoring_utils.get_snr", side_effect=_mock_get_snr_fixed)
    @patch("execute_tools.scoring_utils.get_one_sec_psd", side_effect=_mock_get_one_sec_psd)
    def test_vector_length_is_20(self, mock_psd, mock_snr):
        sample_set: SampleSet = {0: [0, 1], 6: [0]}
        vector, _scalar = score_vector(
            data_dir="/fake",
            sample_set=sample_set,
            anchor_map=MOCK_ANCHOR_MAP,
            s_max=MOCK_S_MAX,
            denoised_filename_fn=self._filename_fn,
            parallel=False,
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
            parallel=False,
        )
        # File 6 should have a real numeric score
        assert vector[6] is not None and not math.isnan(vector[6])
        # All other files should be None (not in sample_set, so not scored)
        for i in range(NUM_FILES):
            if i != 6:
                assert vector[i] is None, f"File {i} should be None, got {vector[i]}"

    @patch("execute_tools.scoring_utils.get_snr", side_effect=_mock_get_snr_fixed)
    @patch("execute_tools.scoring_utils.get_one_sec_psd", side_effect=_mock_get_one_sec_psd)
    def test_scalar_is_log_of_grand_mean(self, mock_psd, mock_snr):
        """``final_scalar = log_{5.27}(grand_mean)`` (no rounding, no eps).

        Single file, single segment ⇒ grand_mean == vector[6]. The Phase-67
        scoring-precision fix dropped the ``round(·, 2) + 1e-10`` quantization
        because it collapsed all weak-injection grand means in
        ``[0.005, 0.0149]`` to the ghost score
        ``log_{5.27}(0.01 + 1e-10) ≈ -2.7708``.
        """
        sample_set: SampleSet = {6: [0]}
        vector, scalar = score_vector(
            data_dir="/fake",
            sample_set=sample_set,
            anchor_map=MOCK_ANCHOR_MAP,
            s_max=MOCK_S_MAX,
            denoised_filename_fn=self._filename_fn,
            parallel=False,
        )
        expected = math.log(vector[6], 5.27)
        assert abs(scalar - expected) < 1e-12

    @patch("execute_tools.scoring_utils.get_snr", side_effect=_mock_get_snr_fixed)
    @patch("execute_tools.scoring_utils.get_one_sec_psd", side_effect=_mock_get_one_sec_psd)
    def test_multiple_files_grand_mean(self, mock_psd, mock_snr):
        """Scalar uses the legacy grand mean (not mean-of-file-means).

        With uniform ``|S_f|=1`` across two files, the grand mean equals
        the simple mean of the two ``file_vector`` entries.
        """
        sample_set: SampleSet = {0: [0], 19: [199]}
        vector, scalar = score_vector(
            data_dir="/fake",
            sample_set=sample_set,
            anchor_map=MOCK_ANCHOR_MAP,
            s_max=MOCK_S_MAX,
            denoised_filename_fn=self._filename_fn,
            parallel=False,
        )
        grand_mean = (vector[0] + vector[19]) / 2.0
        expected = math.log(grand_mean, 5.27)
        assert abs(scalar - expected) < 1e-12

    def test_raises_without_filename_fn(self):
        with pytest.raises(ValueError, match="denoised_filename_fn is required"):
            score_vector(
                data_dir="/fake",
                sample_set={0: [0]},
                anchor_map=MOCK_ANCHOR_MAP,
                s_max=MOCK_S_MAX,
                denoised_filename_fn=None,
                parallel=False,
            )

    def test_raises_without_s_max_in_non_legacy_mode(self):
        """Non-legacy mode requires ``s_max`` from the anchor map."""
        with pytest.raises(ValueError, match="Non-legacy mode requires s_max"):
            score_vector(
                data_dir="/fake",
                sample_set={0: [0]},
                anchor_map=MOCK_ANCHOR_MAP,
                s_max=None,
                denoised_filename_fn=self._filename_fn,
                parallel=False,
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
            parallel=False,
        )
        assert all(v is None for v in vector)
        assert scalar == float("-inf")

    @patch("execute_tools.scoring_utils.get_snr", side_effect=_mock_get_snr_fixed)
    @patch("execute_tools.scoring_utils.get_one_sec_psd", side_effect=_mock_get_one_sec_psd)
    def test_normal_mode_single_file(self, mock_psd, mock_snr):
        """Normal mode: single file with all segments — 1 real value, 19 None."""
        all_segments = list(range(SEGMENTS_PER_FILE))
        sample_set: SampleSet = {6: all_segments}
        vector, _scalar = score_vector(
            data_dir="/fake",
            sample_set=sample_set,
            anchor_map=MOCK_ANCHOR_MAP,
            s_max=MOCK_S_MAX,
            denoised_filename_fn=self._filename_fn,
            parallel=False,
        )
        present = [v for v in vector if v is not None]
        assert len(present) == 1
        assert vector[6] is not None and not math.isnan(vector[6])

    @patch("execute_tools.scoring_utils.get_snr", side_effect=_mock_get_snr_fixed)
    @patch("execute_tools.scoring_utils.get_one_sec_psd", side_effect=_mock_get_one_sec_psd)
    def test_legacy_mode_derives_s_max_globally_from_collected_pairs(self, mock_psd, mock_snr):
        """``legacy_mode=True`` derives ``s_max`` globally as
        ``np.amax(snr_sg)`` over *all pairs collected across the sample_set*
        — not per-file. It ignores any anchor map or explicit ``s_max``
        argument passed in.

        Mocked ``snr_sg = 2.0`` for every segment, so the global-over-
        collected-data s_max is 2.0. For a single segment this yields
        grand_mean = (2/2) * 2 = 2.0 and the scalar becomes
        ``log_{5.27}(2.0)`` regardless of the anchor map or s_max we pass in.

        This is distinct from the Option B convention (``legacy_mode=False``),
        where ``s_max`` is the global maximum over the anchor map — a fixed
        constant independent of which segments happen to be sampled.
        """
        sample_set: SampleSet = {6: [0]}
        _, scalar_legacy = score_vector(
            data_dir="/fake",
            sample_set=sample_set,
            anchor_map=None,
            s_max=None,  # legacy_mode ignores s_max
            denoised_filename_fn=self._filename_fn,
            legacy_mode=True,
            parallel=False,
        )
        # snr_sg=2, snr_squid=2, s_max=np.amax([2.0])=2.0
        # grand_mean = (2/2) * 2 = 2.0
        expected = math.log(2.0, 5.27)
        assert abs(scalar_legacy - expected) < 1e-12


# Note (commit-5a): ``TestScoreVectorHealthCheck`` used to live here (5
# tests exercising ``reference_file_vector`` + the ``is_degenerate`` /
# ``failure_reason`` return fields). Those fields were removed from
# ``score_vector``'s signature per Option A in
# ``docs/design/pluggable_health_checks.md`` §14 — health checks now run
# tuner-side via ``evaluate_gate``. The equivalent testing lives in the
# tuner's gate-integration tests (added in commit-5b).
