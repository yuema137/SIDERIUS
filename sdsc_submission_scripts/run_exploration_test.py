#!/usr/bin/env python3
"""
Standalone Tier 3 integration test runner for SDSC Slurm execution.

Runs the full 5-agent exploration workflow with the same minimal config
as the pytest version (tests/integration/workflows/test_full_exploration_loop.py),
but as a plain Python script — no pytest, no fixtures, no tmp_path.

Designed to be invoked from a Slurm job script. Exits 0 on success, 1 on failure.

Usage:
    python sdsc_submission_scripts/run_exploration_test.py \\
        --workspace /expanse/lustre/projects/ddp433/ym137/test_output \\
        --run_name test_full_loop_$(date +%m%d_%H%M)
"""
import argparse
import os
import shutil
import sys
import traceback

# Ensure SIDERIUS root is importable
SIDERIUS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SIDERIUS_ROOT)
sys.path.insert(0, os.path.join(SIDERIUS_ROOT, "ml_models"))

from dotenv import load_dotenv
load_dotenv()

from execute_tools.data_paths import TIDMAD_DATA_DIR, SIDERIUS_DATA_DIR
from workflows.model_exploration import run_workflow
from workflows.llm_config import WorkflowLLMConfig

# Reuse the validation function from the pytest test file
sys.path.insert(0, os.path.join(SIDERIUS_ROOT, "tests/integration/workflows"))
from test_full_exploration_loop import validate_workflow_outputs


def check_prerequisites(source_models: list[str], source_run_name: str) -> list[str]:
    """Return a list of missing prerequisites (empty if all present)."""
    missing = []

    if not os.getenv("GEMINI_API_KEY"):
        missing.append("GEMINI_API_KEY environment variable not set")

    if not os.path.isdir(TIDMAD_DATA_DIR):
        missing.append(f"TIDMAD data directory not found: {TIDMAD_DATA_DIR}")

    if not os.path.isdir(SIDERIUS_DATA_DIR):
        missing.append(f"SIDERIUS data directory not found: {SIDERIUS_DATA_DIR}")

    anchor_map = os.path.join(TIDMAD_DATA_DIR, "segment_anchors.json")
    if not os.path.exists(anchor_map):
        missing.append(f"Segment anchor map not found: {anchor_map}")

    for model in source_models:
        path = os.path.join(
            SIDERIUS_DATA_DIR, model, source_run_name, "agent",
            f"run_output_{source_run_name}_agent.json",
        )
        if not os.path.exists(path):
            missing.append(f"Tuning output not found: {path}")

    try:
        import torch
        if not torch.cuda.is_available():
            missing.append("CUDA GPU not available")
    except ImportError:
        missing.append("PyTorch not installed")

    return missing


