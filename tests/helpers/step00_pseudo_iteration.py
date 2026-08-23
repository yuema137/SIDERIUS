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


def run_bounded_pseudo_iteration(
    tmp_path,
    monkeypatch,
    preflight_results=None,
    input_overrides=None,
    bridge=None,
    capability_index_path=None,
):
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

    ``input_overrides``: optional mapping merged into the fixture's
    ``HyperparamTuningInput`` kwargs. ``None`` (the default) leaves the
    Step-00 fixture EXACTLY as captured, so every registered baseline that
    replays through this helper is byte-unaffected. Callers that need a
    different SUPPORTED posture (e.g. the Step-07 correction's
    incumbent-formal-gates-on / time-budgets-off regression) pass it here
    rather than forking the harness.

    ``bridge``: optional LLM bridge instance to drive the run with. ``None``
    (the default) uses ``RecordingLLMBridge.for_agent`` exactly as before, so
    every registered Step-00 baseline is byte-unaffected. Step 12 / PR-12a C0
    passes a capturing ``StubLLMBridge`` subclass here because the RECORDING
    double never renders a prompt — it is handed one — and a prompt-BYTE
    baseline has to observe what the real ``plan``/``reflect`` render paths
    actually produced. Forking the harness to get that would have meant two
    harnesses drifting apart.

    ``capability_index_path``: optional loss capability-index path forwarded
    to ``HyperparamTuningAgent``. ``None`` (the default) keeps the production
    default ``agent_generated/_capability_index.json``, so every existing
    baseline is unaffected. A prompt-BYTE baseline MUST pass a pinned path:
    the planner renders the AVAILABLE CUSTOM LOSSES block from this registry,
    and ``agent_generated/`` is machine-local, gitignored, mutable state — a
    committed sha over a prompt that embeds it would pass on the developer's
    box and fail on a fresh CI clone, which is precisely the portability
    failure ``CLAUDE.md`` names.
    """
    import time as _time

    import torch

    from agent.schemas.hyperparam_tuning import HyperparamTuningInput
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
        #
        # The patch target is the tuner's PRIVATE execution module, because
        # that is where the pre-flight call now lives (Step 07 PR 07b, C7d).
        # Patching the main module would bind a name nothing calls, and the
        # real pre-flight would run — so this must follow the code, not the
        # node's public path.
        _tuner = importlib.import_module("nodes.ml_hyperparameter_tune_agent.execution")

        queue = [dict(r) for r in preflight_results]

        def _canned_preflight(**_kwargs):
            if not queue:
                raise AssertionError(
                    "step00 pseudo iteration: preflight fixture queue exhausted "
                    "— the tuner made more pre-flight calls than the capture."
                )
            return queue.pop(0)

        monkeypatch.setattr(_tuner, "run_production_preflight", _canned_preflight)

    # CUDA mock must cover the FULL discovery surface, not just the VRAM
    # gate: `core/hardware_context` calls `device_count()` and
    # `get_device_properties()` once `is_available()` is True, which
    # raises "Found no NVIDIA driver" on driverless CI runners (caught by
    # the first CI run of this helper; invisible locally where a real GPU
    # absorbed the difference, and invisible in k9 which never runs in CI).
    class _FixtureDeviceProps:
        name = "Step00 Mock GPU"
        total_memory = 32 * 1024**3
        major = 8
        minor = 6
        multi_processor_count = 82
        uuid = None

    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 1)
    monkeypatch.setattr(torch.cuda, "get_device_properties", lambda *a, **kw: _FixtureDeviceProps())
    monkeypatch.setattr(torch.cuda, "mem_get_info", lambda *a, **kw: (20 * 1024**3, 32 * 1024**3))
    monkeypatch.setattr(_time, "sleep", lambda *a, **kw: None)

    workspace = str(tmp_path / "workspace")
    os.makedirs(workspace, exist_ok=True)
    run_name = "step00_pseudo"

    agent_input = HyperparamTuningInput(
        **{
            **_fixture_input_kwargs(workspace, run_name),
            **(input_overrides or {}),
        }
    )

    if bridge is None:
        bridge = RecordingLLMBridge.for_agent(PSEUDO_AGENT_FOLDER)
    sandbox = RecordingSandbox.for_model(PLUGIN_MODEL_TYPE, base_dir=workspace, run_name=run_name)
    agent = HyperparamTuningAgent(
        bridge_factory=lambda **kw: bridge,
        sandbox_factory=lambda **kw: sandbox,
        capability_index_path=capability_index_path,
    )
    try:
        output = agent.run(agent_input)
    finally:
        for mt in loaded:
            MODEL_REGISTRY.pop(mt, None)
            PLUGIN_CONFIG_REGISTRY.pop(mt, None)
            PLUGIN_OUTPUT_TYPE_REGISTRY.pop(mt, None)

    return output, bridge, sandbox, workspace


def _fixture_input_kwargs(workspace: str, run_name: str) -> dict:
    """The captured Step-00 tuner input, as keyword arguments.

    Kept as a dict so ``input_overrides`` can replace individual keys
    without the helper growing one parameter per field.
    """
    from agent.schemas.storage import LocalStorageConfig, StorageConfig

    return dict(
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
