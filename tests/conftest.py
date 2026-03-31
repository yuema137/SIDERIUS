"""
Shared pytest fixtures for all test levels.

Data modes
----------
By default all training tests use a tiny synthetic HDF5 file with random
noise (fast, no real data required). Pass --real-data to switch to the
actual TIDMAD file at /home/klz/Data/TIDMAD/abra_training_0000.h5:

    uv run pytest tests/integration/execute_tools/test_training_loop.py --real-data

Real-data tests are also tagged with the "real_data" marker so you can
select or deselect them explicitly:

    uv run pytest -m real_data          # only real-data runs
    uv run pytest -m "not real_data"    # only synthetic runs (default)

Note on synthetic vs real data
-------------------------------
- Synthetic (default): random noise, sample_size=1, seg_size from model config.
  Purpose: verify the training loop runs without errors (forward/backward pass,
  model save/load). Not for optimisation — data quality does not matter.
- Real (--real-data): actual TIDMAD abra_training_0000.h5, seg_size=40000.
  Purpose: verify the full pipeline with realistic data distribution. Slow.
"""
import os
import numpy as np
import h5py
import pytest


try:
    from execute_tools.data_paths import TIDMAD_DATA_DIR
    REAL_DATA_DIR = TIDMAD_DATA_DIR
except (FileNotFoundError, ImportError):
    REAL_DATA_DIR = "/home/klz/Data/TIDMAD/"
REAL_DATA_FILE = "abra_training_0000.h5"

# Number of consecutive samples forming one group in TIDMADDataset.
# Use 1 for synthetic tests so the fixture only needs seg_size samples total.
SYNTH_SAMPLE_SIZE = 1


# ---------------------------------------------------------------------------
# CLI option
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption(
        "--real-data",
        action="store_true",
        default=False,
        help="Run training tests against the real TIDMAD HDF5 file instead of synthetic data.",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_h5(tmp_path):
    """
    Factory that returns a callable for creating a synthetic HDF5 file.

    The caller passes the required seg_size (from the model config) so the
    fixture generates exactly SYNTH_SAMPLE_SIZE * seg_size samples — enough
    for 1 training segment regardless of model architecture.

    Usage in tests:
        def test_foo(synthetic_h5):
            data_dir, fname = synthetic_h5(seg_size=model_cfg.segmentation_size)
    """
    def _make(seg_size: int):
        fpath = tmp_path / REAL_DATA_FILE
        n_samples = SYNTH_SAMPLE_SIZE * seg_size

        rng = np.random.default_rng(42)
        channel1 = rng.integers(-128, 127, size=n_samples, dtype=np.int8)
        channel2 = rng.integers(-128, 127, size=n_samples, dtype=np.int16)

        with h5py.File(fpath, "w") as f:
            ts = f.create_group("timeseries")
            ch1 = ts.create_group("channel0001")
            ch1.create_dataset("timeseries", data=channel1)
            ch2 = ts.create_group("channel0002")
            ch2.create_dataset("timeseries", data=channel2)

        return str(tmp_path), REAL_DATA_FILE

    return _make


@pytest.fixture
def h5_source(request, synthetic_h5):
    """
    Unified data fixture for training tests.

    Returns a callable(seg_size) -> (data_dir, filename):
      - Synthetic (default): generates random noise sized to the model's seg_size
      - Real (--real-data):  ignores seg_size and points to the actual TIDMAD file

    Tests using this fixture are automatically marked "real_data" when
    --real-data is active, and skipped if the file is missing.
    """
    if request.config.getoption("--real-data"):
        real_path = os.path.join(REAL_DATA_DIR, REAL_DATA_FILE)
        if not os.path.exists(real_path):
            pytest.skip(f"Real data not found at {real_path}")
        request.node.add_marker(pytest.mark.real_data)
        def _real(seg_size: int):
            return REAL_DATA_DIR, REAL_DATA_FILE
        return _real
    return synthetic_h5
