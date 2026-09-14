"""Pseudo integration: measured preflight batch reaches runtime and records.

One pseudo tuner iteration uses three supplied isolated-preflight outcomes:
one capacity refusal followed by two completed attempts. It asserts that the
preflight-selected ``inference_batch`` reaches the actual sandbox inference
boundary and the persisted record.

The historical version also entered the TIDMAD-only forecast estimator. A
task-generic composed fixture has no legacy ``SampleSet``, so that authority is
correctly outside its domain. The retained generic contract is the live
preflight-to-executor transport; TIDMAD forecast behavior belongs to the
external task package.

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
from tests.helpers.tuner_composed_effects import (
    composed_tuner_effects,
    recording_sandbox_for_attempts,
    synthetic_cuda_context,
)
from tests.helpers.tuner_composed_fixture import composed_run
from tests.integration.workflows.test_k9_invented_model_dual_mode import (
    _PLUGIN_MODEL_TYPE,
    _PSEUDO_AGENT_FOLDER,
    _disable_sleeps,
    _register_k9_plugin,
)

pytestmark = pytest.mark.dual_mode


@pytest.mark.dual_mode
def test_preflight_batch_reaches_inference_and_record(tmp_path, request, monkeypatch):
    from tests.conftest import _is_real_llm
    from tests.helpers.recording_llm_bridge import RecordingLLMBridge

    if _is_real_llm(request):
        pytest.skip("G2 coherence pin is a wiring test — pseudo choreography only.")

    _register_k9_plugin(monkeypatch, request)
    hardware_context = synthetic_cuda_context(monkeypatch)
    _disable_sleeps(monkeypatch)

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
        trial_time_budget_minutes=None,
        formal_time_budget_minutes=None,
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
    sandbox = recording_sandbox_for_attempts(
        _PLUGIN_MODEL_TYPE,
        base_dir=workspace,
        run_name=run_name,
        completed_attempts=2,
    )
    runtime_batches: list[int | None] = []
    execute_inference = sandbox.execute_inference

    def record_inference_batch(*args, **kwargs):
        runtime_batches.append(kwargs.get("inference_batch"))
        return execute_inference(*args, **kwargs)

    monkeypatch.setattr(sandbox, "execute_inference", record_inference_batch)
    agent = HyperparamTuningAgent(
        bridge_factory=lambda **kw: bridge, sandbox_factory=lambda **kw: sandbox
    )

    with composed_tuner_effects(
        monkeypatch,
        sandbox=sandbox,
        bridge=bridge,
        expected_attempts=3,
        hardware_context=hardware_context,
        preflight_results=[
            ("MEASURED_PEAK_ABOVE_VRAM_CAP", 0.4),
            ("COMPLETED_MEASUREMENT", 0.1),
            ("COMPLETED_MEASUREMENT", 0.1),
        ],
    ) as effects:
        with composed_run(tmp_path, agent_input, health=False):
            output = agent.run(agent_input)
    assert isinstance(output, HyperparamTuningOutput)

    # One refused attempt and two completed attempts all reached the supplied
    # preflight, while only completed attempts reached inference.
    success_records = [r for r in output.all_records if r.status == "success"]
    assert len(success_records) == 2
    assert len(effects.preflight_calls) == 3
    assert len(runtime_batches) == 2, runtime_batches
    assert runtime_batches == [1, 1]

    # The record carries the same value (record_params, tuner :4697).
    for rec, runtime_b in zip(success_records, runtime_batches, strict=True):
        assert rec.params.get("inference_batch") == runtime_b