def main():
    parser = argparse.ArgumentParser(
        description="SDSC Slurm runner for the Tier 3 5-agent workflow integration test"
    )
    parser.add_argument(
        "--workspace", type=str, required=True,
        help="Output directory (use cluster scratch path)"
    )
    parser.add_argument(
        "--run_name", type=str, default="test_full_loop",
        help="Run name for this test execution"
    )
    parser.add_argument(
        "--llm_model", type=str, default="gemini-3.1-pro-preview",
        help="Gemini model ID for all 5 agents"
    )
    parser.add_argument(
        "--max_rounds", type=int, default=2,
        help="Tuning rounds (round 1 = trial, last round = forced formal)"
    )
    parser.add_argument(
        "--max_proposal_attempts", type=int, default=3,
        help="Retry budget for propose→implement→validate"
    )
    parser.add_argument(
        "--max_epochs", type=int, default=1,
        help="Hard cap on epochs per round (test should be fast)"
    )
    parser.add_argument(
        "--source_models", type=str, nargs="+", default=["punet", "wavenet"],
        help="Models to load as historical source data for the interpretation agent"
    )
    parser.add_argument(
        "--source_run_name", type=str, default="small_sample_trial_v0",
        help="Run name to load source data from (lilab default; use 'hpt_full_v1' on SDSC)"
    )
    parser.add_argument(
        "--no_cleanup", action="store_true",
        help="Skip plugin cleanup after test (for debugging)"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  SDSC TIER 3 INTEGRATION TEST: 5-Agent Workflow")
    print(f"  Workspace      : {args.workspace}")
    print(f"  Run name       : {args.run_name}")
    print(f"  LLM            : {args.llm_model}")
    print(f"  Max rounds     : {args.max_rounds}")
    print(f"  Source models  : {args.source_models}")
    print(f"  Source run     : {args.source_run_name}")
    print("=" * 60)

    # --- Prerequisites check ---
    print("\n[1/4] Checking prerequisites...")
    missing = check_prerequisites(args.source_models, args.source_run_name)
    if missing:
        print("FAIL: Missing prerequisites:")
        for m in missing:
            print(f"  - {m}")
        sys.exit(1)
    print("  All prerequisites present.")

    # --- Run workflow ---
    print("\n[2/4] Running 5-agent workflow...")
    llm_config = WorkflowLLMConfig.uniform("gemini", args.llm_model)

    try:
        results = run_workflow(
            data_dir=SIDERIUS_DATA_DIR,
            model_types=args.source_models,
            source_run_name=args.source_run_name,
            workspace=args.workspace,
            run_name=args.run_name,
            llm_config=llm_config,
            max_iterations=1,
            max_rounds=args.max_rounds,
            max_proposal_attempts=args.max_proposal_attempts,
            # Full data mode with minimal data
            is_trial=True,
            trial_strategy="snapshot",
            trial_portion=0.02,
            train_portion=1.0,
            eval_strategy="snapshot",
            eval_portion=0.02,
            cleanup_denoised=True,
            max_epochs=args.max_epochs,
            human_advice_propose=(
                "Propose a VERY simple architecture — no more than 3 layers, "
                "fewer than 10K parameters. Use only basic PyTorch modules "
                "(nn.Embedding, nn.Conv1d, nn.Linear, nn.ReLU). "
                "Do NOT use attention, transformers, or complex gating. "
                "The model must train and infer in under 30 seconds on a single GPU. "
                "Use segmentation_size=10000 in baseline_config.train_config."
            ),
            human_advice_tune=(
                "CRITICAL: Use exactly 1 epoch, batch_size=1, lr=1e-4, device=cuda. "
                "Keep the model as small as possible — under 10K parameters. "
                "This is an integration test — speed matters more than score. "
                "You MUST use segmentation_size from the model_config as-is."
            ),
        )
    except Exception as e:
        print(f"FAIL: Workflow raised exception: {type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(1)

    # --- Validate outputs ---
    print("\n[3/4] Validating workflow outputs...")
    run_dir = os.path.join(args.workspace, args.run_name)
    try:
        model_name = validate_workflow_outputs(run_dir, args.run_name, results)
    except AssertionError as e:
        print(f"FAIL: Validation assertion failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"FAIL: Validation raised exception: {type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(1)

    # --- Cleanup registered plugin ---
    print("\n[4/4] Cleaning up...")
    if not args.no_cleanup:
        plugin_file = os.path.join(SIDERIUS_ROOT, "agent_generated", "models", f"{model_name}.py")
        plugin_desc_dir = os.path.join(SIDERIUS_ROOT, "agent_generated", "models", model_name)
        if os.path.exists(plugin_file):
            os.remove(plugin_file)
            print(f"  Removed {plugin_file}")
        if os.path.isdir(plugin_desc_dir):
            shutil.rmtree(plugin_desc_dir)
            print(f"  Removed {plugin_desc_dir}/")
    else:
        print("  Skipped (--no_cleanup)")

    print()
    print("=" * 60)
    print(f"  TIER 3 TEST PASSED — model '{model_name}' explored successfully")
    print("=" * 60)
    sys.exit(0)


if __name__ == "__main__":
    main()
