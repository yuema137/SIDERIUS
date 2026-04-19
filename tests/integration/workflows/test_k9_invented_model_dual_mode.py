"""K.9 — Dual-mode regression test for the K.2.5-8 soft-fallback path.

Exercises the full tuner-gate → record → memory pipeline when the planner
proposes an unregistered ``model_type`` (an invented plugin not present
in ``core/inference_defaults._INFERENCE_BATCH_SIZES``). Pairs with the
canned pseudo-data folder
``tests/pseudo_data/api_call_outputs/ml_hyperparameter_tune_agent_k9_invented/``
and the plugin file ``tests/pseudo_data/plugins/pe_wavenet_delta.py``.

Choreography (see the pseudo-data folder's README for full rationale):
  Round 1: planner picks ``hidden_dim=2048`` → VRAM gate emits the
           K.2.5-8 warning AND verdicts over budget (~151 MB > 100 MB)
           → record saved as ``skipped_oom_risk``; sandbox never reached.
  Round 2: planner reacts by collapsing to ``hidden_dim=128`` → gate
           emits the K.2.5-8 warning again but verdicts under budget
           → time gate passes → ``RecordingSandbox`` returns the canned
           training/inference/scoring trio → reflector returns the
           canned reflection → record saved with ``status="success"``.

This file holds **only K.9.1 — the scaffold**. Layer 1-4 assertions are
added in K.9.2 (same file). For now the test asserts only that the
agent runs end-to-end and produces a populated ``HyperparamTuningOutput``.

Run with:
  .venv/bin/pytest tests/integration/workflows/test_k9_invented_model_dual_mode.py -v -s
  .venv/bin/pytest tests/integration/workflows/test_k9_invented_model_dual_mode.py -v -s --real-llm
"""
from __future__ import annotations

import os
import pytest
from dotenv import load_dotenv

from agent.schemas.hyperparam_tuning import (
    HyperparamTuningInput,
    HyperparamTuningOutput,
)
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent

load_dotenv()

pytestmark = pytest.mark.dual_mode


# Repo-relative path to the K.9 plugin folder. Resolved to absolute at
# fixture time so the env var the subprocess loader reads is unambiguous.
_PLUGIN_DIR_REL = "tests/pseudo_data/plugins"
_PLUGIN_MODEL_TYPE = "pe_wavenet_delta"
_PSEUDO_AGENT_FOLDER = "ml_hyperparameter_tune_agent_k9_invented"


def _register_k9_plugin(monkeypatch, request):
    """Set ``SIDERIUS_PLUGIN_DIRS`` and re-extend the live registries.

    ``ml_models/models_sandbox.py`` auto-runs ``extend_registries`` once at
    import time, but that ran before our env var was set, so the K.9
    plugin would not be in the registry. Re-running with the env var set
    registers it for the duration of the test; the finaliser pops it back
    out so the registry doesn't leak into other tests.
    """
    plugin_dir_abs = os.path.abspath(_PLUGIN_DIR_REL)
    monkeypatch.setenv("SIDERIUS_PLUGIN_DIRS", plugin_dir_abs)

    from ml_models.models_sandbox import MODEL_REGISTRY
    from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
    from ml_models.plugin_loader import (
        extend_registries,
        PLUGIN_OUTPUT_TYPE_REGISTRY,
    )
    loaded = extend_registries(MODEL_REGISTRY, PLUGIN_CONFIG_REGISTRY)

    def _cleanup():
        for mt in loaded:
            MODEL_REGISTRY.pop(mt, None)
            PLUGIN_CONFIG_REGISTRY.pop(mt, None)
            PLUGIN_OUTPUT_TYPE_REGISTRY.pop(mt, None)

    request.addfinalizer(_cleanup)


def _disable_sleeps(monkeypatch):
    """Replace ``time.sleep`` with a no-op for the duration of the test.

    The tuner's main loop sleeps 2 s after a successful round and 5 s
    after a caught exception. Once the canned bridge is exhausted (after
    the 2 plan + 1 reflect calls K.9 needs), the loop spins for another
    ``max_attempts - 2`` iterations before terminating, each one hitting
    the 5 s catch-block sleep. With sleeps neutralised the whole test
    runs in well under a second of wall-clock.
    """
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda *a, **kw: None)


