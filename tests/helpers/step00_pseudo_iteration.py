"""Shared bounded pseudo tuner iteration for Step-00 baselines.

Design: ``docs/design/generic_framework_upgrade/step_00_golden_baseline_harness.md``
§22.1 (OD-2 outcome A) / §13.5. One bounded pseudo run of the PRODUCTION
tuner (``HyperparamTuningAgent.run``) with ``RecordingLLMBridge`` +
``RecordingSandbox`` — the same wiring as the registered k9 choreography —
so every record funnels through the real ``_emit_record`` seam and every
``plan()``/``reflect()`` call crosses the real call sites.

Consumers: REC-2/REC-3/REC-4 (0C record baselines) and WF-1/WF-2/WF-3
(0E kwargs/label baselines). Unit-tier: no network (canned bridge), no
GPU (CUDA mocked), sub-second (sleeps disabled), all writes under the
caller's tmp_path.

The input mirrors the k9 fixture exactly, so the canned response queues
(3 plans + 2 reflects; OOM-skip → trial success → formal success) stay in
sync with their pseudo-data files. The machine-calibrated
``trial_vram_budget_gb=0.3`` ceiling is a FIXTURE INPUT, never asserted
as a contract (design §12.1 class 5).
"""

from __future__ import annotations

import os

PLUGIN_MODEL_TYPE = "pe_wavenet_delta"
PSEUDO_AGENT_FOLDER = "ml_hyperparameter_tune_agent_k9_invented"
_PLUGIN_DIR_REL = os.path.join("tests", "pseudo_data", "plugins")


def run_bounded_pseudo_iteration(tmp_path, monkeypatch, preflight_results=None):
    """Run one bounded pseudo tuner iteration; return (output, bridge, sandbox, workspace).

    The caller's ``monkeypatch`` scopes the env/CUDA/sleep patches; the
    plugin-registry extension is popped back out before returning (no
    registry leakage into other tests).

    ``preflight_results``: optional FIFO list of legacy preflight dicts to
    stub ``run_production_preflight`` with. REQUIRED under the unit tier —
    the tuner package's autouse guard forbids the real isolated pre-flight
    worker there (its sanctioned pattern is stubbing this exact boundary).
    The committed fixture (``fixtures/step00_preflight_results.json``) was
    captured from the REAL adapter during a live pseudo run, so the stub
    is production-shaped and machine-independent. ``None`` = real path
    (usable outside pytest / at the integration tier).
    """
    import time as _time

    import torch

    from agent.schemas.hyperparam_tuning import HyperparamTuningInput
    from agent.schemas.storage import LocalStorageConfig, StorageConfig
    from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
    from ml_models.models_sandbox import MODEL_REGISTRY
    from ml_models.plugin_loader import PLUGIN_OUTPUT_TYPE_REGISTRY, extend_registries
    from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
        HyperparamTuningAgent,
    )
    from tests.helpers.recording_llm_bridge import RecordingLLMBridge
    from tests.helpers.recording_sandbox import RecordingSandbox

    monkeypatch.setenv("SIDERIUS_PLUGIN_DIRS", os.path.abspath(_PLUGIN_DIR_REL))
    loaded = extend_registries(MODEL_REGISTRY, PLUGIN_CONFIG_REGISTRY)

    if preflight_results is not None:
        import importlib

        # importlib because the package __init__ re-exports shadow the
        # module name (same quirk the tuner unit conftest works around).
        _tuner = importlib.import_module(
            "nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent"
        )

        queue = [dict(r) for r in preflight_results]

        def _canned_preflight(**_kwargs):
            if not queue:
                raise AssertionError(
                    "step00 pseudo iteration: preflight fixture queue exhausted "
                    "— the tuner made more pre-flight calls than the capture."
                )
            return queue.pop(0)

        monkeypatch.setattr(_tuner, "run_production_preflight", _canned_preflight)

    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "mem_get_info", lambda *a, **kw: (20 * 1024**3, 32 * 1024**3))
    monkeypatch.setattr(_time, "sleep", lambda *a, **kw: None)

    workspace = str(tmp_path / "workspace")
    os.makedirs(workspace, exist_ok=True)
    run_name = "step00_pseudo"

    agent_input = HyperparamTuningInput(
        model_type=PLUGIN_MODEL_TYPE,
        max_rounds=2,
        is_trial=True,
        trial_strategy="snapshot",
        trial_portion=0.05,
        train_portion=0.1,
        eval_strategy="snapshot",
        eval_portion=0.05,
        trial_vram_budget_gb=0.3,
        trial_time_budget_minutes=None,
        health_gate_enabled=False,
        llm_provider="openai",
        llm_model_id="gpt-5-mini",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=workspace, run_name=run_name),
        ),
        progress_bar=False,
    )

    bridge = RecordingLLMBridge.for_agent(PSEUDO_AGENT_FOLDER)
    sandbox = RecordingSandbox.for_model(PLUGIN_MODEL_TYPE, base_dir=workspace, run_name=run_name)
    agent = HyperparamTuningAgent(
        bridge_factory=lambda **kw: bridge, sandbox_factory=lambda **kw: sandbox
    )
    try:
        output = agent.run(agent_input)
    finally:
        for mt in loaded:
            MODEL_REGISTRY.pop(mt, None)
            PLUGIN_CONFIG_REGISTRY.pop(mt, None)
            PLUGIN_OUTPUT_TYPE_REGISTRY.pop(mt, None)

    return output, bridge, sandbox, workspace
