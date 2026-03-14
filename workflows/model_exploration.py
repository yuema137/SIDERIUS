#!/usr/bin/env python3
"""
workflows/model_exploration.py — First SIDERIUS workflow.

Iterative model exploration loop:

  for each iteration:
      interpret (all accumulated results)
      for each attempt (up to max_proposal_attempts):
          propose (with previous failures if retrying)
          implement
          validate
          if passed → break
      tune the validated model
      accumulate results for next iteration

Stop conditions (whichever comes first):
  - max_iterations reached (successful iterations = validated + tuned)
  - target_score achieved (best_denoising_score >= target)

Single-pass mode is max_iterations=1 (the default).

This is a workflow, not an orchestrator — the path is fixed and deterministic.
The workflow retries propose→implement→validate on validation failure, feeding
error messages back to the proposal agent. Full retry/rerouting logic belongs
in a future orchestrator.

Storage layout:
  {workspace}/
  ├── workflow_{run_name}.json
  ├── iteration_001/
  │   ├── interpretation.json
  │   ├── attempt_001/
  │   │   ├── proposal.json
  │   │   ├── implementor.json
  │   │   └── validation.json
  │   ├── attempt_002/          (if attempt 1 failed)
  │   │   └── ...
  │   └── tuning/
  │       ├── run_output.json
  │       └── ...
  ├── iteration_002/
  │   └── ...

Usage:
  python workflows/model_exploration.py \\
      --data_dir /home/klz/Data/SIDEREIS_DATA \\
      --models punet wavenet \\
      --workspace ./workflow_output \\
      --run_name explore_v1 \\
      --max_iterations 3 \\
      --max_rounds 10
"""

import os
import sys
import json
import glob
import argparse
import time

# Ensure SIDERIUS root is importable
SIDERIUS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SIDERIUS_ROOT)

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from agent.schemas.interpretation import InterpretationInput, SummaryGroup
from agent.schemas.storage import StorageConfig, LocalStorageConfig

from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import local_full_context
from agent.schemas.protocols.ml_model_propose_to_ml_model_impl import local_full_spec
from agent.schemas.protocols.ml_model_impl_to_ml_model_valid import local_all_fields
from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import local_validated_model

from nodes.result_interpretation_agent import ResultInterpretationAgent
from nodes.ml_model_proposal_agent import MLModelProposalAgent
from nodes.ml_model_implementor import MLModelImplementor
from nodes.ml_code_validator_agent import MLCodeValidatorAgent
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_tuning_outputs(data_dir: str, model_types: list[str]) -> list[HyperparamTuningOutput]:
    """
    Scan data_dir for existing HyperparamTuningOutput JSON files.

    Looks for:
      {data_dir}/{model_type}/*/agent/run_output_*.json

    Returns a list of validated HyperparamTuningOutput objects.
    Raises if no outputs are found.
    """
    outputs = []
    for model_type in model_types:
        pattern = os.path.join(data_dir, model_type, "*", "agent", "run_output_*.json")
        matches = sorted(glob.glob(pattern))
        for path in matches:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                output = HyperparamTuningOutput.model_validate(data)
                outputs.append(output)
                print(f"  Loaded: {path} "
                      f"({output.model_type}, {len(output.all_records)} records, "
                      f"best={output.best_denoising_score})")
            except Exception as e:
                print(f"  Warning: skipping {path} — {e}")

    if not outputs:
        raise FileNotFoundError(
            f"No HyperparamTuningOutput files found in {data_dir} "
            f"for models {model_types}. Run tune_ml_hyperparam_agent first."
        )
    return outputs


def tuning_outputs_to_summary_groups(
    outputs: list[HyperparamTuningOutput],
) -> list[SummaryGroup]:
    """
    Convert a list of HyperparamTuningOutput objects into SummaryGroup objects
    suitable for InterpretationInput.
    """
    groups = []
    for output in outputs:
        records = [r.model_dump() if hasattr(r, "model_dump") else r
                   for r in output.all_records]
        groups.append(SummaryGroup(
            model_type=output.model_type,
            run_name=output.run_name,
            records=records,
        ))
    return groups


def _make_storage(workspace: str, run_name: str) -> StorageConfig:
    """Create a StorageConfig pointing at a specific workspace directory."""
    return StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=workspace, run_name=run_name),
    )


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------

