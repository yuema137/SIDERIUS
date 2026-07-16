"""Shared HDF5-peek primitives — choose_peek_file_index + peek_int8_at_path.

Covers the two functions in ``execute_tools/health_checks/_peek.py``:
    * ``choose_peek_file_index(ctx)`` — file_index selection (AMB-4-5 → A)
    * ``peek_int8_at_path(path, peek_samples)`` — pure HDF5 read;
      raises OSError / KeyError on failure so the caller can construct
      an informative failure result.

See ``docs/design/pluggable_health_checks.md`` §9 for the peek design.
"""

from __future__ import annotations

import h5py
import numpy as np
import pytest

from execute_tools.health_checks._peek import (
    choose_peek_file_index,
    peek_int8_at_channel,
    peek_int8_at_path,
)
from execute_tools.health_checks.schemas import HealthCheckContext


def _write_denoised_h5(path, ch1: np.ndarray) -> None:
    """Write a minimal denoised HDF5 with ``channel0001/timeseries`` populated."""
    with h5py.File(str(path), "w") as f:
        ts = f.create_group("timeseries")
        c1 = ts.create_group("channel0001")
        c1.create_dataset("timeseries", data=ch1, chunks=True)


def _write_two_channel_h5(path, ch1: np.ndarray, ch2: np.ndarray) -> None:
    """Write an HDF5 with both channel0001 and channel0002 populated —
    matches the shape of ground-truth validation files used for pearson."""
    with h5py.File(str(path), "w") as f:
        ts = f.create_group("timeseries")
        c1 = ts.create_group("channel0001")
        c1.create_dataset("timeseries", data=ch1, chunks=True)
        c2 = ts.create_group("channel0002")
        c2.create_dataset("timeseries", data=ch2, chunks=True)


def _ctx(**overrides) -> HealthCheckContext:
    base = {"model_name": "m", "run_name": "r", "round_index": 1}
    base.update(overrides)
    return HealthCheckContext(**base)


# ---------------------------------------------------------------------------
# choose_peek_file_index
# ---------------------------------------------------------------------------


class TestChoosePeekFileIndex:
    def test_defaults_to_zero_when_paths_empty(self):
        assert choose_peek_file_index(_ctx()) == 0

    def test_min_key_when_paths_non_empty(self):
        ctx = _ctx(denoised_paths={7: "a.h5", 3: "b.h5", 5: "c.h5"})
        assert choose_peek_file_index(ctx) == 3

    def test_zero_key_wins_when_present(self):
        ctx = _ctx(denoised_paths={0: "a.h5", 5: "b.h5"})
        assert choose_peek_file_index(ctx) == 0


# ---------------------------------------------------------------------------
# peek_int8_at_path
# ---------------------------------------------------------------------------


class TestPeekInt8AtPath:
    def test_returns_int8_samples_for_valid_hdf5(self, tmp_path):
        p = tmp_path / "d.h5"
        _write_denoised_h5(p, np.arange(-10, 10, dtype=np.int8).repeat(100))
        samples = peek_int8_at_path(str(p), peek_samples=500)
        assert samples.dtype == np.int8
        assert samples.shape[0] == 500

    def test_bounded_by_dataset_size(self, tmp_path):
        """Request more than the dataset holds — get the dataset."""
        p = tmp_path / "d.h5"
        _write_denoised_h5(p, np.zeros(100, dtype=np.int8))
        samples = peek_int8_at_path(str(p), peek_samples=100_000)
        assert samples.shape[0] == 100

    def test_peek_zero_returns_empty(self, tmp_path):
        p = tmp_path / "d.h5"
        _write_denoised_h5(p, np.zeros(100, dtype=np.int8))
        samples = peek_int8_at_path(str(p), peek_samples=0)
        assert samples.shape[0] == 0

    def test_missing_file_raises_oserror(self, tmp_path):
        bogus = str(tmp_path / "does_not_exist.h5")
        with pytest.raises(OSError):
            peek_int8_at_path(bogus, peek_samples=100)

    def test_missing_dataset_raises_keyerror(self, tmp_path):
        """Valid HDF5 but ``timeseries/channel0001/timeseries`` walk fails."""
        p = tmp_path / "wrong_shape.h5"
        with h5py.File(str(p), "w") as f:
            f.create_group("wrong_group")
        with pytest.raises(KeyError):
            peek_int8_at_path(str(p), peek_samples=100)

    def test_partial_dataset_structure_raises_keyerror(self, tmp_path):
        """Second step of the walk fails (top-level ``timeseries`` exists
        but ``channel0001`` under it does not)."""
        p = tmp_path / "partial.h5"
        with h5py.File(str(p), "w") as f:
            f.create_group("timeseries")  # missing channel0001 subgroup
        with pytest.raises(KeyError):
            peek_int8_at_path(str(p), peek_samples=100)


# ---------------------------------------------------------------------------
# peek_int8_at_channel — generalised primitive (M8 §3.4)
# ---------------------------------------------------------------------------


class TestPeekInt8AtChannel:
    def test_reads_channel0001_matching_wrapper(self, tmp_path):
        p = tmp_path / "d.h5"
        ch1 = np.arange(-5, 5, dtype=np.int8).repeat(50)
        _write_two_channel_h5(p, ch1=ch1, ch2=np.zeros(500, dtype=np.int8))
        s = peek_int8_at_channel(str(p), "channel0001", peek_samples=500)
        wrapped = peek_int8_at_path(str(p), peek_samples=500)
        np.testing.assert_array_equal(s, wrapped)

    def test_reads_channel0002_distinct_data(self, tmp_path):
        p = tmp_path / "d.h5"
        ch1 = np.full(500, 1, dtype=np.int8)
        ch2 = np.full(500, -50, dtype=np.int8)
        _write_two_channel_h5(p, ch1=ch1, ch2=ch2)
        s = peek_int8_at_channel(str(p), "channel0002", peek_samples=500)
        assert s.dtype == np.int8
        assert s.shape[0] == 500
        assert int(s[0]) == -50
        assert int(s[-1]) == -50

    def test_missing_channel_key_raises_keyerror(self, tmp_path):
        p = tmp_path / "only_ch1.h5"
        _write_denoised_h5(p, np.zeros(100, dtype=np.int8))
        with pytest.raises(KeyError):
            peek_int8_at_channel(str(p), "channel0002", peek_samples=100)

    def test_peek_zero_returns_empty(self, tmp_path):
        p = tmp_path / "d.h5"
        _write_two_channel_h5(p, np.zeros(100, dtype=np.int8), np.zeros(100, dtype=np.int8))
        s = peek_int8_at_channel(str(p), "channel0002", peek_samples=0)
        assert s.shape[0] == 0

    def test_missing_file_raises_oserror(self, tmp_path):
        bogus = str(tmp_path / "does_not_exist.h5")
        with pytest.raises(OSError):
            peek_int8_at_channel(bogus, "channel0001", peek_samples=100)