def _mock_cuda(monkeypatch):
    """Make the VRAM gate believe it is on a 32 GB GPU with 20 GB free.

    The K.2.5-8 warning fires before the device check, but the
    over/under-budget verdict path is only reachable when
    ``device == "cuda"`` AND ``torch.cuda.is_available()`` is True.
    The 0.8 × 20 GB = 16 GB defensive cap never binds against the
    operator budget (0.1 GB), so this mock keeps the test
    deterministic on machines without a real GPU.
    """
    import torch
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(
        torch.cuda,
        "mem_get_info",
        lambda *a, **kw: (20 * 1024 ** 3, 32 * 1024 ** 3),
    )


@pytest.mark.dual_mode
def test_invented_model_type_triggers_k2_5_8_fallback_path(
    tmp_path, request, monkeypatch
):
    """K.9.1 scaffold — agent runs the 2-round invented-model_type loop
    end-to-end without crashing.

    Asserts only the bare minimum needed to prove the wiring (plugin
    registration, mocked CUDA, canned bridge + sandbox, schema-valid
    output). Deeper Layer 1-4 assertions on stdout, per-record JSON,
    planner reaction, and ``gate_exhaustion`` land in K.9.2.
    """
    from tests.conftest import _is_real_llm, _is_real_training
    from tests.helpers.recording_llm_bridge import RecordingLLMBridge
    from tests.helpers.recording_sandbox import RecordingSandbox
    from agent.llm_bridge import LLMBridge

    _register_k9_plugin(monkeypatch, request)
    _mock_cuda(monkeypatch)
    _disable_sleeps(monkeypatch)

    workspace = str(tmp_path / "workspace")
    os.makedirs(workspace, exist_ok=True)
    run_name = "k9_invented"

    agent_input = HyperparamTuningInput(
        model_type=_PLUGIN_MODEL_TYPE,
        # ``max_rounds`` must be >= 2 so the agent does NOT promote round 1
        # to formal mode. The agent forces ``plan.is_trial = False`` on the
        # last needed round (``ml_hyperparameter_tune_agent.py:591-595``) so
        # the final round always produces a formal-mode result. K.9 needs
        # round 1 in trial mode so the trial VRAM budget binds — hence
        # max_rounds=2. The bridge is intentionally exhausted after round 2
        # succeeds (only 2 canned plans + 1 reflect); the agent's main loop
        # then spins through the remaining attempts up to
        # ``max_attempts = max_rounds * 3`` and terminates. ``_disable_sleeps``
        # makes that spin instantaneous.
        max_rounds=2,
        is_trial=True,
        trial_strategy="snapshot",
        trial_portion=0.05,
        train_portion=0.1,
        eval_strategy="snapshot",
        eval_portion=0.05,
        # 0.1 GB ceiling is the binding budget; round 1's hidden_dim=2048
        # busts it, round 2's hidden_dim=128 fits. See the K.9.0 README
        # for the param-count math.
        trial_vram_budget_gb=0.1,
        # Time gate kept disabled — K.9 is about VRAM/K.2.5-8, not time.
        trial_time_budget_minutes=None,
        llm_provider="openai",
        llm_model_id="gpt-5-mini",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=workspace, run_name=run_name),
        ),
        progress_bar=False,
    )

    bridge = sandbox = None
    if _is_real_llm(request):
        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("--real-llm requires OPENAI_API_KEY for K.9")
        bridge_factory = LLMBridge
    else:
        bridge = RecordingLLMBridge.for_agent(_PSEUDO_AGENT_FOLDER)
        bridge_factory = lambda **kw: bridge

    if _is_real_training(request):
        pytest.skip(
            "--real-training is not supported for K.9: pe_wavenet_delta is a "
            "test-only plugin, not a registered training target."
        )
    else:
        sandbox = RecordingSandbox.for_model(
            _PLUGIN_MODEL_TYPE, base_dir=workspace, run_name=run_name
        )
        sandbox_factory = lambda **kw: sandbox

    agent = HyperparamTuningAgent(
        bridge_factory=bridge_factory, sandbox_factory=sandbox_factory
    )

    output = agent.run(agent_input)

    # --- Minimum scaffold assertions (Layer 1-4 added in K.9.2) ---
    assert isinstance(output, HyperparamTuningOutput)
    HyperparamTuningOutput.model_validate(output.model_dump())
    assert output.run_name == run_name
    assert output.model_type == _PLUGIN_MODEL_TYPE
    # Round 1 is OOM-skipped; round 2 reaches the sandbox and succeeds.
    # Both rounds are persisted as records.
    assert len(output.all_records) == 2
