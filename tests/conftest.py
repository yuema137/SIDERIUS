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
    parser.addoption(
        "--real-api-call",
        action="store_true",
        default=False,
        help=(
            "Run dual-mode integration tests against the real LLM API and real "
            "subprocess execution (training/inference/scoring). Requires API keys "
            "and GPU. Default: pseudo mode (recording fakes from tests/helpers/). "
            "See docs/pseudo_test_infra.md for the dual-mode design."
        ),
    )


def pytest_configure(config):
    """Register custom pytest markers used by the pseudo-full-loop test infra.

    The ``dual_mode`` marker labels integration tests that support BOTH the
    pseudo-mode (recording fakes, default) and real-mode (real LLM + real
    subprocess, opt-in via ``--real-api-call``) execution paths. See
    ``docs/pseudo_test_infra.md`` §4C for the orthogonal-axes design.
    """
    config.addinivalue_line(
        "markers",
        "dual_mode: integration test that supports both pseudo mode (default, "
        "uses RecordingLLMBridge + RecordingSandbox) and real mode (uses real "
        "LLMBridge + TidmadSandbox; requires --real-api-call). Distinct from "
        "the existing 'real_run' marker which is for real-only tests.",
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
# Pseudo-full-loop test fixtures (dual-mode integration tests)
# ---------------------------------------------------------------------------

@pytest.fixture
def tuner_factories(request, tmp_path):
    """Factory pair for dual-mode tuner integration tests.

    Returns ``{"bridge_factory": ..., "sandbox_factory": ...}`` — the two
    callables a dual-mode test passes into ``HyperparamTuningAgent`` (or any
    other consumer of LLMBridge + TidmadSandbox).

    Mode selection:
      * **Pseudo mode (default)**: returns
        ``{"bridge_factory": <RecordingLLMBridge factory>, "sandbox_factory":
        <RecordingSandbox factory>}``. The bridge factory builds a recording
        bridge pre-loaded from ``tests/pseudo_data/api_call_outputs/
        ml_hyperparameter_tune_agent/``; the sandbox factory builds a
        recording sandbox under the test's ``tmp_path``, pre-loaded from
        ``tests/pseudo_data/train_outputs/{model_type}/``. The factories
        accept any ``**kwargs`` the agent passes (provider, model_id,
        base_dir, run_name, etc.) and silently ignore the ones the recording
        fakes don't need.
      * **Real mode (``--real-api-call``)**: returns the real ``LLMBridge``
        and ``TidmadSandbox`` classes themselves. The agent's existing
        constructor signature is preserved bit-for-bit; the test runs
        end-to-end against the real API and real subprocesses, exactly as
        it does today.

    Pseudo-mode usage assumes the consumer is the tuner agent and the model
    type is ``"punet"`` (the only model with v1 canned data in this PR). When
    other models gain canned data in follow-up PRs, callers can pass an
    explicit ``model_type`` keyword to the sandbox factory and the recording
    sandbox will load the matching ``train_outputs/{model_type}/`` directory.
    """
    if request.config.getoption("--real-api-call"):
        # Real mode: return the real classes. Agent constructs them directly
        # via self._bridge_factory(...) / self._sandbox_factory(...) — no
        # behavioral change from today.
        from agent.llm_bridge import LLMBridge
        from core.sandbox_executor import TidmadSandbox
        return {"bridge_factory": LLMBridge, "sandbox_factory": TidmadSandbox}

    # Pseudo mode: return factory closures that build pre-loaded recording fakes.
    from tests.helpers.recording_llm_bridge import RecordingLLMBridge
    from tests.helpers.recording_sandbox import RecordingSandbox

    def _bridge_factory(**kwargs):
        # Pre-load the bridge with the canned outputs for the tuner agent.
        # The agent's call (e.g. with provider/model_id/reflect_*) is ignored
        # by the recording bridge's **kwargs, so this is a clean drop-in.
        return RecordingLLMBridge.for_agent("ml_hyperparameter_tune_agent")

    def _sandbox_factory(**kwargs):
        # Pre-load the sandbox with the canned outputs for the model type.
        # Default to punet (the only v1 canned model). The agent passes
        # base_dir/run_name/file_index/etc.; we honor base_dir if given,
        # otherwise route to the test's tmp_path. file_index and other
        # real-sandbox params are silently swallowed by **kwargs.
        model_type = kwargs.pop("model_type", "punet")
        base_dir = kwargs.pop("base_dir", str(tmp_path))
        run_name = kwargs.pop("run_name", "test")
        return RecordingSandbox.for_model(
            model_type=model_type,
            base_dir=base_dir,
            run_name=run_name,
            **kwargs,
        )

    return {"bridge_factory": _bridge_factory, "sandbox_factory": _sandbox_factory}
