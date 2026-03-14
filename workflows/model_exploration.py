#!/usr/bin/env python3
"""
workflows/model_exploration.py — First SIDERIUS workflow.

A single-pass traversal of the core research loop:

  tune (existing results)
    → interpret     [local_all_records]
    → propose       [local_full_context]
    → implement     [local_full_spec]
    → validate      [local_all_fields]
    → tune          [local_validated_model]  (fan-in: validator + proposal)

This is a workflow, not an orchestrator — the path is fixed and deterministic.
If any node fails, the workflow stops. Retry logic belongs in a future
orchestrator, not here.

Inputs:
  - A directory containing existing HyperparamTuningOutput JSON files
    (from previous runs of tune_ml_hyperparam_agent via run_comparison.py).
  - CLI args for LLM provider, tuning budget, etc.

Usage:
  python workflows/model_exploration.py \\
      --data_dir /home/klz/Data/SIDEREIS_DATA \\
      --models punet wavenet \\
      --workspace ./workflow_output \\
      --run_name explore_v1 \\
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
from agent.schemas.interpretation import SummaryGroup
from agent.schemas.storage import StorageConfig, LocalStorageConfig

from agent.schemas.protocols.ml_model_tune_to_ml_result_interp import local_all_records
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


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------

def run_workflow(
    data_dir: str,
    model_types: list[str],
    workspace: str,
    run_name: str,
    max_rounds: int = 10,
    file_index: int = 6,
    llm_provider: str = "gemini",
    llm_model_id: str = "gemini-3.1-flash-lite-preview",
    human_advice_interpret: str | None = None,
    human_advice_propose: str | None = None,
    human_advice_implement: str | None = None,
    human_advice_validate: str | None = None,
    human_advice_tune: str | None = None,
):
    """
    Execute the model exploration workflow: interpret → propose → implement →
    validate → tune.

    Args:
        data_dir: Root data directory containing existing tuning results.
        model_types: List of model types to include in interpretation.
        workspace: Output directory for this workflow run.
        run_name: Unique name for this workflow run.
        max_rounds: Tuning budget for the new model.
        file_index: Training/validation file index.
        llm_provider: LLM provider for all nodes.
        llm_model_id: LLM model ID for all nodes.
        human_advice_interpret: Human guidance for the interpretation step.
        human_advice_propose: Human guidance for the proposal step.
        human_advice_implement: Human guidance for the implementation step.
        human_advice_validate: Human guidance for the validation step.
        human_advice_tune: Human guidance for the tuning step.
    """
    os.makedirs(workspace, exist_ok=True)
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")

    storage = StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=workspace, run_name=run_name),
    )

    print(f"\n{'='*60}")
    print(f"  SIDERIUS Model Exploration Workflow")
    print(f"  Started   : {started_at}")
    print(f"  Models    : {model_types}")
    print(f"  Workspace : {workspace}")
    print(f"  Run name  : {run_name}")
    print(f"  LLM       : {llm_provider}/{llm_model_id}")
    print(f"  Tune rounds: {max_rounds}")
    print(f"{'='*60}\n")

    # --- Step 0: Load existing tuning outputs ---
    print("Step 0: Loading existing tuning outputs...")
    tuning_outputs = load_tuning_outputs(data_dir, model_types)
    summary_groups = tuning_outputs_to_summary_groups(tuning_outputs)
    print(f"  Loaded {len(tuning_outputs)} tuning outputs "
          f"across {len(set(o.model_type for o in tuning_outputs))} model types.\n")

    # --- Edge 1: tune → interpret ---
    # We have multiple tuning outputs, so we build InterpretationInput directly
    # from summary groups rather than using local_all_records (which handles
    # a single HyperparamTuningOutput). This is equivalent — same schema,
    # same validation.
    from agent.schemas.interpretation import InterpretationInput
    interp_input = InterpretationInput(
        summaries=summary_groups,
        human_advice=human_advice_interpret,
        storage=storage,
    )

    print("Step 1: Interpreting experiment results...")
    interpretation = ResultInterpretationAgent(
        provider=llm_provider, model_id=llm_model_id,
    ).run(interp_input)
    print(f"  Take-home: {interpretation.take_home_message}")
    print(f"  Best score: {interpretation.best_denoising_score}")
    print(f"  Models analysed: {interpretation.model_types}\n")

    # --- Edge 2: interpret → propose ---
    print("Step 2: Proposing new model architecture...")
    propose_input = local_full_context(interpretation, storage)
    if human_advice_propose is not None:
        propose_input.human_advice = human_advice_propose
    proposal = MLModelProposalAgent(
        provider=llm_provider, model_id=llm_model_id,
    ).run(propose_input)
    print(f"  Proposed model: {proposal.model_name}")
    print(f"  Motivation: {proposal.motivation[:120]}...")
    print()

    # --- Edge 3: propose → implement ---
    print("Step 3: Implementing proposed model...")
    impl_input = local_full_spec(proposal, storage)
    if human_advice_implement is not None:
        impl_input.human_advice = human_advice_implement
    impl_output = MLModelImplementor(
        provider=llm_provider, model_id=llm_model_id,
    ).run(impl_input)
    print(f"  Plugin file: {impl_output.model_file_path}")
    print(f"  Test file  : {impl_output.test_file_path}")
    print(f"  Description: {impl_output.description_file_path}")
    print()

    # --- Edge 4: implement → validate ---
    print("Step 4: Validating implemented model...")
    valid_input = local_all_fields(impl_output, storage,
                                   llm_provider=llm_provider,
                                   llm_model_id=llm_model_id)
    if human_advice_validate is not None:
        valid_input.human_advice = human_advice_validate
    validation = MLCodeValidatorAgent(
        provider=llm_provider, model_id=llm_model_id,
    ).run(valid_input)

    if not validation.passed:
        print(f"\n  Validation FAILED: {validation.error_message}")
        print(f"  The workflow stops here. In a future orchestrator, this would")
        print(f"  trigger a retry loop back to the implementor.")

        # Save workflow status
        _save_workflow_status(workspace, run_name, started_at,
                              status="failed_validation",
                              proposal=proposal, validation=validation)
        sys.exit(1)

    print(f"  All 7 checks passed.")
    print()

    # --- Edge 5: validate → tune (fan-in: validator + proposal) ---
    print(f"Step 5: Tuning new model '{proposal.model_name}' for {max_rounds} rounds...")
    tune_input = local_validated_model(
        validation, proposal, storage,
        max_rounds=max_rounds,
        file_index=file_index,
        llm_provider=llm_provider,
        llm_model_id=llm_model_id,
    )
    if human_advice_tune is not None:
        tune_input.human_advice = human_advice_tune
    tune_output = HyperparamTuningAgent().run(tune_input)

    # --- Summary ---
    finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"  Workflow Complete")
    print(f"  Started  : {started_at}")
    print(f"  Finished : {finished_at}")
    print(f"  New model: {proposal.model_name}")
    print(f"  Tuning   : {tune_output.completed_rounds}/{max_rounds} rounds")
    print(f"  Best score: {tune_output.best_denoising_score}")
    print(f"{'='*60}\n")

    _save_workflow_status(workspace, run_name, started_at,
                          status="completed",
                          proposal=proposal, validation=validation,
                          tune_output=tune_output, finished_at=finished_at)

    return tune_output


def _save_workflow_status(
    workspace: str,
    run_name: str,
    started_at: str,
    status: str,
    proposal=None,
    validation=None,
    tune_output=None,
    finished_at=None,
):
    """Save a JSON summary of the workflow run for later inspection."""
    summary = {
        "workflow": "model_exploration",
        "run_name": run_name,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at or time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if proposal:
        summary["proposed_model"] = proposal.model_name
        summary["motivation"] = proposal.motivation
    if validation:
        summary["validation_passed"] = validation.passed
        summary["validation_error"] = validation.error_message
    if tune_output:
        summary["tuning_status"] = tune_output.status
        summary["tuning_rounds"] = tune_output.completed_rounds
        summary["best_score"] = tune_output.best_denoising_score

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
                    "interpret existing results, propose and implement a new model, "
                    "validate it, and tune its hyperparameters.",
    )
    parser.add_argument(
        "--data_dir", type=str, default="/home/klz/Data/SIDEREIS_DATA",
        help="Root data directory containing existing tuning results.",
    )
    parser.add_argument(
        "--models", type=str, nargs="+", required=True,
        help="Model types to include in interpretation (e.g. punet wavenet rnn).",
    )
    parser.add_argument(
        "--workspace", type=str, default="./workflow_output",
        help="Output directory for this workflow run.",
    )
    parser.add_argument(
        "--run_name", type=str, default="explore_v1",
        help="Unique name for this workflow run.",
    )
    parser.add_argument(
        "--max_rounds", type=int, default=10,
        help="Tuning budget for the new model (default: 10).",
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
        help="Human guidance for the interpretation step.",
    )
    parser.add_argument(
        "--advice_propose", type=str, default=None,
        help="Human guidance for the proposal step "
             "(e.g. 'propose a lightweight model with < 100K params').",
    )
    parser.add_argument(
        "--advice_implement", type=str, default=None,
        help="Human guidance for the implementation step.",
    )
    parser.add_argument(
        "--advice_validate", type=str, default=None,
        help="Human guidance for the validation step.",
    )
    parser.add_argument(
        "--advice_tune", type=str, default=None,
        help="Human guidance for the tuning step "
             "(e.g. 'keep epochs <= 3 for quick testing').",
    )
    args = parser.parse_args()

    run_workflow(
        data_dir=args.data_dir,
        model_types=args.models,
        workspace=args.workspace,
        run_name=args.run_name,
        max_rounds=args.max_rounds,
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
