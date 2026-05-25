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
        vector, _scalar, _, _ = score_vector(
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
        vector, _, _, _ = score_vector(
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
        vector, scalar, _, _ = score_vector(
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
        vector, scalar, _, _ = score_vector(
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
        vector, scalar, _, _ = score_vector(
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
        vector, _scalar, _, _ = score_vector(
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
        _, scalar_legacy, _, _ = score_vector(
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


# ---------------------------------------------------------------------------
# score_vector — reference / health-check integration (commit b2)
# ---------------------------------------------------------------------------


class TestScoreVectorHealthCheck:
    """``score_vector`` accepts an optional ``reference_file_vector`` and
    returns ``(file_vector, scalar, is_degenerate, failure_reason)``.

    The collapse predicate itself is unit-tested in
    ``test_squid_health_checks.py`` — these tests verify the wiring:
    ``score_vector`` correctly forwards to ``check_amplitude_collapse``
    and surfaces the result in its return tuple.
    """

    def _filename_fn(self, file_index: int) -> str:
        return f"validation_denoised_{file_index:04d}.h5"

    @patch("execute_tools.scoring_utils.get_snr", side_effect=_mock_get_snr_fixed)
    @patch("execute_tools.scoring_utils.get_one_sec_psd", side_effect=_mock_get_one_sec_psd)
    def test_no_reference_returns_false_none(self, mock_psd, mock_snr):
        """Graceful fallback: ``reference_file_vector=None`` (the default)
        skips the health check; ``is_degenerate`` is False, reason is None."""
        sample_set: SampleSet = {6: [0]}
        _, _, is_degen, reason = score_vector(
            data_dir="/fake",
            sample_set=sample_set,
            anchor_map=MOCK_ANCHOR_MAP,
            s_max=MOCK_S_MAX,
            denoised_filename_fn=self._filename_fn,
            parallel=False,
            # reference_file_vector omitted -> None default
        )
        assert is_degen is False
        assert reason is None

    @patch("execute_tools.scoring_utils.get_snr", side_effect=_mock_get_snr_fixed)
    @patch("execute_tools.scoring_utils.get_one_sec_psd", side_effect=_mock_get_one_sec_psd)
    def test_reference_with_collapse_trips_check(self, mock_psd, mock_snr):
        """A reference 1000× the current output must trip collapse."""
        sample_set: SampleSet = {6: [0]}
        # Current output mocked to a small magnitude. Pass a reference
        # whose mean magnitude vastly exceeds the current.
        reference_huge = [None] * NUM_FILES
        reference_huge[6] = 10000.0
        _, _, is_degen, reason = score_vector(
            data_dir="/fake",
            sample_set=sample_set,
            anchor_map=MOCK_ANCHOR_MAP,
            s_max=MOCK_S_MAX,
            denoised_filename_fn=self._filename_fn,
            parallel=False,
            reference_file_vector=reference_huge,
        )
        assert is_degen is True
        assert reason is not None
        assert "amplitude_collapse" in reason

    @patch("execute_tools.scoring_utils.get_snr", side_effect=_mock_get_snr_fixed)
    @patch("execute_tools.scoring_utils.get_one_sec_psd", side_effect=_mock_get_one_sec_psd)
    def test_reference_with_normal_output_passes(self, mock_psd, mock_snr):
        """When the current output is comparable to the reference, the
        check passes."""
        sample_set: SampleSet = {6: [0]}
        # Mock returns snr_squid=2.0 — score should be a small linear
        # value. Pass a reference at a similar order of magnitude.
        # Because mocks are non-trivial, we read the actual file_vector
        # first then build a reference at parity.
        fv, _, _, _ = score_vector(
            data_dir="/fake",
            sample_set=sample_set,
            anchor_map=MOCK_ANCHOR_MAP,
            s_max=MOCK_S_MAX,
            denoised_filename_fn=self._filename_fn,
            parallel=False,
        )
        # Use the same vector as reference -> ratio is 1.0, well above 1%.
        _, _, is_degen, reason = score_vector(
            data_dir="/fake",
            sample_set=sample_set,
            anchor_map=MOCK_ANCHOR_MAP,
            s_max=MOCK_S_MAX,
            denoised_filename_fn=self._filename_fn,
            parallel=False,
            reference_file_vector=fv,
        )
        assert is_degen is False
        assert reason is None

    @patch("execute_tools.scoring_utils.get_snr", side_effect=_mock_get_snr_fixed)
    @patch("execute_tools.scoring_utils.get_one_sec_psd", side_effect=_mock_get_one_sec_psd)
    def test_custom_threshold_forwarded(self, mock_psd, mock_snr):
        """A 5% threshold catches a 4%-of-reference output that the default
        (1%) would miss — proves ``degeneracy_threshold_ratio`` is forwarded."""
        sample_set: SampleSet = {6: [0]}
        fv, _, _, _ = score_vector(
            data_dir="/fake",
            sample_set=sample_set,
            anchor_map=MOCK_ANCHOR_MAP,
            s_max=MOCK_S_MAX,
            denoised_filename_fn=self._filename_fn,
            parallel=False,
        )
        # Build reference 25× larger -> ratio = 4% (below 5%, above 1%)
        ref = [None] * NUM_FILES
        ref[6] = float(fv[6]) * 25.0
        # Default 1% threshold passes
        _, _, is_degen_default, _ = score_vector(
            data_dir="/fake",
            sample_set=sample_set,
            anchor_map=MOCK_ANCHOR_MAP,
            s_max=MOCK_S_MAX,
            denoised_filename_fn=self._filename_fn,
            parallel=False,
            reference_file_vector=ref,
        )
        assert is_degen_default is False
        # Custom 5% threshold trips
        _, _, is_degen_custom, reason_custom = score_vector(
            data_dir="/fake",
            sample_set=sample_set,
            anchor_map=MOCK_ANCHOR_MAP,
            s_max=MOCK_S_MAX,
            denoised_filename_fn=self._filename_fn,
            parallel=False,
            reference_file_vector=ref,
            degeneracy_threshold_ratio=0.05,
        )
        assert is_degen_custom is True
        assert reason_custom is not None