def run_workflow(
    data_dir: str,
    model_types: list[str],
    workspace: str,
    run_name: str,
    max_iterations: int = 1,
    max_rounds: int = 10,
    max_proposal_attempts: int = 3,
    target_score: float | None = None,
    file_index: int = 6,
    llm_provider: str = "gemini",
    llm_model_id: str = "gemini-3.1-flash-lite-preview",
    human_advice_interpret: str | None = None,
    human_advice_propose: str | None = None,
    human_advice_implement: str | None = None,
    human_advice_validate: str | None = None,
    human_advice_tune: str | None = None,
) -> list[HyperparamTuningOutput]:
    """
    Execute the model exploration workflow for one or more iterations.

    Each iteration: interpret → (propose → implement → validate) → tune.
    The propose→implement→validate inner loop retries on validation failure.

    Args:
        data_dir: Root data directory containing existing tuning results.
        model_types: List of model types to include in initial interpretation.
        workspace: Root output directory for this workflow run.
        run_name: Unique name for this workflow run.
        max_iterations: Number of successful iterations (validated + tuned).
        max_rounds: Tuning budget per iteration.
        max_proposal_attempts: Max propose→implement→validate retries per iteration.
        target_score: Optional early stop — halt if best score >= target.
        file_index: Training/validation file index.
        llm_provider: LLM provider for all nodes.
        llm_model_id: LLM model ID for all nodes.
        human_advice_interpret: Human guidance for interpretation steps.
        human_advice_propose: Human guidance for proposal steps.
        human_advice_implement: Human guidance for implementation steps.
        human_advice_validate: Human guidance for validation steps.
        human_advice_tune: Human guidance for tuning steps.

    Returns:
        List of HyperparamTuningOutput objects, one per successful iteration.
    """
    os.makedirs(workspace, exist_ok=True)
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")

    print(f"\n{'='*60}")
    print(f"  SIDERIUS Model Exploration Workflow")
    print(f"  Started       : {started_at}")
    print(f"  Models        : {model_types}")
    print(f"  Workspace     : {workspace}")
    print(f"  Run name      : {run_name}")
    print(f"  LLM           : {llm_provider}/{llm_model_id}")
    print(f"  Iterations    : {max_iterations}")
    print(f"  Tune rounds   : {max_rounds} per iteration")
    print(f"  Proposal tries: {max_proposal_attempts} per iteration")
    if target_score is not None:
        print(f"  Target score  : {target_score}")
    print(f"{'='*60}\n")

    # --- Step 0: Load existing tuning outputs ---
    print("Step 0: Loading existing tuning outputs...")
    tuning_outputs = load_tuning_outputs(data_dir, model_types)
    summary_groups = tuning_outputs_to_summary_groups(tuning_outputs)
    print(f"  Loaded {len(tuning_outputs)} tuning outputs "
          f"across {len(set(o.model_type for o in tuning_outputs))} model types.\n")

    # Track all model types seen (for duplicate name guard)
    all_model_types = list({o.model_type for o in tuning_outputs})

    # Collect results across iterations
    iteration_results: list[HyperparamTuningOutput] = []
    best_score_overall: float | None = None

    # --- Iteration loop ---
    for iteration in range(1, max_iterations + 1):
        iter_dir = os.path.join(workspace, f"iteration_{iteration:03d}")
        os.makedirs(iter_dir, exist_ok=True)
        iter_run_name = f"{run_name}_iter{iteration:03d}"

        print(f"\n{'='*60}")
        print(f"  ITERATION {iteration}/{max_iterations}")
        print(f"  Directory: {iter_dir}")
        print(f"{'='*60}\n")

        # --- Interpret (once per iteration, with accumulated results) ---
        interp_storage = _make_storage(iter_dir, iter_run_name)
        interp_input = InterpretationInput(
            summaries=summary_groups,
            human_advice=human_advice_interpret,
            storage=interp_storage,
        )

        print(f"  [{iteration}] Interpreting experiment results...")
        interpretation = ResultInterpretationAgent(
            provider=llm_provider, model_id=llm_model_id,
        ).run(interp_input)
        print(f"    Take-home: {interpretation.take_home_message}")
        print(f"    Best score: {interpretation.best_denoising_score}")
        print(f"    Models: {interpretation.model_types}\n")

        # --- Propose → Implement → Validate (retry loop) ---
        proposal = None
        impl_output = None
        validation = None
        previous_failures: list[str] = []

        for attempt in range(1, max_proposal_attempts + 1):
            attempt_dir = os.path.join(iter_dir, f"attempt_{attempt:03d}")
            os.makedirs(attempt_dir, exist_ok=True)
            attempt_run_name = f"{iter_run_name}_att{attempt:03d}"
            attempt_storage = _make_storage(attempt_dir, attempt_run_name)

            print(f"  [{iteration}.{attempt}] Proposing new model (attempt {attempt}/{max_proposal_attempts})...")

            # --- Propose ---
            propose_input = local_full_context(interpretation, attempt_storage)
            propose_input.existing_model_types = list(all_model_types)
            if human_advice_propose is not None:
                propose_input.human_advice = human_advice_propose
            if previous_failures:
                propose_input.previous_failures = previous_failures

            proposal = MLModelProposalAgent(
                provider=llm_provider, model_id=llm_model_id,
            ).run(propose_input)
            print(f"    Proposed: {proposal.model_name}")

            # --- Implement ---
            print(f"  [{iteration}.{attempt}] Implementing...")
            impl_input = local_full_spec(proposal, attempt_storage)
            if human_advice_implement is not None:
                impl_input.human_advice = human_advice_implement

            impl_output = MLModelImplementor(
                provider=llm_provider, model_id=llm_model_id,
            ).run(impl_input)
            print(f"    Plugin: {impl_output.model_file_path}")

            # --- Validate ---
            print(f"  [{iteration}.{attempt}] Validating...")
            valid_input = local_all_fields(
                impl_output, attempt_storage,
                llm_provider=llm_provider,
                llm_model_id=llm_model_id,
            )
            if human_advice_validate is not None:
                valid_input.human_advice = human_advice_validate

            validation = MLCodeValidatorAgent(
                provider=llm_provider, model_id=llm_model_id,
            ).run(valid_input)

            if validation.passed:
                print(f"    All 7 checks passed.\n")
                break
            else:
                print(f"    Validation FAILED: {validation.error_message}")
                previous_failures.append(validation.error_message or "Unknown validation error")
                if attempt < max_proposal_attempts:
                    print(f"    Retrying with failure feedback...\n")

        if not validation or not validation.passed:
            print(f"\n  Iteration {iteration}: exhausted {max_proposal_attempts} proposal "
                  f"attempts without passing validation. Workflow stopping.")
            break

        # --- Tune ---
        tuning_dir = os.path.join(iter_dir, "tuning")
        os.makedirs(tuning_dir, exist_ok=True)
        tuning_run_name = f"{iter_run_name}_tune"
        tuning_storage = _make_storage(tuning_dir, tuning_run_name)

        print(f"  [{iteration}] Tuning '{proposal.model_name}' for {max_rounds} rounds...")
        tune_input = local_validated_model(
            validation, proposal, tuning_storage,
            max_rounds=max_rounds,
            file_index=file_index,
            llm_provider=llm_provider,
            llm_model_id=llm_model_id,
        )
        if human_advice_tune is not None:
            tune_input.human_advice = human_advice_tune

        tune_output = HyperparamTuningAgent().run(tune_input)
        iteration_results.append(tune_output)

        # --- Accumulate results for next iteration ---
        all_model_types.append(proposal.model_name)
        new_groups = tuning_outputs_to_summary_groups([tune_output])
        summary_groups.extend(new_groups)

        # --- Check score target ---
        if tune_output.best_denoising_score is not None:
            if best_score_overall is None or tune_output.best_denoising_score > best_score_overall:
                best_score_overall = tune_output.best_denoising_score

        print(f"\n  [{iteration}] Complete: {proposal.model_name} "
              f"best_score={tune_output.best_denoising_score}")

        if target_score is not None and best_score_overall is not None and best_score_overall >= target_score:
            print(f"\n  Target score {target_score} reached "
                  f"(best={best_score_overall}). Stopping early.")
            break

    # --- Final summary ---
    finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"  Workflow Complete")
    print(f"  Started     : {started_at}")
    print(f"  Finished    : {finished_at}")
    print(f"  Iterations  : {len(iteration_results)}/{max_iterations}")
    print(f"  Best overall: {best_score_overall}")
    for i, result in enumerate(iteration_results, 1):
        print(f"    Iteration {i}: {result.model_type} "
              f"score={result.best_denoising_score}")
    print(f"{'='*60}\n")

    _save_workflow_summary(
        workspace, run_name, started_at, finished_at,
        iteration_results, best_score_overall,
    )

    return iteration_results


