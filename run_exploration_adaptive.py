#!/usr/bin/env python3
"""
Launch the adaptive exploration workflow.

Uses run_workflow() directly with max_iterations > 1 so the vocabulary
feedback loop (previous_proposal -> interpretation -> discoveries -> proposal)
works across iterations.

Examples
--------
# Run with defaults (adaptive_v1, v1 advice):
  python run_exploration_adaptive.py --run_name adaptive_v1

# Run with custom advice and workspace:
  python run_exploration_adaptive.py \\
      --run_name adaptive_v2 \\
      --advice tuner_advice/chain_v3_proposer_advice_time_sens.json \\
      --workspace /home/klz/Data/SIDEREIS_DATA/exploration_adaptive_v2
"""
import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "ml_models"))

from workflows.model_exploration import run_workflow
from workflows.llm_config import WorkflowLLMConfig

# Default source paths (wavenet + punet seed runs)
DEFAULT_SOURCE_PATHS = [
    "/home/klz/Data/SIDEREIS_DATA/wavenet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json",
    "/home/klz/Data/SIDEREIS_DATA/punet/small_sample_trial_v0/agent/run_output_small_sample_trial_v0_agent.json",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Launch SIDERIUS adaptive exploration workflow.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--run_name", type=str, required=True,
        help="Run identifier, e.g. 'adaptive_v1'. Used for output filenames.",
    )
    parser.add_argument(
        "--workspace", type=str, default=None,
        help="Output workspace directory. Defaults to "
             "/home/klz/Data/SIDEREIS_DATA/exploration_{run_name}.",
    )
    parser.add_argument(
        "--advice", type=str, default="tuner_advice/exploration_adaptive_v1.json",
        help="Path to the JSON advice file (propose/implement/tune keys).",
    )
    parser.add_argument(
        "--max_iterations", type=int, default=20,
        help="Number of propose->implement->validate->tune iterations.",
    )
    parser.add_argument(
        "--max_rounds", type=int, default=3,
        help="Tuning rounds per iteration.",
    )
    parser.add_argument(
        "--max_proposal_attempts", type=int, default=3,
        help="Max proposal retries per iteration if validation fails.",
    )
    parser.add_argument(
        "--trial_portion", type=float, default=0.1,
        help="Fraction of data used for trial-mode training/eval.",
    )
    parser.add_argument(
        "--train_portion", type=float, default=1.0,
        help="Fraction of trial data used per epoch.",
    )
    parser.add_argument(
        "--eval_portion", type=float, default=0.1,
        help="Fraction of data used for trial-mode evaluation.",
    )
    parser.add_argument(
        "--max_epochs", type=int, default=1,
        help="Hard cap on epochs per tuning round.",
    )
    parser.add_argument(
        "--source_paths", type=str, nargs="+", default=None,
        help="Seed run output JSON paths. Defaults to wavenet + punet trial runs.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Resolve workspace
    workspace = args.workspace or (
        f"/home/klz/Data/SIDEREIS_DATA/exploration_{args.run_name}"
    )

    # Resolve source paths
    source_paths = args.source_paths or DEFAULT_SOURCE_PATHS
    for p in source_paths:
        if not os.path.exists(p):
            print(f"ERROR: Source path not found: {p}")
            sys.exit(1)

    # Load advice file
    if not os.path.exists(args.advice):
        print(f"ERROR: Advice file not found: {args.advice}")
        sys.exit(1)
    with open(args.advice) as f:
        advice = json.load(f)

    # LLM config
    llm_config = WorkflowLLMConfig.uniform(
        "gemini", "gemini-3.1-pro-preview",
        reflect_provider="gemini",
        reflect_model_id="gemini-2.5-flash",
    )

    # Print summary
    print("=" * 60)
    print("  SIDERIUS Adaptive Exploration")
    print(f"  Run name  : {args.run_name}")
    print(f"  Workspace : {workspace}")
    print(f"  Iterations: {args.max_iterations}")
    print(f"  Rounds/iter: {args.max_rounds}  |  Max epochs: {args.max_epochs}")
    print(f"  Trial portion: {args.trial_portion}  |  Train portion: {args.train_portion}  |  Eval portion: {args.eval_portion}")
    print(f"  Advice    : {args.advice}")
    print(f"  Seeds     : {len(source_paths)} models")
    print("=" * 60)

    run_workflow(
        source_paths=source_paths,
        workspace=workspace,
        run_name=args.run_name,
        max_iterations=args.max_iterations,
        max_rounds=args.max_rounds,
        max_proposal_attempts=args.max_proposal_attempts,
        llm_config=llm_config,
        # Trial mode
        is_trial=True,
        trial_strategy="snapshot",
        trial_portion=args.trial_portion,
        train_portion=args.train_portion,
        eval_portion=args.eval_portion,
        max_epochs=args.max_epochs,
        plan_overrides={
            "is_trial": True,
            "trial_portion": args.trial_portion,
            "train_portion": args.train_portion,
            "eval_portion": args.eval_portion,
        },
        # Advice
        human_advice_propose=advice.get("propose"),
        human_advice_implement=advice.get("implement"),
        human_advice_tune=advice.get("tune"),
        human_advice_mindset=advice.get("mindset"),
        # Cleanup denoised files to save disk
        cleanup_denoised=True,
    )


if __name__ == "__main__":
    main()
