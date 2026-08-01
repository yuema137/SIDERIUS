"""Keep the tuner's unit tests on the stubbed side of the new pre-flight
boundary (V20 PR A, A-C4).

Production used to reach the VRAM pre-flight through
``_run_skill("evaluate_vram_skill", …)``, and every test in this package
stubs exactly that. A-C4 moved production to
``run_production_preflight``, which spawns a real isolated worker.

The tests did not fail when that happened — they **hung**. A stub that no
longer intercepts does not raise; it lets the real thing run, and the
real thing here is a subprocess with a 900-second deadline. One run
spawned an actual ``preflight_worker_main`` under
``/tmp/pytest-of-…/preflight_workers/``. Silence looked like slowness.

Rather than rewrite six dispatchers, the new boundary is delegated back
to whatever ``_run_skill`` each test has already patched. Existing stubs,
return dictionaries and assertions are untouched, and no unit test in
this package can start a real worker.
"""

from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def route_preflight_to_run_skill_stub():
    """Delegate ``run_production_preflight`` to the test's ``_run_skill``.

    Resolved at call time, not at patch time, so it picks up whichever
    mock the individual test installed inside its own ``with`` block.
    """
    tuner = importlib.import_module(
        "nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent"
    )

    def _delegate(**kwargs):
        return tuner._run_skill(
            "evaluate_vram_skill",
            None,
            model_type=kwargs.get("model_type"),
            model_config=kwargs.get("model_config"),
            train_config=kwargs.get("train_config"),
            loss_config=kwargs.get("loss_config"),
            vram_budget_gb=kwargs.get("vram_budget_gb"),
            hardware_context=kwargs.get("hardware_context"),
        )

    with patch.object(tuner, "run_production_preflight", side_effect=_delegate):
        yield


@pytest.fixture(autouse=True)
def forbid_real_preflight_worker():
    """Fail fast if anything in this package tries to spawn the worker.

    Without this, a future rewiring reintroduces the hang instead of a
    test failure — and a hang is far harder to attribute than an error.
    """
    isolated = importlib.import_module("agent.skills.evaluate_vram_skill.isolated_probe")

    def _refuse(*_args, **_kwargs):
        raise AssertionError(
            "a unit test attempted to start a real isolated pre-flight worker. "
            "Unit tests must stub the production boundary "
            "(run_production_preflight); spawning the worker means a stub "
            "stopped intercepting, which hangs rather than fails."
        )

    with patch.object(isolated, "run_isolated_preflight", side_effect=_refuse):
        yield