def _save_workflow_summary(
    workspace: str,
    run_name: str,
    started_at: str,
    finished_at: str,
    iteration_results: list[HyperparamTuningOutput],
    best_score_overall: float | None,
):
    """Save a JSON summary of the full workflow run."""
    summary = {
        "workflow": "model_exploration",
        "run_name": run_name,
        "status": "completed" if iteration_results else "failed",
        "started_at": started_at,
        "finished_at": finished_at,
        "total_iterations": len(iteration_results),
        "best_score_overall": best_score_overall,
        "iterations": [
            {
                "model_type": r.model_type,
                "best_score": r.best_denoising_score,
                "completed_rounds": r.completed_rounds,
                "status": r.status,
            }
            for r in iteration_results
        ],
    }
    path = os.path.join(workspace, f"workflow_{run_name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=4)
    print(f"  Workflow summary saved -> {path}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="SIDERIUS Model Exploration Workflow — "
                    "iteratively interpret results, propose new models, implement, "
                    "validate, and tune.",
    )
    parser.add_argument(
        "--data_dir", type=str, default="/home/klz/Data/SIDEREIS_DATA",
        help="Root data directory containing existing tuning results.",
    )
    parser.add_argument(
        "--models", type=str, nargs="+", required=True,
        help="Model types to include in initial interpretation (e.g. punet wavenet rnn).",
    )
    parser.add_argument(
        "--workspace", type=str, default="./workflow_output",
        help="Root output directory for this workflow run.",
    )
    parser.add_argument(
        "--run_name", type=str, default="explore_v1",
        help="Unique name for this workflow run.",
    )
    parser.add_argument(
        "--max_iterations", type=int, default=1,
        help="Number of successful iterations (default: 1 = single pass).",
    )
    parser.add_argument(
        "--max_rounds", type=int, default=10,
        help="Tuning budget per iteration (default: 10).",
    )
    parser.add_argument(
        "--max_proposal_attempts", type=int, default=3,
        help="Max propose→implement→validate retries per iteration (default: 3).",
    )
    parser.add_argument(
        "--target_score", type=float, default=None,
        help="Optional early stop: halt if best score >= target.",
    )
    parser.add_argument(
        "--file_index", type=int, default=6,
        help="Training/validation file index (default: 6).",
    )
    parser.add_argument(
        "--provider", type=str, default="gemini", choices=["gemini", "openai"],
        help="LLM provider for all nodes (default: gemini).",
    )
    parser.add_argument(
        "--model_id", type=str, default="gemini-3.1-flash-lite-preview",
        help="LLM model ID for all nodes.",
    )

    # Human advice per step (all optional)
    parser.add_argument(
        "--advice_interpret", type=str, default=None,
        help="Human guidance for interpretation steps.",
    )
    parser.add_argument(
        "--advice_propose", type=str, default=None,
        help="Human guidance for proposal steps "
             "(e.g. 'propose a lightweight model with < 100K params').",
    )
    parser.add_argument(
        "--advice_implement", type=str, default=None,
        help="Human guidance for implementation steps.",
    )
    parser.add_argument(
        "--advice_validate", type=str, default=None,
        help="Human guidance for validation steps.",
    )
    parser.add_argument(
        "--advice_tune", type=str, default=None,
        help="Human guidance for tuning steps "
             "(e.g. 'keep epochs <= 3 for quick testing').",
    )
    args = parser.parse_args()

    run_workflow(
        data_dir=args.data_dir,
        model_types=args.models,
        workspace=args.workspace,
        run_name=args.run_name,
        max_iterations=args.max_iterations,
        max_rounds=args.max_rounds,
        max_proposal_attempts=args.max_proposal_attempts,
        target_score=args.target_score,
        file_index=args.file_index,
        llm_provider=args.provider,
        llm_model_id=args.model_id,
        human_advice_interpret=args.advice_interpret,
        human_advice_propose=args.advice_propose,
        human_advice_implement=args.advice_implement,
        human_advice_validate=args.advice_validate,
        human_advice_tune=args.advice_tune,
    )


if __name__ == "__main__":
    main()
