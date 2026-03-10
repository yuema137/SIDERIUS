"""
Shared pytest fixtures for all test levels.
"""
import numpy as np
import h5py
import pytest


SAMPLE_SIZE = 20   # matches TIDMADDataset default
SEG_SIZE = 1000    # small for speed


@pytest.fixture
def synthetic_h5(tmp_path):
    """
    Creates a minimal ABRA-format HDF5 file for training tests.

    Structure mirrors the real dataset:
      timeseries/channel0001/timeseries  — int8  (noisy SQUID input)
      timeseries/channel0002/timeseries  — int16 (clean injected signal)

    Size: SAMPLE_SIZE * SEG_SIZE = 20000 samples → 1 training segment.
    """
    fpath = tmp_path / "abra_training_0000.h5"
    n_samples = SAMPLE_SIZE * SEG_SIZE  # exactly 1 segment

    rng = np.random.default_rng(42)
    channel1 = rng.integers(-128, 127, size=n_samples, dtype=np.int8)
    channel2 = rng.integers(-128, 127, size=n_samples, dtype=np.int16)

    with h5py.File(fpath, "w") as f:
        ts = f.create_group("timeseries")
        ch1 = ts.create_group("channel0001")
        ch1.create_dataset("timeseries", data=channel1)
        ch2 = ts.create_group("channel0002")
        ch2.create_dataset("timeseries", data=channel2)

    return str(tmp_path), "abra_training_0000.h5"
