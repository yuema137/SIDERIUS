"""
Unit tests for execute_tools/build_anchor_map.py

Tests the anchor map builder logic with mocked SNR computation.
No real HDF5 files or TIDMAD data required.
"""
import json
import math
import pytest
from unittest.mock import patch, MagicMock

from execute_tools.build_anchor_map import build_anchor_map, load_anchor_map
from execute_tools.scoring_utils import NUM_FILES, SEGMENTS_PER_FILE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_compute_ch2_snr(file_index, segment_index, data_dir):
    """
    Deterministic mock: SNR = file_index * 1000 + segment_index.
    This makes the global max predictable: file 19, segment 199 → 19199.
    """
    return file_index, segment_index, float(file_index * 1000 + segment_index)


# ---------------------------------------------------------------------------
# build_anchor_map
# ---------------------------------------------------------------------------

class TestBuildAnchorMap:

    @patch("execute_tools.build_anchor_map._compute_ch2_snr", side_effect=_mock_compute_ch2_snr)
    def test_returns_correct_structure(self, mock_compute):
        result = build_anchor_map(data_dir="/fake/path")

        assert "s_max" in result
        assert "segments_per_file" in result
        assert "num_files" in result
        assert "anchors" in result

        assert result["segments_per_file"] == SEGMENTS_PER_FILE
        assert result["num_files"] == NUM_FILES

    @patch("execute_tools.build_anchor_map._compute_ch2_snr", side_effect=_mock_compute_ch2_snr)
    def test_anchors_has_20_files(self, mock_compute):
        result = build_anchor_map(data_dir="/fake/path")
        assert len(result["anchors"]) == NUM_FILES

    @patch("execute_tools.build_anchor_map._compute_ch2_snr", side_effect=_mock_compute_ch2_snr)
    def test_each_file_has_200_segments(self, mock_compute):
        result = build_anchor_map(data_dir="/fake/path")
        for file_idx in range(NUM_FILES):
            segments = result["anchors"][str(file_idx)]
            assert len(segments) == SEGMENTS_PER_FILE, (
                f"File {file_idx} has {len(segments)} segments, expected {SEGMENTS_PER_FILE}"
            )

    @patch("execute_tools.build_anchor_map._compute_ch2_snr", side_effect=_mock_compute_ch2_snr)
    def test_s_max_is_global_maximum(self, mock_compute):
        result = build_anchor_map(data_dir="/fake/path")
        # With our mock: max is file 19, segment 199 → 19 * 1000 + 199 = 19199
        assert result["s_max"] == 19199.0

    @patch("execute_tools.build_anchor_map._compute_ch2_snr", side_effect=_mock_compute_ch2_snr)
    def test_snr_values_are_correct(self, mock_compute):
        result = build_anchor_map(data_dir="/fake/path")
        # Spot check: file 5, segment 42 → 5 * 1000 + 42 = 5042
        assert result["anchors"]["5"][42] == 5042.0
        # file 0, segment 0 → 0
        assert result["anchors"]["0"][0] == 0.0
        # file 19, segment 199 → 19199
        assert result["anchors"]["19"][199] == 19199.0

    @patch("execute_tools.build_anchor_map._compute_ch2_snr", side_effect=_mock_compute_ch2_snr)
    def test_total_compute_calls(self, mock_compute):
        build_anchor_map(data_dir="/fake/path")
        assert mock_compute.call_count == NUM_FILES * SEGMENTS_PER_FILE

    @patch("execute_tools.build_anchor_map._compute_ch2_snr", side_effect=_mock_compute_ch2_snr)
    def test_anchors_keys_are_strings(self, mock_compute):
        """Keys must be strings for JSON serialization."""
        result = build_anchor_map(data_dir="/fake/path")
        for key in result["anchors"]:
            assert isinstance(key, str)


# ---------------------------------------------------------------------------
# load_anchor_map
# ---------------------------------------------------------------------------

class TestLoadAnchorMap:

    def test_round_trip(self, tmp_path):
        """Write a map to JSON, load it back, verify contents match."""
        original = {
            "s_max": 42.5,
            "segments_per_file": 200,
            "num_files": 20,
            "anchors": {
                "0": [1.0, 2.0, 3.0],
                "1": [4.0, 5.0, 6.0],
            },
        }
        path = tmp_path / "test_anchors.json"
        with open(path, "w") as f:
            json.dump(original, f)

        loaded = load_anchor_map(str(path))
        assert loaded["s_max"] == 42.5
        assert loaded["anchors"]["0"] == [1.0, 2.0, 3.0]
        assert loaded["anchors"]["1"] == [4.0, 5.0, 6.0]


# ---------------------------------------------------------------------------
# scoring_utils constants
# ---------------------------------------------------------------------------

class TestConstants:

    def test_segment_length(self):
        from execute_tools.scoring_utils import SEGMENT_LENGTH
        assert SEGMENT_LENGTH == 10_000_000

    def test_segments_per_file(self):
        assert SEGMENTS_PER_FILE == 200

    def test_num_files(self):
        assert NUM_FILES == 20
