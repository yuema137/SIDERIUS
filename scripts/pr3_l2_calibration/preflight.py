# scripts/pr3_l2_calibration/preflight.py
"""Zero-LLM launch preflight (protocol §3.3-§3.4). NO LLM CALLS.

Drives the full production assembly per arm with a mocked bridge and
asserts every launch invariant; also produces the launch-day prompt
measurement. Run via the pytest wrapper
(tests/unit/scripts/test_pr3_l2p_preflight.py) or directly:

    .venv/bin/python -m scripts.pr3_l2_calibration.preflight
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

FAKE_COMPARISON = {
    "comparisons": [],
    "proposed_vocab_links": [],
    "proposed_vocab_candidates": [],
    "sota_model_type": "spectral_resnet_b",
    "sota_score": 1.62,
    "sota_mechanism": "Gated spectral residual path.",
}
FAKE_REASONING = {
    "proposed_change": "Add variance-preserving output head.",
    "causal_hypothesis": "Output head collapse causes single-value output.",
    "falsifiable_prediction": {
        "metric": "denoising_score",
        "current_value": 1.62,
        "predicted_value": 2.0,
        "threshold_for_refutation": 1.0,
        "rationale": "Anti-collapse head should preserve diversity.",
    },
    "predicted_failure_modes": ["VRAM overflow."],
    "inherited_components": [],
    "proposed_vocab_candidates": [],
}
FAKE_PROPOSING = {
    "model_name": "variance_preserving_unet",
    "model_description": "UNet with variance-preserving output head.",
    "mathematical_definition": "Conv encoder/decoder + entropy-regularized head.",
    "motivation": "Addresses diversity collapse.",
    "expert_advice": {
        "focus_areas": ["output diversity"],
        "constraints": ["VRAM < 10 GB"],
        "known_failures": [],
        "suggested_directions": [],
        "rationale": "Anti-collapse baseline.",
    },
    "baseline_config": {
        "model_config": {"depth": 3},
        "train_config": {"lr": 1e-4, "epochs": 1},
        "loss_config": {"loss_type": "focal"},
    },
    "memo_consistency_notes": [],
}
FAKE_INTERP_PER_MODEL = {
    "key_findings": ["finding"],
    "bottlenecks": ["bottleneck"],
    "best_config_analysis": "analysis",
    "score_trend": "flat",
    "per_file_analysis": "n/a",
    "data_sensitivity": "n/a",
    "efficiency_assessment": "n/a",
    "strategy_assessment": "n/a",
}
FAKE_INTERP_SYNTHESIS = {
    "key_findings": ["cross-model finding"],
    "bottlenecks": ["cross bottleneck"],
    "take_home_message": "Break the collapse.",
    "proposed_vocab_candidates": [],
    "prediction_evaluation": None,
}


def _interp_dispatch(system_prompt, user_prompt, **kw):
    if "ONE model architecture" in system_prompt:
        return dict(FAKE_INTERP_PER_MODEL)
    return dict(FAKE_INTERP_SYNTHESIS)


def run_arm(scenario: str, arm: str) -> dict:
    """Assemble one sample's full prompt set with mocked LLMs; return the
    measurement + invariant record."""
    import tempfile
    from unittest.mock import patch

    from agent.schemas.interpretation import InterpretationInput
    from agent.schemas.proposal import (
        ForwardContract,
        ReasoningPipelineConfig,
        ReasoningStage,
    )
    from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import (
        local_full_context,
    )
    from agent.schemas.storage import LocalStorageConfig, StorageConfig
    from nodes.ml_model_proposal_agent import MLModelProposalAgent
    from nodes.result_interpretation_agent import (
        ResultInterpretationAgent,
        tuning_output_to_model_run_summary,
    )
    from scripts.pr3_l2_calibration.fixtures import MODEL_DESCRIPTIONS, SCENARIOS
    from workflows.task_config import get_task_description, load_task_config

    spec = SCENARIOS[scenario]
    interp_on, proposer_on = arm in ("T", "D"), arm == "T"
    tmp = tempfile.mkdtemp(prefix=f"p3l2p_preflight_{scenario}_{arm}_")

    summaries = []
    for out in spec["tune_outputs"]():
        s = tuning_output_to_model_run_summary(out)
        s.model_description = MODEL_DESCRIPTIONS.get(s.model_type)
        summaries.append(s)
    interp_input = InterpretationInput(
        summaries=summaries,
        storage={"backend": "local", "local": {"workspace": tmp, "run_name": "pf"}},
        iteration=spec["iteration"],
        enable_structured_health_feedback=interp_on,
        collapse_fingerprint_history=spec["carried_history"](),
        task_description=get_task_description(load_task_config()),
    )
    with patch("nodes.result_interpretation_agent.LLMBridge") as MB:
        MB.return_value.generate.side_effect = _interp_dispatch
        agent = ResultInterpretationAgent(provider="openai", model_id="preflight")
        agent.bridge = MB.return_value
        interp_out = agent.run(interp_input)
    interp_prompts = [
        (c.kwargs.get("system_prompt") or c.args[0])
        + "\n"
        + (c.kwargs.get("user_prompt") or c.args[1])
        for c in agent.bridge.generate.call_args_list
    ]

    storage = StorageConfig(backend="local", local=LocalStorageConfig(workspace=tmp, run_name="pf"))
    propose_input = local_full_context(
        interp_out,
        storage,
        enable_structured_health_feedback=proposer_on,
        reasoning_pipeline=ReasoningPipelineConfig(
            exploration_mode="exploit",
            stages=[
                ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
                ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
            ],
        ),
    )
    _cfg = load_task_config()
    propose_input.task_description = get_task_description(_cfg)
    propose_input.forward_contract = ForwardContract(**_cfg["forward_contract"])

    mb = MagicMock()
    mb.generate.side_effect = [FAKE_COMPARISON, FAKE_REASONING, FAKE_PROPOSING]
    proposer = MLModelProposalAgent(
        provider="openai", model_id="preflight", bridge_factory=lambda **kw: mb
    )
    proposer.run(propose_input)
    stage_prompts = []
    proposing_prompt = ""
    for c in mb.generate.call_args_list:
        sp = c.kwargs.get("system_prompt") or c.args[0]
        up = c.kwargs.get("user_prompt") or (c.args[1] if len(c.args) > 1 else "") or ""
        stage_prompts.append(sp + "\n" + up)
        if "custom_loss_spec" in sp:
            proposing_prompt = sp

    interp_chars = sum(len(p) for p in interp_prompts)
    proposer_chars = sum(len(p) for p in stage_prompts)
    return {
        "scenario": scenario,
        "arm": arm,
        "pipeline_mode": bool(proposing_prompt),
        "placeholder_unresolved": "{healthgate_evidence_block}" in proposing_prompt
        or "{recent_gate_exhaustions_block}" in proposing_prompt,
        "proposer_block_present": "[HEALTHGATE EVIDENCE]" in proposing_prompt,
        "interp_block_present": any("HealthGate summary" in p for p in interp_prompts),
        "interp_chars": interp_chars,
        "proposer_chars": proposer_chars,
        "est_input_tokens": (interp_chars + proposer_chars) // 4,
    }


def main() -> dict:
    from scripts.pr3_l2_calibration.fixtures import fixture_hash

    results = {}
    for scenario in ("S1", "S2"):
        for arm in ("C", "T", "D"):
            r = run_arm(scenario, arm)
            assert r["pipeline_mode"], f"{scenario}/{arm}: pipeline mode not selected"
            assert not r["placeholder_unresolved"], f"{scenario}/{arm}: unresolved placeholder"
            assert r["proposer_block_present"] == (arm == "T"), (
                f"{scenario}/{arm}: proposer block wrong"
            )
            assert r["interp_block_present"] == (arm in ("T", "D")), (
                f"{scenario}/{arm}: interp block wrong"
            )
            results[f"{scenario}_{arm}"] = r
    # Fixture-hash stability + cross-arm identity (builders are arm-free;
    # two consecutive evaluations must agree).
    for s in ("S1", "S2"):
        assert fixture_hash(s) == fixture_hash(s)
    results["fixture_hashes"] = {"S1": fixture_hash("S1"), "S2": fixture_hash("S2")}
    # Treatment-only token increase (proposer, per scenario).
    for s in ("S1", "S2"):
        results[f"{s}_treatment_token_increase"] = (
            results[f"{s}_T"]["proposer_chars"] - results[f"{s}_C"]["proposer_chars"]
        ) // 4
    return results


if __name__ == "__main__":
    out = main()
    print(json.dumps(out, indent=2))
