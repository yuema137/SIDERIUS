"""
Unit tests for execute_tools/sample_set_builder.py

Pure logic tests — no I/O, no real data.
"""

import pytest

from execute_tools.dataset_config import DataScope, resolve_dataset_profile, tidmad_topology
from execute_tools.sample_set_builder import build_sample_set


def _segments_per_file() -> int:
    return tidmad_topology(resolve_dataset_profile()).dataset.segments_per_file


def _partition_count() -> int:
    return resolve_dataset_profile().partition_count


def _anchor_files() -> list[int]:
    return list(resolve_dataset_profile().anchor_selection_files)


# ---------------------------------------------------------------------------
# Normal mode (is_trial=False)
# ---------------------------------------------------------------------------


class TestNormalMode:
    def test_returns_single_file(self):
        ss = build_sample_set(is_trial=False, file_index=6)
        assert list(ss.keys()) == [6]

    def test_all_segments_included(self):
        ss = build_sample_set(is_trial=False, file_index=6)
        assert ss[6] == list(range(_segments_per_file()))

    def test_different_file_index(self):
        ss = build_sample_set(is_trial=False, file_index=0)
        assert list(ss.keys()) == [0]
        assert len(ss[0]) == _segments_per_file()

    def test_trial_fields_ignored(self):
        """Trial params should be ignored when is_trial=False."""
        ss = build_sample_set(
            is_trial=False,
            file_index=6,
            trial_strategy="target",
            target_files=[0, 1, 2],
        )
        assert list(ss.keys()) == [6]


# ---------------------------------------------------------------------------
# Snapshot strategy
# ---------------------------------------------------------------------------


class TestSnapshotStrategy:
    def test_all_declared_files_present(self):
        ss = build_sample_set(is_trial=True, trial_strategy="snapshot", seed=42)
        assert sorted(ss.keys()) == list(range(_partition_count()))

    def test_correct_segment_count(self):
        ss = build_sample_set(
            is_trial=True,
            trial_strategy="snapshot",
            trial_portion=0.1,
            seed=42,
        )
        expected = max(1, round(0.1 * _segments_per_file()))
        for fi, segs in ss.items():
            assert len(segs) == expected, f"File {fi}: expected {expected}, got {len(segs)}"

    def test_segments_are_valid(self):
        ss = build_sample_set(
            is_trial=True,
            trial_strategy="snapshot",
            trial_portion=0.2,
            seed=42,
        )
        for fi, segs in ss.items():
            assert all(0 <= s < _segments_per_file() for s in segs), (
                f"File {fi} has invalid segments"
            )

    def test_segments_are_sorted(self):
        ss = build_sample_set(
            is_trial=True,
            trial_strategy="snapshot",
            trial_portion=0.1,
            seed=42,
        )
        for fi, segs in ss.items():
            assert segs == sorted(segs), f"File {fi} segments not sorted"

    def test_full_portion(self):
        """portion=1.0 should include every declared segment."""
        ss = build_sample_set(
            is_trial=True,
            trial_strategy="snapshot",
            trial_portion=1.0,
            seed=42,
        )
        for _fi, segs in ss.items():
            assert len(segs) == _segments_per_file()

    def test_deterministic_with_seed(self):
        ss1 = build_sample_set(is_trial=True, trial_strategy="snapshot", trial_portion=0.1, seed=42)
        ss2 = build_sample_set(is_trial=True, trial_strategy="snapshot", trial_portion=0.1, seed=42)
        assert ss1 == ss2

    def test_different_seeds_differ(self):
        ss1 = build_sample_set(is_trial=True, trial_strategy="snapshot", trial_portion=0.1, seed=42)
        ss2 = build_sample_set(is_trial=True, trial_strategy="snapshot", trial_portion=0.1, seed=99)
        # At least some files should have different segments
        differ = any(ss1[fi] != ss2[fi] for fi in ss1)
        assert differ


# ---------------------------------------------------------------------------
# Anchors strategy
# ---------------------------------------------------------------------------


class TestAnchorsStrategy:
    def test_only_anchor_files(self):
        ss = build_sample_set(is_trial=True, trial_strategy="anchors", seed=42)
        assert sorted(ss.keys()) == sorted(_anchor_files())

    def test_correct_segment_count(self):
        ss = build_sample_set(
            is_trial=True,
            trial_strategy="anchors",
            trial_portion=0.1,
            seed=42,
        )
        expected = max(1, round(0.1 * _segments_per_file()))
        for _fi, segs in ss.items():
            assert len(segs) == expected


