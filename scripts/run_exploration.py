#!/usr/bin/env python3
"""
Launch the model exploration workflow with real data.

Usage:
    screen -S siderius-explore
    python scripts/run_exploration.py
    Ctrl+A D  (detach)

    # Monitor:
    tail -f /home/klz/Data/SIDEREIS_DATA/exploration/explore_v1/workflow_log.txt
"""

import os

from execute_tools.data_paths import SIDERIUS_DATA_DIR
from workflows.llm_config import NodeLLMConfig, WorkflowLLMConfig
from workflows.model_exploration import run_workflow

llm_config = WorkflowLLMConfig(
    implement=NodeLLMConfig(provider="gemini", model_id="gemini-3.1-pro-preview"),
)

results = run_workflow(
    data_dir=SIDERIUS_DATA_DIR,
    model_types=["punet", "wavenet", "fcnet"],
    source_run_name="v3_file6",
    workspace=os.path.join(SIDERIUS_DATA_DIR, "exploration"),
    run_name="explore_v1",
    max_iterations=50,
    max_rounds=20,
    max_proposal_attempts=10,
    target_score=10.0,
    llm_config=llm_config,
    human_advice_propose=(
        "Do NOT propose complex architectures like attention, transformers, or mamba. "
        "Start simple: please use equal probability to choose from these two options: "
        "1. propose a easy and straightforward, commonly used model. "
        "2. try modification or variant of the existing models. "
        "For example, a WaveNet-style dilated CNN, a simple residual CNN, or a deeper "
        "version of the existing U-Net with minor changes. The model must be easy to "
        "implement correctly with basic PyTorch modules (Conv1d, ReLU, BatchNorm, "
        "residual connections). No custom attention mechanisms. Under 50K parameters. "
        "Note: fcnet (AutoEncoder) achieved the best score of 7.9 — consider building "
        "on its strengths."
    ),
    human_advice_tune=(
        "Use batch_size=1. Focus on finding the best hyperparameters within 20 rounds."
    ),
    # Trial mode: multi-file sparse sampling with anchor-normalized scoring
    is_trial=True,
    trial_strategy="snapshot",
    trial_portion=0.1,
    train_portion=0.1,
    eval_strategy="snapshot",
    eval_portion=0.1,
    cleanup_denoised=True,
)

print(f"\n\nFinal results: {len(results)} iterations completed")
for i, r in enumerate(results, 1):
    print(f"  Iteration {i}: {r.model_type} score={r.best_denoising_score}")
