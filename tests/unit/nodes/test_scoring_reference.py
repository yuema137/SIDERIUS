"""
Unit tests for ``nodes.scoring_reference.load_reference_scores``.

Uses ``tmp_path`` fixtures to synthesize a full 20+20 reference tree, so no
dependency on the real on-disk data under ``SIDERIUS_DATA_DIR``. The loader's
module-level cache is cleared between tests via ``_reset_cache``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from nodes import scoring_reference
from nodes.scoring_reference import (
    _GT_PER_FILE_FMT,
    _GT_SCALAR_FILE,
    _RAW_PER_FILE_FMT,
    _RAW_SCALAR_FILE,
    ReferenceScores,
    load_reference_scores,
)


@pytest.fixture(autouse=True)
def _clear_cache_between_tests():
    scoring_reference._reset_cache()
    yield
    scoring_reference._reset_cache()


# -----------------------------------------------------------------------------
# Fixture helpers
# -----------------------------------------------------------------------------


def _write_raw_per_file(
    raw_dir: Path, idx: int, score: float = 1.0, linear_sum: float = 100.0, n_segments: int = 200
) -> None:
    (raw_dir / _RAW_PER_FILE_FMT.format(idx=idx)).write_text(
        json.dumps(
            {
                "file_index": idx,
                "score": score,
                "linear_sum": linear_sum,
                "n_segments": n_segments,
                "mode": "fine",
                "s_max": 295715680.14,
            }
        )
    )


def _write_gt_per_file(
    gt_dir: Path, idx: int, score: float = 5.0, linear_sum: float = 1000.0, n_segments: int = 200
) -> None:
    (gt_dir / _GT_PER_FILE_FMT.format(idx=idx)).write_text(
        json.dumps(
            {
                "file_index": idx,
                "score": score,
                "linear_sum": linear_sum,
                "n_segments": n_segments,
                "mode": "fine",
                "s_max": 295715680.14,
            }
        )
    )


def _write_raw_scalar(
    raw_dir: Path, *, scalar: float = 1.0011, s_max: float = 295715680.14
) -> None:
    (raw_dir / _RAW_SCALAR_FILE).write_text(
        json.dumps(
            {
                "scalar_score": scalar,
                "file_vector": [0.0] * 20,
                "formula": "anchor_normalized_raw_baseline",
                "s_max": s_max,
                "num_files": 20,
                "source": "segment_anchors.json",
            }
        )
    )


def _write_gt_scalar(gt_dir: Path, *, scalar: float = 10.1134, s_max: float = 295715680.14) -> None:
    (gt_dir / _GT_SCALAR_FILE).write_text(
        json.dumps(
            {
                "scalar_score": scalar,
                "file_vector": [0.0] * 20,
                "formula": "anchor_normalized_ceiling",
                "s_max": s_max,
                "num_files": 20,
                "source": "segment_anchors.json",
            }
        )
    )


def _synthesize_full_tree(
    tmp_path: Path, *, raw_smax: float = 295715680.14, gt_smax: float = 295715680.14
) -> tuple[Path, Path]:
    raw_dir = tmp_path / "raw_baseline"
    gt_dir = tmp_path / "ground_truth"
    raw_dir.mkdir()
    gt_dir.mkdir()

    for i in range(20):
        _write_raw_per_file(raw_dir, i, score=1.0 * i, linear_sum=10.0 * i, n_segments=200)
        _write_gt_per_file(gt_dir, i, score=5.0 * i, linear_sum=500.0 * i, n_segments=200)

    _write_raw_scalar(raw_dir, s_max=raw_smax)
    _write_gt_scalar(gt_dir, s_max=gt_smax)
    return raw_dir, gt_dir


# =============================================================================
# Happy path
# =============================================================================


class TestLoadReferenceScoresHappyPath:
    def test_returns_reference_scores_with_correct_shapes(self, tmp_path):
        raw_dir, gt_dir = _synthesize_full_tree(tmp_path)

        ref = load_reference_scores(
            raw_dir=str(raw_dir),
            gt_dir=str(gt_dir),
            use_cache=False,
        )
        assert isinstance(ref, ReferenceScores)
        assert len(ref.raw_per_file_log) == 20
        assert len(ref.gt_per_file_log) == 20
        assert len(ref.raw_per_file_linear_sum) == 20
        assert len(ref.raw_per_file_n_segments) == 20
        assert len(ref.gt_per_file_linear_sum) == 20
        assert len(ref.gt_per_file_n_segments) == 20
        assert ref.s_max == pytest.approx(295715680.14)
        assert ref.raw_scalar_full == pytest.approx(1.0011)
        assert ref.gt_scalar_full == pytest.approx(10.1134)

    def test_values_align_with_index(self, tmp_path):
        raw_dir, gt_dir = _synthesize_full_tree(tmp_path)
        ref = load_reference_scores(
            raw_dir=str(raw_dir),
            gt_dir=str(gt_dir),
            use_cache=False,
        )
        for i in range(20):
            assert ref.raw_per_file_log[i] == pytest.approx(1.0 * i)
            assert ref.gt_per_file_log[i] == pytest.approx(5.0 * i)
            assert ref.raw_per_file_linear_sum[i] == pytest.approx(10.0 * i)
            assert ref.gt_per_file_linear_sum[i] == pytest.approx(500.0 * i)
            assert ref.raw_per_file_n_segments[i] == 200
            assert ref.gt_per_file_n_segments[i] == 200


# =============================================================================
# Error paths
# =============================================================================


class TestLoadReferenceScoresErrorPaths:
    def test_missing_raw_per_file_raises(self, tmp_path):
        raw_dir, gt_dir = _synthesize_full_tree(tmp_path)
        os.remove(raw_dir / _RAW_PER_FILE_FMT.format(idx=7))
        with pytest.raises(FileNotFoundError, match="raw_baseline_score_file_0007"):
            load_reference_scores(
                raw_dir=str(raw_dir),
                gt_dir=str(gt_dir),
                use_cache=False,
            )

    def test_missing_gt_per_file_raises(self, tmp_path):
        raw_dir, gt_dir = _synthesize_full_tree(tmp_path)
        os.remove(gt_dir / _GT_PER_FILE_FMT.format(idx=11))
        with pytest.raises(FileNotFoundError, match="ground_truth_score_file_0011"):
            load_reference_scores(
                raw_dir=str(raw_dir),
                gt_dir=str(gt_dir),
                use_cache=False,
            )

    def test_missing_raw_scalar_raises(self, tmp_path):
        raw_dir, gt_dir = _synthesize_full_tree(tmp_path)
        os.remove(raw_dir / _RAW_SCALAR_FILE)
        with pytest.raises(FileNotFoundError, match=_RAW_SCALAR_FILE):
            load_reference_scores(
                raw_dir=str(raw_dir),
                gt_dir=str(gt_dir),
                use_cache=False,
            )

    def test_missing_gt_scalar_raises(self, tmp_path):
        raw_dir, gt_dir = _synthesize_full_tree(tmp_path)
        os.remove(gt_dir / _GT_SCALAR_FILE)
        with pytest.raises(FileNotFoundError, match=_GT_SCALAR_FILE):
            load_reference_scores(
                raw_dir=str(raw_dir),
                gt_dir=str(gt_dir),
                use_cache=False,
            )

    def test_legacy_raw_per_file_without_linear_sum_raises(self, tmp_path):
        """Pre-Phase-1 raw JSON lacks linear_sum — must refuse with a hint."""
        raw_dir, gt_dir = _synthesize_full_tree(tmp_path)
        # Overwrite file 3 with a legacy-shape JSON.
        (raw_dir / _RAW_PER_FILE_FMT.format(idx=3)).write_text(
            json.dumps(
                {
                    "file_index": 3,
                    "score": -13.854,
                    "mode": "fine",
                }
            )
        )
        with pytest.raises(KeyError, match="linear_sum"):
            load_reference_scores(
                raw_dir=str(raw_dir),
                gt_dir=str(gt_dir),
                use_cache=False,
            )

    def test_legacy_gt_per_file_without_n_segments_raises(self, tmp_path):
        raw_dir, gt_dir = _synthesize_full_tree(tmp_path)
        (gt_dir / _GT_PER_FILE_FMT.format(idx=5)).write_text(
            json.dumps(
                {
                    "file_index": 5,
                    "score": 0.0945,
                    "linear_sum": 1.0,  # no n_segments
                }
            )
        )
        with pytest.raises(KeyError, match="n_segments"):
            load_reference_scores(
                raw_dir=str(raw_dir),
                gt_dir=str(gt_dir),
                use_cache=False,
            )

    def test_smax_mismatch_raises(self, tmp_path):
        raw_dir, gt_dir = _synthesize_full_tree(
            tmp_path,
            raw_smax=1.0,
            gt_smax=2.0,
        )
        with pytest.raises(ValueError, match="s_max mismatch"):
            load_reference_scores(
                raw_dir=str(raw_dir),
                gt_dir=str(gt_dir),
                use_cache=False,
            )


# =============================================================================
# Cache behavior
# =============================================================================


class TestLoadReferenceScoresCache:
    def test_cache_returns_same_object(self, tmp_path):
        """Second call under use_cache=True returns the same instance,
        even if the underlying dirs change."""
        raw_dir, gt_dir = _synthesize_full_tree(tmp_path)
        kwargs = {"raw_dir": str(raw_dir), "gt_dir": str(gt_dir), "use_cache": True}

        first = load_reference_scores(**kwargs)
        os.remove(raw_dir / _RAW_PER_FILE_FMT.format(idx=0))

        second = load_reference_scores(**kwargs)
        assert second is first  # identity — second call is served from cache

    def test_cache_reset_restores_fresh_load(self, tmp_path):
        raw_dir, gt_dir = _synthesize_full_tree(tmp_path)
        kwargs = {"raw_dir": str(raw_dir), "gt_dir": str(gt_dir), "use_cache": True}

        _ = load_reference_scores(**kwargs)
        scoring_reference._reset_cache()
        os.remove(raw_dir / _RAW_PER_FILE_FMT.format(idx=0))

        with pytest.raises(FileNotFoundError):
            load_reference_scores(**kwargs)
