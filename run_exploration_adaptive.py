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
        "--llm_config", type=str, default=None,
        help=(
            "Path to a WorkflowLLMConfig JSON file for per-node model routing "
            "(e.g. llm_configs/openai_tiered_v1.json). "
            "When omitted, defaults to uniform gemini-3.1-pro-preview."
        ),
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
        "--max_impl_attempts", type=int, default=3,
        help=(
            "Max implementation retries per proposal when the validator rejects the code. "
            "Each retry feeds the validator's error back to the implementor so it can fix "
            "spec-alignment issues without requiring a new proposal."
        ),
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
        "--trial_strategy", type=str, default="snapshot",
        choices=["snapshot", "anchors", "target"],
        help=(
            "Sampling strategy for trial mode. 'snapshot' covers all 20 files, "
            "'anchors' picks files 0/10/19, 'target' restricts to --target_files. "
            "Forwarded to BOTH the proposer's and tuner's evaluate_time_skill gates."
        ),
    )
    parser.add_argument(
        "--target_files", type=int, nargs="+", default=None,
        help=(
            "File indices to sample from (required when --trial_strategy=target). "
            "Modern replacement for legacy single-file mode: pass e.g. --target_files 6."
        ),
    )
    parser.add_argument(
        "--sampling_seed", type=int, default=None,
        help="Seed for build_sample_set(). None auto-generates per gate.",
    )
    parser.add_argument(
        "--trial_time_budget_minutes", type=float, default=None,
        help=(
            "Wall-time budget (minutes) for the evaluate_time_skill gate on "
            "rounds where plan.is_trial=True. Forwarded to BOTH the proposer's "
            "baseline gate and the tuner's per-round gate. None disables the "
            "trial gate (docs/resource_estimator_implement.md §2.7 / Phase I)."
        ),
    )
    parser.add_argument(
        "--formal_time_budget_minutes", type=float, default=None,
        help=(
            "Wall-time budget (minutes) for the evaluate_time_skill gate on "
            "rounds where plan.is_trial=False. Sized independently from the "
            "trial budget because formal runs use the full dataset and are "
            "50–100x longer. None disables the formal gate."
        ),
    )
    parser.add_argument(
        "--data_dir", type=str, default=None,
        help=(
            "TIDMAD data directory used by evaluate_time_skill's real-dataset "
            "warmup. None makes the skill fall back to its static formula."
        ),
    )
    parser.add_argument(
        "--source_paths", type=str, nargs="+", default=None,
        help="Seed run output JSON paths. Defaults to wavenet + punet trial runs.",
    )
    parser.add_argument(
        "--exploration_mode", type=str, default="auto",
        choices=["auto", "explore", "exploit"],
        help=(
            "Reasoning pipeline mode. 'auto' resolves dynamically from n_agent_proposed "
            "and vocab_diversity_ratio. 'explore' forces novel architecture search "
            "(use with exploration_adaptive_v3 advice). 'exploit' forces incremental "
            "refinement of the current SOTA."
        ),
    )
    parser.add_argument(
        "--minimum_boldness", type=float, default=0.05,
        help=(
            "Minimum boldness threshold for FalsifiablePrediction: "
            "|predicted - current| / |current| must exceed this value. "
            "Predictions below the threshold trigger a causal_reasoning retry. "
            "Default 0.05 (5%% relative improvement required)."
        ),
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
    # Allow advice values to be either a string or a list of lines (joined with
    # "\n" before consumption). The list form keeps long prose readable in the
    # JSON file without changing what the LLM ultimately sees.
    advice = {k: ("\n".join(v) if isinstance(v, list) else v)
              for k, v in advice.items()}

    # LLM config — from file if provided, else default uniform gemini
    if args.llm_config:
        if not os.path.exists(args.llm_config):
            print(f"ERROR: LLM config file not found: {args.llm_config}")
            sys.exit(1)
        llm_config = WorkflowLLMConfig.from_json(args.llm_config)
    else:
        llm_config = WorkflowLLMConfig.uniform("gemini", "gemini-3.1-pro-preview")

    # Validate target-mode wiring early
    if args.trial_strategy == "target" and not args.target_files:
        print("ERROR: --trial_strategy=target requires --target_files (one or more file indices)")
        sys.exit(1)

    # Print summary
    print("=" * 60)
    print("  SIDERIUS Adaptive Exploration")
    print(f"  Run name  : {args.run_name}")
    print(f"  Workspace : {workspace}")
    print(f"  Iterations: {args.max_iterations}")
    print(f"  Rounds/iter: {args.max_rounds}  |  Max epochs: {args.max_epochs}")
    print(f"  Trial strategy: {args.trial_strategy}"
          + (f"  |  Target files: {args.target_files}" if args.trial_strategy == "target" else ""))
    print(f"  Trial portion: {args.trial_portion}  |  Train portion: {args.train_portion}  |  Eval portion: {args.eval_portion}")
    print(f"  Sampling seed : {args.sampling_seed if args.sampling_seed is not None else 'auto'}")
    trial_budget_str = (f"{args.trial_time_budget_minutes} min"
                        if args.trial_time_budget_minutes is not None
                        else "disabled")
    formal_budget_str = (f"{args.formal_time_budget_minutes} min"
                         if args.formal_time_budget_minutes is not None
                         else "disabled")
    print(f"  Time budget   : trial={trial_budget_str}  |  formal={formal_budget_str}")
    print(f"  Data dir      : {args.data_dir or 'unset (skill uses static formula)'}")
    print(f"  Advice    : {args.advice}")
    print(f"  LLM config: {args.llm_config or 'default (gemini-3.1-pro-preview uniform)'}")
    print(f"  Seeds     : {len(source_paths)} models")
    print(f"  Exploration mode : {args.exploration_mode}")
    print(f"  Min boldness     : {args.minimum_boldness}")
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
        trial_strategy=args.trial_strategy,
        trial_portion=args.trial_portion,
        target_files=args.target_files,
        train_portion=args.train_portion,
        eval_portion=args.eval_portion,
        sampling_seed=args.sampling_seed,
        max_epochs=args.max_epochs,
        plan_overrides={
            "is_trial": True,
            "trial_portion": args.trial_portion,
            "train_portion": args.train_portion,
            "eval_portion": args.eval_portion,
        },
        # Time-budget gate (Phase I two-budget split — fans out to both proposer and tuner)
        trial_time_budget_minutes=args.trial_time_budget_minutes,
        formal_time_budget_minutes=args.formal_time_budget_minutes,
        data_dir=args.data_dir,
        # Advice
        human_advice_propose=advice.get("propose"),
        human_advice_implement=advice.get("implement"),
        human_advice_tune=advice.get("tune"),
        human_advice_mindset=advice.get("mindset"),
        # Cleanup denoised files to save disk
        cleanup_denoised=True,
        # Reasoning pipeline
        exploration_mode=args.exploration_mode,
        minimum_boldness=args.minimum_boldness,
        # Implementation retry
        max_impl_attempts=args.max_impl_attempts,
    )


if __name__ == "__main__":
    main()
