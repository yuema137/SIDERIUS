"""The FROZEN DAVIS clip rule (D14-3 C2) — hand-computed cases only.

`clip_starts` is a pure function of (frame_count, cap): no RNG, no disk, no
config. Every expectation below is hand-computed from the documented rule
(§2.2), never read back from the function. What only this catches: a
too-short sequence silently producing a padded window, an off-by-one on the
last legal start, uneven or duplicated spacing, and the cap being applied
to something other than the per-sequence window count.
"""

from __future__ import annotations

import pytest

from execute_tools.davis_data_path import (
    CLIP_CAPS,
    WINDOW_FRAMES,
    clip_starts,
)


class TestTooShortSequences:
    @pytest.mark.parametrize("frame_count", [0, 1, 11])
    def test_fewer_frames_than_one_window_yields_no_clips(self, frame_count):
        assert clip_starts(frame_count, cap=8) == ()

    def test_exactly_one_window_yields_exactly_start_zero(self):
        assert WINDOW_FRAMES == 12
        assert clip_starts(12, cap=8) == (0,)


class TestSpacing:
    def test_cap_binds_and_endpoints_are_first_and_last_legal(self):
        # F=112 -> L=100; cap 8 -> n=8; starts = round(i*100/7):
        # 0, 14.29->14, 28.57->29, 42.86->43, 57.14->57, 71.43->71,
        # 85.71->86, 100.
        assert clip_starts(112, cap=8) == (0, 14, 29, 43, 57, 71, 86, 100)

    def test_available_windows_bind_when_fewer_than_the_cap(self):
        # F=15 -> L=3 -> only 4 legal starts; cap 8 -> n=4 -> every start.
        assert clip_starts(15, cap=8) == (0, 1, 2, 3)

    def test_validation_cap_of_four_spaces_evenly(self):
        # F=52 -> L=40; cap 4 -> n=4; round(i*40/3): 0, 13.33->13, 26.67->27, 40.
        assert clip_starts(52, cap=4) == (0, 13, 27, 40)

    def test_banker_rounding_case_is_pinned(self):
        # F=14 -> L=2; cap 3 -> n=3; round(i*2/2) = 0, 1, 2 (exact, no tie).
        assert clip_starts(14, cap=3) == (0, 1, 2)
        # F=13 -> L=1; cap 4 -> n=2; starts 0 and 1.
        assert clip_starts(13, cap=4) == (0, 1)

    @pytest.mark.parametrize("frame_count", [12, 13, 20, 47, 83, 104, 500])
    @pytest.mark.parametrize("cap", [1, 4, 8])
    def test_invariants_hold_across_the_grid(self, frame_count, cap):
        starts = clip_starts(frame_count, cap)
        last_start = frame_count - WINDOW_FRAMES
        assert len(starts) == min(cap, last_start + 1)
        assert len(set(starts)) == len(starts), "duplicate starts"
        assert list(starts) == sorted(starts), "not ascending"
        assert starts[0] == 0
        assert starts[-1] == (last_start if len(starts) > 1 else 0)
        assert all(0 <= s <= last_start for s in starts)


class TestCaps:
    def test_the_frozen_caps_are_the_parent_indicative_ones(self):
        assert CLIP_CAPS == {"train": 8, "validation": 4, "final": 4}

    def test_a_nonsense_cap_is_refused(self):
        with pytest.raises(ValueError, match="cap must be"):
            clip_starts(100, cap=0)