# ---------------------------------------------------------------------------
# Target strategy
# ---------------------------------------------------------------------------


class TestTargetStrategy:
    def test_only_target_files(self):
        ss = build_sample_set(
            is_trial=True,
            trial_strategy="target",
            target_files=[0, 1, 2, 3],
            seed=42,
        )
        assert sorted(ss.keys()) == [0, 1, 2, 3]

    def test_correct_segment_count(self):
        ss = build_sample_set(
            is_trial=True,
            trial_strategy="target",
            target_files=[5, 15],
            trial_portion=0.5,
            seed=42,
        )
        expected = max(1, round(0.5 * _segments_per_file()))
        for _fi, segs in ss.items():
            assert len(segs) == expected

    def test_deduplicates_target_files(self):
        ss = build_sample_set(
            is_trial=True,
            trial_strategy="target",
            target_files=[3, 3, 3, 1],
            seed=42,
        )
        assert sorted(ss.keys()) == [1, 3]

    def test_empty_target_files_raises(self):
        with pytest.raises(ValueError, match="non-empty target_files"):
            build_sample_set(
                is_trial=True,
                trial_strategy="target",
                target_files=[],
                seed=42,
            )

    def test_none_target_files_raises(self):
        with pytest.raises(ValueError, match="non-empty target_files"):
            build_sample_set(
                is_trial=True,
                trial_strategy="target",
                target_files=None,
                seed=42,
            )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_tiny_portion_at_least_one_segment(self):
        """Even with a very small portion, each file gets at least 1 segment."""
        ss = build_sample_set(
            is_trial=True,
            trial_strategy="snapshot",
            trial_portion=0.001,
            seed=42,
        )
        for _fi, segs in ss.items():
            assert len(segs) >= 1

    def test_no_duplicate_segments(self):
        ss = build_sample_set(
            is_trial=True,
            trial_strategy="snapshot",
            trial_portion=0.5,
            seed=42,
        )
        for fi, segs in ss.items():
            assert len(segs) == len(set(segs)), f"File {fi} has duplicate segments"

    def test_unknown_strategy_raises(self):
        with pytest.raises(ValueError, match="Unknown trial_strategy"):
            build_sample_set(
                is_trial=True,
                trial_strategy="invalid",
                seed=42,
            )


# ---------------------------------------------------------------------------
# DataScope (DS2 — docs/design/enable_partial_file_list.md)
# ---------------------------------------------------------------------------


class TestDataScopePartial:
    SCOPE = DataScope(file_indices=[4, 5, 6, 7, 8, 9])

    def test_snapshot_keys_equal_scope_exactly(self):
        ss = build_sample_set(
            is_trial=True, trial_strategy="snapshot", trial_portion=0.1, seed=42, scope=self.SCOPE
        )
        assert sorted(ss.keys()) == [4, 5, 6, 7, 8, 9]

    def test_snapshot_segment_counts_unchanged(self):
        ss = build_sample_set(
            is_trial=True, trial_strategy="snapshot", trial_portion=0.1, seed=42, scope=self.SCOPE
        )
        expected = max(1, round(0.1 * _segments_per_file()))
        for _fi, segs in ss.items():
            assert len(segs) == expected

    def test_anchors_rejected(self):
        with pytest.raises(ValueError, match="not allowed under a partial DataScope"):
            build_sample_set(is_trial=True, trial_strategy="anchors", seed=42, scope=self.SCOPE)

    def test_target_rejected_even_when_subset_of_scope(self):
        with pytest.raises(ValueError, match="not allowed under a partial DataScope"):
            build_sample_set(
                is_trial=True,
                trial_strategy="target",
                target_files=[4, 5],
                seed=42,
                scope=self.SCOPE,
            )

    def test_deterministic_with_seed(self):
        kw = dict(is_trial=True, trial_portion=0.1, seed=42, scope=self.SCOPE)
        assert build_sample_set(**kw) == build_sample_set(**kw)

    def test_normal_mode_in_scope_passes(self):
        ss = build_sample_set(is_trial=False, file_index=6, scope=self.SCOPE)
        assert list(ss.keys()) == [6]

    def test_normal_mode_out_of_scope_raises(self):
        with pytest.raises(ValueError, match="file_index=2 is outside the DataScope"):
            build_sample_set(is_trial=False, file_index=2, scope=self.SCOPE)


pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")
