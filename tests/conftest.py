"""
Shared pytest fixtures for all test levels.

Data modes
----------
By default all training tests use a tiny synthetic HDF5 file with random
noise (fast, no real data required). Pass --real-data to switch to the
explicitly configured ``SIDERIUS_TEST_DATA_DIR`` resource. When the variable
is absent the optional lane skips visibly. When it is set but invalid, the
qualification fails before execution rather than silently turning green:

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
from pathlib import Path

import h5py
import numpy as np
import pytest

from execute_tools.data_paths import bind_physical_data_root
from execute_tools.dataset_config import (
    bind_dataset_profile,
    resolve_dataset_profile,
    tidmad_topology,
)
from execute_tools.evaluation_metric import bind_run_metric
from tests.helpers.configured_resource import (
    require_configured_directory,
    require_resource_file,
)
from tests.helpers.metric_fixtures import accuracy_like_metric
from tests.helpers.two_family_profile import make_two_family_profile
from workflows.task_config import bind_task_config, load_task_config

_REPO_ROOT = Path(__file__).resolve().parents[1]

REAL_DATA_ENV_VAR = "SIDERIUS_TEST_DATA_DIR"
REAL_DATA_FILE = "abra_training_0000.h5"


def _require_real_data_dir(flag: str) -> str:
    """The configured external data directory, or an informative skip/failure.

    Only ever called from behind ``--real-data`` / ``--real-training``; the
    default run never resolves ``SIDERIUS_TEST_DATA_DIR`` at all.
    """
    return str(require_configured_directory(REAL_DATA_ENV_VAR, requested_by=flag))


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


def pytest_collection_modifyitems(config, items):
    """Enforce the real_run opt-in contract (docs/pseudo_test_infra.md §4C).

    ``real_run`` tests make real LLM API calls and/or run real training —
    slow and billable. Their in-test guards only skip when API keys are
    ABSENT, so on a machine with keys configured a bare ``pytest tests/``
    would silently launch them. This hook closes that gap: without an
    explicit real-mode flag (``--real-llm``, ``--real-training``, or the
    deprecated ``--real-api-call``), every ``real_run`` test is skipped at
    collection time regardless of key availability.
    """
    real_mode = (
        config.getoption("--real-llm")
        or config.getoption("--real-training")
        or config.getoption("--real-api-call")
    )
    if real_mode:
        return
    skip_real = pytest.mark.skip(
        reason=(
            "real_run tests need an explicit real-mode flag: "
            "--real-api-call (or --real-llm / --real-training)"
        )
    )
    for item in items:
        if "real_run" in item.keywords:
            item.add_marker(skip_real)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def synthetic_dataset_profile():
    """Bind the neutral indexed-data profile for tests that request it.

    This fixture is deliberately not autouse.  A test module that exercises a
    profile-sensitive boundary must opt in with either a fixture argument or
    ``pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")``.
    Keeping the dependency visible prevents framework tests from recreating an
    ambient scientific-task default merely to make legacy fixtures pass.
    """
    profile = make_two_family_profile(num_files=20, psd_segment_length=200_000)
    with bind_dataset_profile(profile):
        yield profile


@pytest.fixture(scope="module")
def synthetic_task_config(synthetic_dataset_profile):
    """Bind the framework's explicit, task-neutral configuration example.

    Depending on ``synthetic_dataset_profile`` makes both prerequisites
    visible and orders their context bindings before broader module/class
    fixtures execute.  This is still opt-in; it is not a repository-wide
    scientific default.
    """
    config_path = _REPO_ROOT / "configs" / "task_config.example.yaml"
    config = load_task_config(str(config_path))
    patcher = pytest.MonkeyPatch()
    patcher.setattr(
        "workflows.task_config.default_task_config_path",
        lambda: str(config_path),
    )
    try:
        with bind_task_config(config):
            yield config
    finally:
        patcher.undo()


@pytest.fixture(scope="module")
def synthetic_run_authorities(synthetic_task_config):
    """Bind the neutral primary metric required by composed-run unit tests."""
    metric = accuracy_like_metric()
    with bind_run_metric(metric):
        yield metric


@pytest.fixture(scope="module")
def synthetic_physical_data_root(tmp_path_factory):
    """Bind an empty, caller-owned data root for executor plumbing tests.

    The directory is intentionally empty: tests using this fixture exercise
    command construction, persistence, or a stub executor and must not read a
    scientific dataset.  A test that needs bytes must create its own declared
    fixture and bind the corresponding task data-path implementation instead.
    """
    root = tmp_path_factory.mktemp("explicit_physical_data_root")
    with bind_physical_data_root(str(root)):
        yield root


@pytest.fixture(autouse=True, scope="session")
def _isolate_calibration_registry(tmp_path_factory):
    """No test may touch the operator's real calibration registry.

    `CalibrationRegistry()` with no root resolves to
    `$SIDERIUS_CALIBRATION_DIR` or `$HOME/.siderius/...`, and production
    constructs one that way (`ml_hyperparameter_tune_agent`, the V20 PR C1
    calibration derivation). So ANY test that drives the agent -- not only
    the calibration tests -- reaches the real tree.

    Found exactly that way: a full-suite run created a live
    `~/.siderius/runtime_calibration_v2` directory. A per-module fixture was
    not enough, because the writer is production code reached from the tuner
    suite. Session-scoped and autouse so the protection does not depend on
    each future test remembering it.

    The live v1 tree is preserved evidence -- 20 observations that document
    an uncalibrated system -- and rebuilding or appending to it would
    destroy what several V20 findings rest on.

    TESTING DEFAULT PATH RESOLUTION. This fixture pins the override, so a
    test of the un-overridden rule must delete the variable itself and
    redirect `$HOME`, or it will silently assert the override branch and
    prove nothing about the default. See
    `test_calibration_registry.py::test_the_default_rule_applies_when_no_override_is_set`.
    Every other test writes into the temporary root.
    """
    root = tmp_path_factory.mktemp("calibration_registry_isolation")
    previous = os.environ.get("SIDERIUS_CALIBRATION_DIR")
    os.environ["SIDERIUS_CALIBRATION_DIR"] = str(root)
    try:
        yield root
    finally:
        if previous is None:
            os.environ.pop("SIDERIUS_CALIBRATION_DIR", None)
        else:
            os.environ["SIDERIUS_CALIBRATION_DIR"] = previous


@pytest.fixture(autouse=True, scope="session")
def _isolate_generated_library(tmp_path_factory):
    """No test may touch the operator's real generated-capability library.

    arXiv P1: with no override, ``core.generated_library`` resolves to
    ``$HOME/.siderius/generated_library`` — and production constructs paths
    that way (capability-index default, promotion writers, preloads, the
    loss-union scan). So ANY test that drives the workflow or the loaders —
    not only the generated-library tests — would otherwise read whatever the
    operator's real library has accumulated (nondeterministic absorption)
    and could write promotions into it (the durable-state analogue of the
    checkout pollution P1 removes).

    Same failure class and same shape as ``_isolate_calibration_registry``
    directly above: session-scoped and autouse so the protection does not
    depend on each future test remembering it.

    TESTING DEFAULT PATH RESOLUTION. This fixture pins the override, so a
    test of the un-overridden rule must delete the variable itself (see
    ``tests/unit/core/test_generated_library.py``). Every other test either
    writes into this temporary root or pins its own.
    """
    root = tmp_path_factory.mktemp("generated_library_isolation")
    previous = os.environ.get("SIDERIUS_GENERATED_LIBRARY_DIR")
    os.environ["SIDERIUS_GENERATED_LIBRARY_DIR"] = str(root)
    try:
        yield root
    finally:
        if previous is None:
            os.environ.pop("SIDERIUS_GENERATED_LIBRARY_DIR", None)
        else:
            os.environ["SIDERIUS_GENERATED_LIBRARY_DIR"] = previous


@pytest.fixture(autouse=True)
def _restore_generated_library_binding_after_test():
    """Prevent a workflow entry point from leaking its workspace to later tests."""
    names = ("SIDERIUS_GENERATED_LIBRARY_DIR", "SIDERIUS_CHAIN_WORKSPACE")
    previous = {name: os.environ.get(name) for name in names}
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


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
        topology = tidmad_topology(resolve_dataset_profile())
        filename = topology.dataset.training_file_name(0)
        fpath = tmp_path / filename
        n_samples = SYNTH_SAMPLE_SIZE * seg_size

        rng = np.random.default_rng(42)
        values = rng.integers(-128, 127, size=n_samples, dtype=np.int16)

        with h5py.File(fpath, "w") as f:
            ts = f.create_group("timeseries")
            input_group = ts.create_group(topology.channels.input_channel)
            input_group.create_dataset("timeseries", data=values)
            target_group = ts.create_group(topology.channels.target_channel)
            target_group.create_dataset("timeseries", data=values.copy())

        return str(tmp_path), filename

    return _make


@pytest.fixture
def h5_source(request, synthetic_h5):
    """
    Unified data fixture for training tests.

    Returns a callable(seg_size) -> (data_dir, filename):
      - Synthetic (default): generates random noise sized to the model's seg_size
      - Real (--real-data):  ignores seg_size and points to the actual TIDMAD file

    Tests using this fixture are automatically marked "real_data" when
    --real-data is active. An unconfigured optional resource skips; an
    explicitly configured missing directory or file fails.
    """
    if request.config.getoption("--real-data"):
        data_dir = _require_real_data_dir("--real-data")
        require_resource_file(Path(data_dir), REAL_DATA_FILE, requested_by="--real-data")
        request.node.add_marker(pytest.mark.real_data)

        def _real(seg_size: int):
            return data_dir, REAL_DATA_FILE

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
    ``--real-api-call``) for real subprocess execution. An unconfigured
    optional resource skips; an explicitly configured invalid resource fails.

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
        data_dir = _require_real_data_dir("--real-training")
        require_resource_file(Path(data_dir), REAL_DATA_FILE, requested_by="--real-training")
        from core.sandbox_executor import TidmadSandbox

        return TidmadSandbox
    from tests.helpers.recording_sandbox import RecordingSandbox

    sandbox = RecordingSandbox.for_model(model_type, base_dir=base_dir, run_name=run_name)
    return lambda **kw: sandbox
