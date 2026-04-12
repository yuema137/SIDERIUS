#!/usr/bin/env python3
"""
Launch the adaptive exploration workflow with vocabulary feedback.

Uses run_workflow() directly with max_iterations > 1 so the vocabulary
feedback loop (previous_proposal -> interpretation -> discoveries -> proposal)
works across iterations.
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "ml_models"))

from workflows.model_exploration import run_workflow
from workflows.llm_config import WorkflowLLMConfig


def main():
    # --- Source data: trial-mode seed runs (wavenet + punet only) ---
    source_paths = [
        "/home/klz/Data/SIDEREIS_DATA/wavenet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json",
        "/home/klz/Data/SIDEREIS_DATA/punet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json",
    ]

    # Verify source paths exist
    for p in source_paths:
        if not os.path.exists(p):
            print(f"ERROR: Source path not found: {p}")
            sys.exit(1)

    # --- Load advice file ---
    advice_path = "tuner_advice/exploration_adaptive_v1.json"
    with open(advice_path) as f:
        advice = json.load(f)

    # --- LLM config ---
    llm_config = WorkflowLLMConfig.uniform(
        "gemini", "gemini-3.1-pro-preview",
        reflect_provider="gemini",
        reflect_model_id="gemini-2.5-flash",
    )

    # --- Run ---
    print("=" * 60)
    print("  SIDERIUS Adaptive Exploration v1")
    print(f"  Iterations: 20")
    print(f"  Tuning rounds per iteration: 3")
    print(f"  Max epochs per round: 1")
    print(f"  Trial portion: 0.1, Train portion: 1.0, Eval portion: 0.1")
    print(f"  Advice: {advice_path}")
    print(f"  Seeds: {len(source_paths)} models (wavenet, punet)")
    print("=" * 60)

    run_workflow(
        source_paths=source_paths,
        workspace="/home/klz/Data/SIDEREIS_DATA/exploration_adaptive_v1",
        run_name="adaptive_v1",
        max_iterations=20,
        max_rounds=3,
        max_proposal_attempts=3,
        llm_config=llm_config,
        # Trial mode
        is_trial=True,
        trial_strategy="snapshot",
        trial_portion=0.1,
        train_portion=1.0,
        eval_portion=0.1,
        max_epochs=1,
        plan_overrides={
            "is_trial": True,
            "trial_portion": 0.1,
            "train_portion": 1.0,
            "eval_portion": 0.1,
        },
        # Advice
        human_advice_propose=advice.get("propose"),
        human_advice_implement=advice.get("implement"),
        human_advice_tune=advice.get("tune"),
        # Cleanup denoised files to save disk
        cleanup_denoised=True,
    )


if __name__ == "__main__":
    main()
