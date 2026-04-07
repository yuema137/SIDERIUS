#!/usr/bin/env python3
"""
Per-iteration runner for the SIDERIUS exploration workflow.

Runs ONE iteration of `run_workflow()` (max_iterations=1) using explicit
source paths. Designed for per-iteration Slurm jobs where each job is
1-4 hours and the workflow is chained across many jobs.

Each iteration:
  1. Loads source data from explicit paths (seeds + previous iterations)
  2. Runs the 5-agent loop (interpret → propose → implement → validate → tune)
  3. Writes a manifest.json summarizing the iteration's output for the next job

Usage:
    python sdsc_submission_scripts/run_one_iteration.py \\
        --workspace /scratch/exploration_v1 \\
        --iteration 3 \\
        --source_paths /scratch/.../seed_punet.json /scratch/.../seed_wavenet.json \\
                       /scratch/exploration_v1/iter_001/{m1}/run_output_iter_001.json \\
                       /scratch/exploration_v1/iter_002/{m2}/run_output_iter_002.json \\
        --max_rounds 20 \\
        --llm_model gemini-3.1-pro-preview \\
        --gpu_memory_limit_gb 10
"""
import argparse
import glob
import json
import os
import sys
import traceback

# Ensure SIDERIUS root is importable
SIDERIUS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SIDERIUS_ROOT)
sys.path.insert(0, os.path.join(SIDERIUS_ROOT, "ml_models"))

from dotenv import load_dotenv
load_dotenv()

from workflows.model_exploration import run_workflow
from workflows.llm_config import WorkflowLLMConfig


def resolve_source_paths(source_paths: list[str]) -> list[str]:
    """
    Resolve source path entries to actual JSON file paths.

    Two formats are supported:
      - Direct path: /scratch/.../run_output_*.json (used as-is)
      - Manifest indirection: @manifest:/path/to/manifest.json (read manifest,
        return manifest['output_path'])

    The manifest indirection is used by the orchestrator script when chaining
    iterations: the manifest path is known at submission time, but the actual
    output file path inside it is only known after the iteration completes.
    """
    resolved = []
    for entry in source_paths:
        if entry.startswith("@manifest:"):
            manifest_path = entry[len("@manifest:"):]
            if not os.path.exists(manifest_path):
                raise FileNotFoundError(
                    f"Manifest not found (previous iteration may have failed): {manifest_path}"
                )
            with open(manifest_path) as f:
                manifest = json.load(f)
            output_path = manifest.get("output_path")
            if not output_path:
                raise ValueError(f"Manifest has no output_path: {manifest_path}")
            print(f"  Resolved @manifest:{manifest_path} → {output_path}")
            resolved.append(output_path)
        else:
            resolved.append(entry)
    return resolved


