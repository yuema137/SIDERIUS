"""Tests for execute_tools/dataset_config.py.

Focus: ``DatasetConfig.valid_segmentation_sizes`` — the helper used by both the
proposer-side schema validator and the planner prompt's known-constraints block.
"""

from execute_tools.dataset_config import TIDMAD, DatasetConfig

# ---- valid_segmentation_sizes ----


def test_returns_sorted_divisors_within_default_window():
    sizes = TIDMAD.valid_segmentation_sizes()
    assert sizes == sorted(sizes)
    psd = TIDMAD.psd_segment_length
    for s in sizes:
        assert psd % s == 0
        assert 100 <= s <= 100_000


def test_excludes_invalid_powers_of_two_for_tidmad():
    """16384, 8192, 4096 must NOT appear — these are the values the LLM keeps
    proposing that don't divide 10_000_000."""
    sizes = set(TIDMAD.valid_segmentation_sizes())
    assert 16384 not in sizes
    assert 8192 not in sizes
    assert 4096 not in sizes


def test_includes_known_valid_values_for_tidmad():
    """16000, 1250, 1000, 100 are listed in the tuner_advice prose as valid."""
    sizes = set(TIDMAD.valid_segmentation_sizes())
    assert 16000 in sizes
    assert 1250 in sizes
    assert 1000 in sizes
    assert 100 in sizes


def test_respects_lo_hi_bounds():
    sizes = TIDMAD.valid_segmentation_sizes(lo=1000, hi=20000)
    for s in sizes:
        assert 1000 <= s <= 20000
    assert 100 not in sizes
    assert 50000 not in sizes


def test_empty_when_window_excludes_all_divisors():
    """A window that misses every divisor returns an empty list, not a crash."""
    # Pick a window that no integer divisor of 10_000_000 falls into.
    # Divisors of 10_000_000 near 10003 don't exist (10000 and 10240 don't both fit).
    sizes = TIDMAD.valid_segmentation_sizes(lo=10001, hi=10239)
    assert sizes == []


def test_works_for_arbitrary_dataset():
    """Helper is parameterized on DatasetConfig — not tied to TIDMAD constants."""
    cfg = DatasetConfig(
        psd_segment_length=1000,
        segments_per_file=10,
        num_files=5,
        sampling_frequency=100.0,
    )
    sizes = cfg.valid_segmentation_sizes(lo=1, hi=1000)
    # Divisors of 1000: 1, 2, 4, 5, 8, 10, 20, 25, 40, 50, 100, 125, 200, 250, 500, 1000
    assert 100 in sizes
    assert 125 in sizes
    assert 250 in sizes
    assert 500 in sizes
    assert 1000 in sizes
    # Not divisors:
    assert 3 not in sizes
    assert 7 not in sizes
