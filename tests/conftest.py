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

import h5py
import numpy as np
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
    parser.addoption(
        "--real-llm",
        action="store_true",
        default=False,
        help=(
            "Use real LLMBridge (real API calls) in dual-mode tests. "
            "Requires GEMINI_API_KEY. Can be combined independently with "
            "--real-training. See docs/pseudo_test_infra.md §4C."
        ),
    )
    parser.addoption(
        "--real-training",
        action="store_true",
        default=False,
        help=(
            "Use real TidmadSandbox (real subprocess execution) in dual-mode "
            "tests. Requires GPU and TIDMAD data on disk. Can be combined "
            "independently with --real-llm. See docs/pseudo_test_infra.md §4C."
        ),
    )
    parser.addoption(
        "--real-api-call",
        action="store_true",
        default=False,
        help=(
            "Deprecated alias: sets both --real-llm and --real-training. "
            "Use --real-llm / --real-training independently instead."
        ),
    )


def pytest_configure(config):
    """Register custom pytest markers used by the pseudo-full-loop test infra.

    The ``dual_mode`` marker labels integration tests that support BOTH the
    pseudo-mode (recording fakes, default) and real-mode (real LLM and/or real
    subprocess, opt-in via --real-llm / --real-training) execution paths. See
    ``docs/pseudo_test_infra.md`` §4C for the dual-axis design.
    """
    config.addinivalue_line(
        "markers",
        "dual_mode: integration test that supports pseudo mode (default, uses "
        "RecordingLLMBridge + RecordingSandbox) and real mode (uses real "
        "LLMBridge via --real-llm and/or real TidmadSandbox via --real-training, "
        "independently). Distinct from 'real_run' which is real-only.",
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


# ---------------------------------------------------------------------------
# Pseudo-full-loop test helpers (dual-mode integration tests)
# ---------------------------------------------------------------------------
# These are plain functions, not fixtures, so tests can call them with explicit
# arguments (agent_name, model_type, etc.) rather than relying on a fixture
# that has hidden defaults. Each axis — LLM and training — is controlled by
# its own flag and can be switched independently.
#
# Flag matrix (see docs/pseudo_test_infra.md §4C):
#   --real-llm       use real LLMBridge  (needs GEMINI_API_KEY)
#   --real-training  use real TidmadSandbox (needs GPU + data)
#   --real-api-call  deprecated alias: sets both of the above
# ---------------------------------------------------------------------------


def _is_real_llm(request) -> bool:
    """True when the test should use a real LLM API call."""
    return request.config.getoption("--real-llm") or request.config.getoption("--real-api-call")


def _is_real_training(request) -> bool:
    """True when the test should use real subprocess execution."""
    return request.config.getoption("--real-training") or request.config.getoption(
        "--real-api-call"
    )


def make_bridge_factory(request, agent_name: str):
    """Return a bridge factory for the given agent.

    Pseudo by default; pass ``--real-llm`` (or the deprecated
    ``--real-api-call``) for real API calls. Skips the test if the flag is
    set but ``GEMINI_API_KEY`` is absent.

    Args:
        request:    pytest ``request`` fixture (for option access).
        agent_name: agent's CLAUDE.md taxonomy name, e.g.
                    ``"ml_hyperparameter_tune_agent"``. Used to locate the
                    canned pseudo-data under
                    ``tests/pseudo_data/api_call_outputs/{agent_name}/``.

    Returns:
        A callable that matches the ``bridge_factory`` DI parameter used by
        every node constructor.
    """
    if _is_real_llm(request):
        if not os.getenv("GEMINI_API_KEY"):
            pytest.skip("--real-llm requires GEMINI_API_KEY")
        from agent.llm_bridge import LLMBridge

        return LLMBridge
    from tests.helpers.recording_llm_bridge import RecordingLLMBridge

    bridge = RecordingLLMBridge.for_agent(agent_name)
    return lambda **kw: bridge


def make_sandbox_factory(request, model_type: str, base_dir: str, run_name: str):
    """Return a sandbox factory for the given model.

    Pseudo by default; pass ``--real-training`` (or the deprecated
    ``--real-api-call``) for real subprocess execution. Skips the test if
    the flag is set but TIDMAD data is absent.

    Args:
        request:    pytest ``request`` fixture (for option access).
        model_type: built-in model key, e.g. ``"punet"``, ``"wavenet"``.
                    Used to locate canned pseudo-data under
                    ``tests/pseudo_data/train_outputs/{model_type}/``.
        base_dir:   root directory for on-disk artifacts (pass ``tmp_path``).
        run_name:   run identifier scoping per-run subdirectories.

    Returns:
        A callable that matches the ``sandbox_factory`` DI parameter used by
        ``HyperparamTuningAgent``.
    """
    if _is_real_training(request):
        real_path = os.path.join(REAL_DATA_DIR, REAL_DATA_FILE)
        if not os.path.exists(real_path):
            pytest.skip(f"--real-training requires TIDMAD data at {real_path}")
        from core.sandbox_executor import TidmadSandbox

        return TidmadSandbox
    from tests.helpers.recording_sandbox import RecordingSandbox

    sandbox = RecordingSandbox.for_model(model_type, base_dir=base_dir, run_name=run_name)
    return lambda **kw: sandbox
