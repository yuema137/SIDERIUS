"""V21 PR G G2 — pseudo integration: forecast batch == runtime batch.

One dual-mode tuner iteration (the K.9 invented-model choreography, with
the trial TIME gate enabled) asserting the coherence invariant §0.R.10
restores: within one attempt, the time-gate forecast and the inference
runtime receive the SAME ``inference_batch`` — the current attempt's
probe-derived value captured into ``active_params`` at tuner :4696 —
and the saved record's ``params["inference_batch"]`` carries that same
value.

The record schema carries only the runtime batch (no new record field
is permitted — PR G §2 non-goals), so forecast==runtime is asserted by
capturing the kwargs each skill wrapper actually receives, pass-through
shims around the REAL wrappers. Deleting either hop (the tuner's
``**active_params`` splat into the time skill, or the inference skill's
transport) fails this test — the PR-level transport-contract evidence
for the two live hops (§4 criterion 2).

Pseudo-only: the canned choreography (3 plans + 2 reflects, one
OOM-skip then two successes) is what makes the attempt sequence — and
therefore the capture pairing — deterministic. Real-LLM mode diverges
and is skipped.

Run with:
  .venv/bin/pytest tests/integration/workflows/test_g2_forecast_runtime_batch_pseudo.py -v
"""

from __future__ import annotations

import os

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningInput, HyperparamTuningOutput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from tests.integration.workflows.test_k9_invented_model_dual_mode import (
    _PLUGIN_MODEL_TYPE,
    _PSEUDO_AGENT_FOLDER,
    _disable_sleeps,
    _mock_cuda,
    _register_k9_plugin,
)

pytestmark = pytest.mark.dual_mode


@pytest.mark.dual_mode
def test_time_gate_and_inference_receive_the_same_probed_batch(tmp_path, request, monkeypatch):
    from tests.conftest import _is_real_llm, _is_real_training
    from tests.helpers.recording_llm_bridge import RecordingLLMBridge
    from tests.helpers.recording_sandbox import RecordingSandbox

    if _is_real_llm(request) or _is_real_training(request):
        pytest.skip("G2 coherence pin is a wiring test — pseudo choreography only.")

    _register_k9_plugin(monkeypatch, request)
    _mock_cuda(monkeypatch)
    _disable_sleeps(monkeypatch)

    # Pass-through shims around the REAL skill wrappers, recording the
    # batch each one receives. _run_skill re-imports the wrapper module
    # per call, so patching the module attribute is sufficient.
    import agent.skills.evaluate_time_skill.wrapper as time_wrapper
    import agent.skills.inference_skill.wrapper as inf_wrapper

    forecast_batches: list = []
    runtime_batches: list = []

    real_time_run = time_wrapper.run_skill
    real_inf_run = inf_wrapper.run_skill

    def time_shim(sandbox, **kw):
        forecast_batches.append(kw.get("inference_batch"))
        return real_time_run(sandbox, **kw)

    def inf_shim(sandbox, **kw):
        runtime_batches.append(kw.get("inference_batch"))
        return real_inf_run(sandbox, **kw)

    monkeypatch.setattr(time_wrapper, "run_skill", time_shim)
    monkeypatch.setattr(inf_wrapper, "run_skill", inf_shim)

    workspace = str(tmp_path / "workspace")
    os.makedirs(workspace, exist_ok=True)
    run_name = "g2_coherence"

    agent_input = HyperparamTuningInput(
        model_type=_PLUGIN_MODEL_TYPE,
        max_rounds=2,
        is_trial=True,
        trial_strategy="snapshot",
        trial_portion=0.05,
        train_portion=0.1,
        eval_strategy="snapshot",
        eval_portion=0.05,
        trial_vram_budget_gb=0.3,
        # THE difference from K.9: the time gate is ON in BOTH modes
        # (round 2 is the forced-formal round and reads the formal
        # budget). With no data_dir the wrapper lands on the static path
        # (advisory-only), so the canned choreography is unchanged — but
        # the gate RUNS and its kwargs carry the probed batch.
        trial_time_budget_minutes=60.0,
        formal_time_budget_minutes=60.0,
        health_gate_enabled=False,
        llm_provider="openai",
        llm_model_id="gpt-5-mini",
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=workspace, run_name=run_name),
        ),
        progress_bar=False,
    )

    bridge = RecordingLLMBridge.for_agent(_PSEUDO_AGENT_FOLDER)
    sandbox = RecordingSandbox.for_model(_PLUGIN_MODEL_TYPE, base_dir=workspace, run_name=run_name)
    agent = HyperparamTuningAgent(
        bridge_factory=lambda **kw: bridge, sandbox_factory=lambda **kw: sandbox
    )

    output = agent.run(agent_input)
    assert isinstance(output, HyperparamTuningOutput)

    # Choreography: round 1 attempt 1 OOM-skips BEFORE the time gate, so
    # exactly the two successful attempts reach both skills.
    success_records = [r for r in output.all_records if r.status == "success"]
    assert len(success_records) == 2
    assert len(forecast_batches) == 2, forecast_batches
    assert len(runtime_batches) == 2, runtime_batches

    for i, (forecast_b, runtime_b) in enumerate(
        zip(forecast_batches, runtime_batches, strict=True)
    ):
        assert forecast_b is not None, (
            f"attempt {i}: the time gate received no probed batch — the "
            f"tuner->wrapper hop (:4696 + **active_params) is broken."
        )
        assert forecast_b == runtime_b, (
            f"attempt {i}: forecast priced at batch {forecast_b} but runtime "
            f"ran at {runtime_b} — the §0.R.10 coherence invariant is broken."
        )

    # The record carries the same value (record_params, tuner :4697).
    for rec, runtime_b in zip(success_records, runtime_batches, strict=True):
        assert rec.params.get("inference_batch") == runtime_b
