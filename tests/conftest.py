"""Shared task-generic pytest fixtures and explicit provider opt-in controls.

Scientific datasets, task-owned executors, and real training qualification
belong to external task packages. Framework tests create their smallest
synthetic input beside the test that owns it; this shared module never selects
a scientific task or dataset.
"""

import os
from pathlib import Path

import pytest

from execute_tools.data_paths import bind_physical_data_root
from execute_tools.dataset_config import (
    bind_dataset_profile,
)
from execute_tools.evaluation_metric import bind_run_metric
from tests.helpers.metric_fixtures import accuracy_like_metric
from tests.helpers.two_family_profile import make_two_family_profile
from workflows.task_config import bind_task_config, load_task_config

_REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# CLI option
# ---------------------------------------------------------------------------


def pytest_addoption(parser):
    parser.addoption(
        "--real-llm",
        action="store_true",
        default=False,
        help=(
            "Use real LLMBridge (real API calls) in dual-mode tests. "
            "Requires the enabled provider credential."
        ),
    )
    parser.addoption(
        "--real-api-call",
        action="store_true",
        default=False,
        help=("Deprecated alias for --real-llm. Use --real-llm instead."),
    )


def pytest_configure(config):
    """Register custom pytest markers used by the pseudo-full-loop test infra.

    The ``dual_mode`` marker labels integration tests whose provider boundary
    can use either a recording fake (default) or a real LLM (explicit opt-in).
    Subprocess and task-data qualification are external-task responsibilities.
    """
    config.addinivalue_line(
        "markers",
        "dual_mode: integration test that supports pseudo mode (default, uses "
        "RecordingLLMBridge) and real-provider mode (uses real LLMBridge via "
        "--real-llm). Distinct from 'real_run' which is real-provider-only.",
    )


def pytest_collection_modifyitems(config, items):
    """Enforce the real_run opt-in contract (docs/pseudo_test_infra.md §4C).

    ``real_run`` tests make real provider/API calls, which can be slow and
    billable. Their in-test guards only skip when API keys are
    ABSENT, so on a machine with keys configured a bare ``pytest tests/``
    would silently launch them. This hook closes that gap: without an
    explicit provider flag (``--real-llm`` or the deprecated
    ``--real-api-call``), every ``real_run`` test is skipped at
    collection time regardless of key availability.
    """
    real_mode = config.getoption("--real-llm") or config.getoption("--real-api-call")
    if real_mode:
        return
    skip_real = pytest.mark.skip(
        reason=(
            "real_run tests need an explicit real-mode flag: "
            "--real-llm (or deprecated --real-api-call)"
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


# ---------------------------------------------------------------------------
# Pseudo/full-provider test helpers
# ---------------------------------------------------------------------------
# These are plain functions so the provider selection remains explicit.
# `--real-api-call` is retained only as a deprecated alias for `--real-llm`.
# ---------------------------------------------------------------------------


def _is_real_llm(request) -> bool:
    """True when the test should use a real LLM API call."""
    return request.config.getoption("--real-llm") or request.config.getoption("--real-api-call")


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