def write_manifest(iter_dir: str, run_name: str, results: list) -> dict:
    """
    Write a manifest.json summarizing this iteration's output.

    The manifest is the discoverable handoff between iterations: the next
    iteration's job reads it to find this iteration's tuning output path.
    """
    if not results:
        manifest = {
            "status": "failed",
            "iteration_dir": iter_dir,
            "output_path": None,
            "model_name": None,
            "best_score": None,
        }
    else:
        tune_output = results[0]
        # The tuning output is at {iter_dir}/iteration_001/{model_name}/run_output_{run_name}.json
        # (run_workflow always wraps each iteration in iteration_NNN, even with max_iterations=1)
        model_name = tune_output.model_type
        output_path = os.path.join(
            iter_dir, "iteration_001", model_name, f"run_output_{run_name}.json"
        )
        if not os.path.exists(output_path):
            # Defensive: scan iter_dir for the actual file
            candidates = glob.glob(
                os.path.join(iter_dir, "**", f"run_output_{run_name}.json"),
                recursive=True,
            )
            if candidates:
                output_path = candidates[0]
        manifest = {
            "status": "completed",
            "iteration_dir": iter_dir,
            "output_path": output_path,
            "model_name": model_name,
            "best_score": tune_output.best_denoising_score,
            "completed_rounds": tune_output.completed_rounds,
        }

    manifest_path = os.path.join(iter_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Manifest written: {manifest_path}")
    return manifest


def main():
    parser = argparse.ArgumentParser(
        description="Run one iteration of the SIDERIUS exploration workflow."
    )
    parser.add_argument(
        "--workspace", type=str, required=True,
        help="Root output directory for this exploration (shared across all iterations)."
    )
    parser.add_argument(
        "--iteration", type=int, required=True,
        help="Iteration number (1-based). Used to construct iter_dir."
    )
    parser.add_argument(
        "--source_paths", type=str, nargs="+", required=True,
        help="Explicit list of HyperparamTuningOutput JSON paths to use as source data."
    )
    parser.add_argument(
        "--max_rounds", type=int, default=20,
        help="Tuning rounds per iteration."
    )
    parser.add_argument(
        "--max_proposal_attempts", type=int, default=3,
        help="Retry budget for propose→implement→validate."
    )
    parser.add_argument(
        "--llm_model", type=str, default="gemini-3.1-pro-preview",
        help="Gemini model ID for all 5 agents."
    )
    parser.add_argument(
        "--gpu_memory_limit_gb", type=int, default=None,
        help="Hard cap on GPU memory per process (Phase 2, not yet implemented end-to-end)."
    )
    parser.add_argument(
        "--max_epochs", type=int, default=None,
        help="Hard cap on epochs per round."
    )
    parser.add_argument(
        "--is_trial", action="store_true",
        help="Enable trial mode (default: True for production)."
    )
    parser.add_argument(
        "--trial_strategy", type=str, default="snapshot",
        choices=["snapshot", "anchors", "target"],
    )
    parser.add_argument(
        "--trial_portion", type=float, default=0.1)
    parser.add_argument(
        "--train_portion", type=float, default=0.1)
    parser.add_argument(
        "--eval_portion", type=float, default=0.1)
    parser.add_argument(
        "--cleanup_denoised", action="store_true",
        help="Delete denoised H5 files after scoring (recommended for production)."
    )
    parser.add_argument(
        "--human_advice_propose", type=str, default=None,
        help="Human guidance for the proposal agent."
    )
    parser.add_argument(
        "--human_advice_tune", type=str, default=None,
        help="Human guidance for the tuning agent."
    )
    args = parser.parse_args()

    # Iteration directory: {workspace}/iter_{N:03d}
    run_name = f"iter_{args.iteration:03d}"
    iter_dir = os.path.join(args.workspace, run_name)
    os.makedirs(iter_dir, exist_ok=True)

    print("=" * 60)
    print(f"  SIDERIUS PER-ITERATION RUNNER")
    print(f"  Workspace      : {args.workspace}")
    print(f"  Iteration      : {args.iteration}")
    print(f"  Run name       : {run_name}")
    print(f"  Iter directory : {iter_dir}")
    print(f"  LLM            : {args.llm_model}")
    print(f"  Source paths   : {len(args.source_paths)} entries")
    for p in args.source_paths:
        print(f"    - {p}")
    print("=" * 60)

    # Resolve manifest indirections to actual JSON paths
    try:
        resolved_paths = resolve_source_paths(args.source_paths)
    except (FileNotFoundError, ValueError) as e:
        print(f"FAIL: Could not resolve source paths: {e}")
        write_manifest(iter_dir, run_name, results=[])
        sys.exit(1)

    llm_config = WorkflowLLMConfig.uniform("gemini", args.llm_model)

    try:
        results = run_workflow(
            source_paths=resolved_paths,
            workspace=args.workspace,
            run_name=run_name,
            llm_config=llm_config,
            max_iterations=1,
            max_rounds=args.max_rounds,
            max_proposal_attempts=args.max_proposal_attempts,
            is_trial=args.is_trial or True,  # default to trial mode
            trial_strategy=args.trial_strategy,
            trial_portion=args.trial_portion,
            train_portion=args.train_portion,
            eval_strategy=args.trial_strategy,
            eval_portion=args.eval_portion,
            cleanup_denoised=args.cleanup_denoised,
            max_epochs=args.max_epochs,
            human_advice_propose=args.human_advice_propose,
            human_advice_tune=args.human_advice_tune,
        )
    except Exception as e:
        print(f"FAIL: Workflow raised exception: {type(e).__name__}: {e}")
        traceback.print_exc()
        write_manifest(iter_dir, run_name, results=[])
        sys.exit(1)

    manifest = write_manifest(iter_dir, run_name, results)

    if manifest["status"] != "completed":
        print(f"FAIL: Iteration did not complete successfully.")
        sys.exit(1)

    print()
    print("=" * 60)
    print(f"  ITERATION {args.iteration} COMPLETE")
    print(f"  Model      : {manifest['model_name']}")
    print(f"  Best score : {manifest['best_score']}")
    print(f"  Output     : {manifest['output_path']}")
    print("=" * 60)
    sys.exit(0)


if __name__ == "__main__":
    main()
