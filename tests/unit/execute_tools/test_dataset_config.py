"""Tests for execute_tools/dataset_config.py.

Focus: ``DatasetConfig.valid_segmentation_sizes`` — the helper used by both the
proposer-side schema validator and the planner prompt's known-constraints block
— and the filename-pattern validator (PR 2 commit A), which is the only guard
against a pattern that silently maps every file index to the same file.
"""

import pytest
from pydantic import ValidationError

from execute_tools.dataset_config import TIDMAD, DatasetConfig


def _cfg(**overrides) -> DatasetConfig:
    """Minimal non-TIDMAD config; overrides target the pattern fields."""
    base = {
        "psd_segment_length": 1000,
        "segments_per_file": 10,
        "num_files": 5,
        "sampling_frequency": 100.0,
    }
    return DatasetConfig(**{**base, **overrides})


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


# ---- filename-pattern validation (PR 2 commit A) ----


@pytest.mark.parametrize(
    "pattern",
    [
        "abra_training_{file_index:04d}.h5",  # the TIDMAD default
        "training_{file_index}.h5",  # bare field
        "training_{file_index:04d}.h5",  # zero-padded
        "{file_index}.h5",  # field only
        "sub/dir/f_{file_index:02d}.hdf5",  # nested path, different suffix
    ],
)
def test_valid_patterns_accepted(pattern):
    cfg = _cfg(training_file_pattern=pattern)
    assert cfg.training_file_pattern == pattern


def test_missing_placeholder_rejected():
    """The silent-corruption case: str.format() would NOT raise here, so every
    file index would resolve to the same filename."""
    with pytest.raises(ValidationError) as exc:
        _cfg(training_file_pattern="training_file.h5")
    message = str(exc.value)
    assert "no {file_index} replacement field" in message
    assert "silently" in message


def test_missing_placeholder_rejected_on_validation_pattern_too():
    with pytest.raises(ValidationError) as exc:
        _cfg(validation_file_pattern="validation_file.h5")
    assert "validation_file_pattern" in str(exc.value)


def test_positional_field_rejected():
    """'{0}' parses as a field but cannot format with a keyword index."""
    with pytest.raises(ValidationError) as exc:
        _cfg(training_file_pattern="{0}.h5")
    assert "no {file_index} replacement field" in str(exc.value)


def test_unknown_extra_field_rejected():
    """Caught by the format probe — would otherwise KeyError at training time."""
    with pytest.raises(ValidationError) as exc:
        _cfg(training_file_pattern="{file_index}_{other}.h5")
    assert "does not format with an integer index" in str(exc.value)


def test_bad_format_spec_rejected():
    """Caught by the format probe — would otherwise ValueError at training time."""
    with pytest.raises(ValidationError) as exc:
        _cfg(training_file_pattern="{file_index:04q}.h5")
    assert "does not format with an integer index" in str(exc.value)


def test_index_access_on_file_index_rejected():
    """Base name is 'file_index' so presence passes; the probe rejects it."""
    with pytest.raises(ValidationError) as exc:
        _cfg(training_file_pattern="{file_index[0]}.h5")
    assert "does not format with an integer index" in str(exc.value)


def test_malformed_format_string_rejected():
    """Unterminated brace: Formatter().parse itself raises."""
    with pytest.raises(ValidationError) as exc:
        _cfg(training_file_pattern="training_{file_index.h5")
    assert "not a valid format string" in str(exc.value)


# ---- training_file_name ----


def test_training_file_name_matches_tidmad_legacy_literal():
    """The refactor must reproduce the inlined f-string byte for byte, for
    every index in the dataset — this is the PR 2 commit A parity contract."""
    for file_index in range(TIDMAD.num_files):
        assert TIDMAD.training_file_name(file_index) == f"abra_training_{file_index:04d}.h5"


def test_training_file_name_uses_the_configs_own_pattern():
    """Not tied to TIDMAD: a second dataset's pattern drives the name."""
    cfg = _cfg(training_file_pattern="run_{file_index:02d}.hdf5")
    assert cfg.training_file_name(3) == "run_03.hdf5"
