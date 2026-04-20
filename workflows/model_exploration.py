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

Storage layout (run_name is consistent across all files):
  {workspace}/{run_name}/
  ├── workflow_{run_name}.json
  ├── iteration_001/
  │   ├── interpretation_{run_name}.json
  │   ├── attempt_001/
  │   │   ├── proposal_{run_name}.json
  │   │   ├── implementor_{run_name}.json
  │   │   ├── validation_{run_name}.json
  │   │   ├── models/{model_name}.py
  │   │   └── tests/test_{model_name}.py
  │   └── {model_name}/              (tuning output, named by proposed model)
  │       ├── run_output_{run_name}.json
  │       ├── summary_{run_name}.json
  │       ├── run_config_{run_name}.json
  │       ├── cached_models/
  │       ├── configs/
  │       └── records/
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
import shutil
import argparse
import time

# Ensure SIDERIUS root and ml_models/ are importable.
# ml_models/ uses flat internal imports (e.g. from models_format_sandbox import ...)
# which require ml_models/ on sys.path.
SIDERIUS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SIDERIUS_ROOT)
sys.path.insert(0, os.path.join(SIDERIUS_ROOT, "ml_models"))

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from agent.schemas.interpretation import InterpretationInput, ModelRunSummary
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from nodes.result_interpretation_agent import tuning_output_to_model_run_summary

from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import local_full_context
from agent.schemas.protocols.ml_model_propose_to_ml_model_impl import local_full_spec
from agent.schemas.protocols.ml_model_impl_to_ml_model_valid import local_all_fields
from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import local_validated_model

from nodes.result_interpretation_agent import ResultInterpretationAgent
from nodes.ml_model_proposal_agent import MLModelProposalAgent
from nodes.ml_model_implementor import MLModelImplementor
from nodes.ml_code_validator_agent import MLCodeValidatorAgent
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from agent.schemas.proposal import VocabEntry
from workflows.llm_config import WorkflowLLMConfig, ProposalLLMConfig, NodeLLMConfig


def _load_vocab_seed() -> list:
    """Load the canonical vocabulary seed from agent/schemas/vocab_seed.json.

    Returns a list of VocabEntry objects. Returns empty list if the file
    is missing (backward compat — legacy workflows without vocab).
    """
    seed_path = os.path.join(SIDERIUS_ROOT, "agent", "schemas", "vocab_seed.json")
    if not os.path.exists(seed_path):
        return []
    try:
        from agent.schemas.proposal import VocabEntry
        with open(seed_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return [VocabEntry.model_validate(entry) for entry in raw]
    except Exception as e:
        print(f"Warning: failed to load vocab seed: {e}")
        return []


def _get_reasoning_pipeline(
    llm_config: WorkflowLLMConfig,
    exploration_mode: str = "auto",
    minimum_boldness: float = 0.05,
):
    """Build a ReasoningPipelineConfig from the workflow's ProposalLLMConfig.

    Returns None if propose is not a ProposalLLMConfig (legacy mode).

    Args:
        llm_config: Workflow LLM config; must have a ProposalLLMConfig in the
            propose slot for the pipeline to be active.
        exploration_mode: One of "auto", "explore", "exploit".
            "auto" lets the pipeline resolver choose based on n_agent_proposed
            and vocab_diversity_ratio. "explore" and "exploit" force the mode
            regardless of those signals.
        minimum_boldness: Minimum required boldness for a FalsifiablePrediction
            (|predicted - current| / |current|). Predictions below this threshold
            trigger a causal_reasoning retry. Default 0.05.
    """
    if llm_config.propose and isinstance(llm_config.propose, ProposalLLMConfig):
        from agent.schemas.proposal import (
            ReasoningPipelineConfig, ReasoningStage, ResearchPolicy,
        )
        pipeline = ReasoningPipelineConfig(
            stages=[
                ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
                ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
            ],
            exploration_mode=exploration_mode,
            policy=ResearchPolicy(minimum_boldness=minimum_boldness),
        )
        return pipeline
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_tuning_outputs_from_paths(
    paths: list[str],
) -> list[HyperparamTuningOutput]:
    """
    Load HyperparamTuningOutput from an explicit list of JSON file paths.

    Used by per-iteration Slurm runs where each iteration's source data
    is a heterogeneous list of paths (original seeds + previous iterations'
    outputs), which can't be derived from a single run_name pattern.

    Args:
        paths: List of explicit paths to run_output_*.json files.

    Returns:
        List of validated HyperparamTuningOutput objects (one per path).
        Raises FileNotFoundError if any path is missing or invalid.
    """
    outputs = []
    missing = []
    for path in paths:
        if not os.path.exists(path):
            missing.append(f"  not found: {path}")
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            output = HyperparamTuningOutput.model_validate(data)
            outputs.append(output)
            print(f"  Loaded: {path} "
                  f"({output.model_type}, {len(output.all_records)} records, "
                  f"best={output.best_denoising_score})")
        except Exception as e:
            missing.append(f"  invalid: {path} — {e}")

    if missing:
        raise FileNotFoundError(
            f"Missing or invalid source files:\n"
            + "\n".join(missing)
        )
    return outputs


def load_tuning_outputs(
    data_dir: str,
    model_types: list[str],
    source_run_name: str,
) -> list[HyperparamTuningOutput]:
    """
    Backward-compat wrapper: load HyperparamTuningOutput from a single run by
    constructing paths from (data_dir, model_types, source_run_name).

    Looks for:
      {data_dir}/{model_type}/{source_run_name}/agent/run_output_{source_run_name}_agent.json

    Prefer ``load_tuning_outputs_from_paths()`` for new code.

    Args:
        data_dir: Root data directory (e.g. /home/klz/Data/SIDEREIS_DATA).
        model_types: Model type keys to load (e.g. ["punet", "wavenet"]).
        source_run_name: The run name to load from (e.g. "small_sample_trial_v0").

    Returns:
        List of validated HyperparamTuningOutput objects (one per model).
        Raises FileNotFoundError if any model's output is missing.
    """
    paths = [
        os.path.join(
            data_dir, model_type, source_run_name, "agent",
            f"run_output_{source_run_name}_agent.json",
        )
        for model_type in model_types
    ]
    return load_tuning_outputs_from_paths(paths)


def tuning_outputs_to_summaries(
    outputs: list[HyperparamTuningOutput],
) -> list[ModelRunSummary]:
    """
    Convert a list of HyperparamTuningOutput objects into condensed
    ModelRunSummary objects suitable for InterpretationInput.

    Raw experiment records are NOT carried forward — only aggregates
    and per-round scores/conclusions are extracted.
    """
    return [tuning_output_to_model_run_summary(o) for o in outputs]


def _make_storage(workspace: str, run_name: str) -> StorageConfig:
    """Create a StorageConfig pointing at a specific workspace directory."""
    return StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=workspace, run_name=run_name),
    )


def _register_plugin(impl_output, model_name: str, dest_plugin_dir: str):
    """
    Copy validated plugin files to ``dest_plugin_dir`` (the tuner's run-scoped
    plugin dir) so the training subprocess discovers them via
    ``SIDERIUS_PLUGIN_DIRS``.

    Copies:
      - {model_file_path}       → {dest_plugin_dir}/{model_name}.py
      - {description_file_path} → {dest_plugin_dir}/{model_name}/description.md

    Pre-Phase-4 this function copied to the legacy global
    ``agent_generated/models/``, which the training subprocess no longer
    scans once ``SIDERIUS_PLUGIN_DIRS`` is set (Phase 2). See
    docs/run_scoped_plugins.md.

    Also extends the in-process ``MODEL_REGISTRY`` / ``PLUGIN_CONFIG_REGISTRY``
    so the tuner's planner (same Python process as the workflow) can resolve
    the new model type without a re-scan.

    Skips gracefully if source files don't exist (e.g. in unit tests with mocks).
    """
    # Copy plugin file
    if os.path.isfile(impl_output.model_file_path):
        os.makedirs(dest_plugin_dir, exist_ok=True)
        dest_plugin = os.path.join(dest_plugin_dir, f"{model_name}.py")
        shutil.copy2(impl_output.model_file_path, dest_plugin)
        print(f"    Plugin registered → {dest_plugin}")
    else:
        print(f"    Warning: plugin file not found at {impl_output.model_file_path}, skipping registration")
        return

    # Copy description
    if os.path.isfile(impl_output.description_file_path):
        desc_dest_dir = os.path.join(dest_plugin_dir, model_name)
        os.makedirs(desc_dest_dir, exist_ok=True)
        dest_desc = os.path.join(desc_dest_dir, "description.md")
        shutil.copy2(impl_output.description_file_path, dest_desc)
        print(f"    Description registered → {dest_desc}")
    else:
        print(f"    Warning: description not found at {impl_output.description_file_path}, skipping registration")

    # Extend the already-cached MODEL_REGISTRY so the tuning agent can
    # find the new model type without re-importing models_sandbox.
    try:
        from ml_models.models_sandbox import MODEL_REGISTRY
        from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
        from ml_models.plugin_loader import _load_plugin

        plugin_data = _load_plugin(dest_plugin)
        if plugin_data:
            MODEL_REGISTRY[plugin_data["model_type"]] = plugin_data["model_class"]
            PLUGIN_CONFIG_REGISTRY[plugin_data["model_type"]] = plugin_data["config_class"]
            print(f"    Model '{model_name}' added to MODEL_REGISTRY")
    except Exception as e:
        print(f"    Warning: could not extend MODEL_REGISTRY: {e}")


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------

def run_workflow(
    workspace: str,
    run_name: str,
    # --- Source data: provide either source_paths OR (data_dir + model_types + source_run_name) ---
    source_paths: list[str] | None = None,
    data_dir: str | None = None,
    model_types: list[str] | None = None,
    source_run_name: str | None = None,
    max_iterations: int = 1,
    max_rounds: int = 10,
    max_proposal_attempts: int = 3,
    target_score: float | None = None,
    file_index: int = 6,
    llm_config: WorkflowLLMConfig | None = None,
    human_advice_interpret: str | None = None,
    human_advice_propose: str | None = None,
    human_advice_implement: str | None = None,
    human_advice_validate: str | None = None,
    human_advice_tune: str | None = None,
    human_advice_mindset: str | None = None,
    # --- Trial mode (optional — defaults preserve single-file behavior) ---
    is_trial: bool = False,
    trial_strategy: str = "snapshot",
    trial_portion: float = 0.1,
    target_files: list[int] | None = None,
    train_portion: float = 0.1,
    eval_strategy: str = "snapshot",
    eval_portion: float = 0.1,
    train_validation_align: bool = True,
    sampling_seed: int | None = None,
    train_base_seed: int | None = None,
    cleanup_denoised: bool = False,
    max_epochs: int | None = None,
    plan_overrides: dict | None = None,
    # --- Time-budget gate (evaluate_time_skill, docs/resource_estimator_implement.md §2.7.2 / Phase I) ---
    trial_time_budget_minutes: float | None = None,
    formal_time_budget_minutes: float | None = None,
    # --- VRAM-budget gate (evaluate_vram_skill, docs/resource_estimator_implement.md §10.9 / Phase K) ---
    # Tuner-only fan-out; no proposer-side gate in Phase K (§10.17).
    trial_vram_budget_gb: float | None = None,
    formal_vram_budget_gb: float | None = None,
    # --- Formal-mode training levers (Phase M, docs/resource_estimator_implement.md §12) ---
    # Training-side knobs applied on any round promoted to formal. Eval side in
    # formal mode is hardcoded to snapshot + eval_portion=1.0 in the tuner so
    # formal scores are architecturally comparable — see §12.2.
    formal_strategy: str = "snapshot",
    formal_portion: float = 0.1,
    formal_train_portion: float = 1.0,
    # --- Per-round attempt budget (Phase L, docs/resource_estimator_implement.md §11) ---
    # Tuner-only fan-out (no proposer-side equivalent). Defaults mirror the
    # schema/protocol defaults so omitting them at the workflow surface yields
    # the documented Phase L behaviour.
    attempts_per_round: int = 3,
    attempts_per_formal_round: int = 5,
    max_fail_rounds: int = 3,
    # --- Reasoning pipeline ---
    exploration_mode: str = "auto",
    minimum_boldness: float = 0.05,
    # --- Implementation retry ---
    max_impl_attempts: int = 3,
    # --- Phase K.8 debug instrumentation ---
    debug_dump_prompts: bool = False,
) -> list[HyperparamTuningOutput]:
    """
    Execute the model exploration workflow for one or more iterations.

    Each iteration: interpret → (propose → implement → validate) → tune.
    The propose→implement→validate inner loop retries on validation failure.

    Args:
        workspace: Root output directory for this workflow run.
        run_name: Unique name for this workflow run.
        source_paths: (preferred) Explicit list of HyperparamTuningOutput JSON file
            paths to load as historical context. Use this when chaining iterations
            across separate Slurm jobs — each iteration's source list = original
            seeds + all previous iteration outputs.
        data_dir: (legacy) Root data directory containing existing tuning results.
            Used only when source_paths is None.
        model_types: (legacy) List of model types to load from source_run_name.
            Used only when source_paths is None.
        source_run_name: (legacy) The run name to load initial tuning results from
            (e.g. "small_sample_trial_v0"). One output per model is loaded from
            {data_dir}/{model_type}/{source_run_name}/agent/. Used only when
            source_paths is None.
        max_iterations: Number of successful iterations (validated + tuned).
        max_rounds: Tuning budget per iteration.
        max_proposal_attempts: Max propose→implement→validate retries per iteration.
        target_score: Optional early stop — halt if best score >= target.
        file_index: Training/validation file index (ignored when is_trial=True).
        llm_config: Per-node LLM configuration. If None, each node uses its
            own built-in default. See WorkflowLLMConfig for details.
        human_advice_interpret: Human guidance for interpretation steps.
        human_advice_propose: Human guidance for proposal steps.
        human_advice_implement: Human guidance for implementation steps.
        human_advice_validate: Human guidance for validation steps.
        human_advice_tune: Human guidance for tuning steps.
        is_trial: Enable trial mode for the tuning agent.
        trial_strategy: Sampling strategy ('snapshot', 'anchors', 'target').
        trial_portion: Fraction of segments per file for training scope.
        target_files: File indices for 'target' strategy.
        train_portion: Per-epoch subsample from training scope.
        eval_strategy: Sampling strategy for validation.
        eval_portion: Fraction of segments per file for validation.
        train_validation_align: When True, train and eval scopes share segment indices.
        sampling_seed: Seed for SampleSet construction.
        train_base_seed: Base seed for per-epoch training subsampling.
        cleanup_denoised: Delete denoised H5 files after scoring.
        trial_time_budget_minutes: Wall-time budget (minutes) for the
            evaluate_time_skill gate on trial-mode rounds (plan.is_trial=True).
            Fanned out to BOTH ProposalInput (proposer's baseline gate) and
            HyperparamTuningInput (tuner's per-round gate). None = trial gate
            disabled. See docs/resource_estimator_implement.md §2.7.2 / Phase I.
        formal_time_budget_minutes: Same as above, but for formal-mode rounds
            (plan.is_trial=False). Sized independently because formal runs
            use the full dataset and are 50–100x longer.
        trial_vram_budget_gb: Per-mode VRAM ceiling (GB) for the
            evaluate_vram_skill gate on trial-mode rounds. Fanned out to
            HyperparamTuningInput only — Phase K has no proposer-side VRAM
            gate (deferred per §10.17). None → tuner's skill falls back to
            the defensive free×0.8 limit. See §10.9 / Phase K.
        formal_vram_budget_gb: Same as above, but for formal-mode rounds.
            Sized independently because formal rounds often use larger
            batch_size / segmentation_size so the VRAM ceiling can differ.

    Returns:
        List of HyperparamTuningOutput objects, one per successful iteration.
    """
    if llm_config is None:
        llm_config = WorkflowLLMConfig()

    # All workflow output goes under {workspace}/{run_name}/
    run_dir = os.path.join(workspace, run_name)
    os.makedirs(run_dir, exist_ok=True)
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")

    print(f"\n{'='*60}")
    print(f"  SIDERIUS Model Exploration Workflow")
    print(f"  Started       : {started_at}")
    if source_paths is not None:
        print(f"  Source paths  : {len(source_paths)} files")
        for p in source_paths:
            print(f"    - {p}")
    else:
        print(f"  Source run    : {source_run_name}")
        print(f"  Models        : {model_types}")
    print(f"  Workspace     : {workspace}")
    print(f"  Run name      : {run_name}")
    print(f"  LLM config    : {llm_config.model_dump(exclude_none=True)}")
    print(f"  Iterations    : {max_iterations}")
    print(f"  Tune rounds   : {max_rounds} per iteration")
    print(f"  Proposal tries: {max_proposal_attempts} per iteration")
    if target_score is not None:
        print(f"  Target score  : {target_score}")
    print(f"{'='*60}\n")

    # --- Step 0: Load existing tuning outputs ---
    print("Step 0: Loading existing tuning outputs...")
    if source_paths is not None:
        tuning_outputs = load_tuning_outputs_from_paths(source_paths)
    elif data_dir and model_types and source_run_name:
        tuning_outputs = load_tuning_outputs(data_dir, model_types, source_run_name)
    else:
        raise ValueError(
            "Must provide either source_paths OR "
            "(data_dir + model_types + source_run_name)."
        )
    seed_summaries = tuning_outputs_to_summaries(tuning_outputs)
    print(f"  Loaded {len(tuning_outputs)} tuning outputs "
          f"across {len(set(o.model_type for o in tuning_outputs))} model types.\n")

    # Track all model types seen (for duplicate name guard)
    all_model_types = list({o.model_type for o in tuning_outputs})

    # --- Load vocabulary seed + reasoning pipeline config ---
    vocab_seed = _load_vocab_seed()
    reasoning_pipeline = _get_reasoning_pipeline(
        llm_config,
        exploration_mode=exploration_mode,
        minimum_boldness=minimum_boldness,
    )
    if vocab_seed:
        print(f"  Vocab seed: {len(vocab_seed)} entries loaded.")
    if reasoning_pipeline and reasoning_pipeline.stages:
        print(f"  Reasoning pipeline: {[s.name for s in reasoning_pipeline.stages]} "
              f"({reasoning_pipeline.exploration_mode} mode)")
    else:
        print(f"  Reasoning pipeline: legacy 2-call mode (no stages configured).")

    # Collect results across iterations
    iteration_results: list[HyperparamTuningOutput] = []
    best_score_overall: float | None = None

    # Long-term memory: variables carried forward across iterations
    previous_proposal_data: dict | None = None  # serialized ProposalOutput from iter N-1
    current_runtime_vocab = list(vocab_seed)     # starts with seed, grows with discoveries
    model_knowledge_cache: dict = {}             # per-model Phase 1 cache (grows once per model)
    latest_new_summary = None                    # ModelRunSummary from the most recent tune
    # Phase K.7.5 — retain the previous iteration's tuner output so the
    # interp→propose protocol can surface its gate_exhaustion to the next
    # proposer (docs/resource_estimator_implement.md §10.13). None on
    # iteration 1; assigned at the end of every subsequent iteration.
    previous_tune_output: HyperparamTuningOutput | None = None

    # --- Iteration loop ---
    for iteration in range(1, max_iterations + 1):
        iter_dir = os.path.join(run_dir, f"iteration_{iteration:03d}")
        os.makedirs(iter_dir, exist_ok=True)

        print(f"\n{'='*60}")
        print(f"  ITERATION {iteration}/{max_iterations}")
        print(f"  Directory: {iter_dir}")
        print(f"{'='*60}\n")

        # --- Interpret (once per iteration) ---
        # Iteration 1: all seeds are new (cache is empty).
        # Iteration 2+: only the model tuned in the previous iteration is new.
        if iteration == 1:
            new_summaries = seed_summaries
        else:
            new_summaries = [latest_new_summary] if latest_new_summary is not None else []

        interp_storage = _make_storage(iter_dir, run_name)
        interp_input = InterpretationInput(
            summaries=new_summaries,
            model_knowledge_cache=model_knowledge_cache,
            human_advice=human_advice_interpret,
            runtime_vocab=current_runtime_vocab,
            previous_proposal=previous_proposal_data,
            storage=interp_storage,
        )

        print(f"  [{iteration}] Interpreting experiment results...")
        interpretation = ResultInterpretationAgent(
            **llm_config.get("interpret"),
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
            print(f"  [{iteration}.{attempt}] Proposing new model (attempt {attempt}/{max_proposal_attempts})...")

            # Create a temporary attempt dir; renamed after model name is known
            attempt_dir = os.path.join(iter_dir, f"attempt_{attempt:03d}")
            os.makedirs(attempt_dir, exist_ok=True)
            attempt_storage = _make_storage(attempt_dir, run_name)

            try:
                # --- Propose ---
                # Forward the trial-mode mirror + budget set so the proposer's
                # evaluate_time_skill gate constructs the same sample_set the
                # tuner will (docs/resource_estimator_implement.md §2.7.2).
                propose_input = local_full_context(
                    interpretation,
                    attempt_storage,
                    vocab_seed=vocab_seed,
                    reasoning_pipeline=reasoning_pipeline,
                    human_advice=human_advice_propose,
                    is_trial=is_trial,
                    trial_strategy=trial_strategy,
                    trial_portion=trial_portion,
                    target_files=target_files,
                    train_portion=train_portion,
                    sampling_seed=sampling_seed,
                    trial_time_budget_minutes=trial_time_budget_minutes,
                    formal_time_budget_minutes=formal_time_budget_minutes,
                    data_dir=data_dir,
                    recent_tune_outputs=(
                        [previous_tune_output] if previous_tune_output is not None else []
                    ),
                )
                propose_input.existing_model_types = list(all_model_types)
                if previous_failures:
                    propose_input.previous_failures = previous_failures
                if human_advice_mindset is not None:
                    propose_input.mindset = human_advice_mindset

                # Phase K.8 debug — dump rendered proposing-stage system
                # prompt under {run_dir}/debug/ when the flag is on.
                if debug_dump_prompts:
                    propose_input.debug_dump_proposing_prompt_path = os.path.join(
                        run_dir, "debug",
                        f"iter{iteration:03d}_attempt{attempt:03d}"
                        "_proposing_system_prompt.md",
                    )

                proposal = MLModelProposalAgent(
                    **llm_config.get("propose"),
                ).run(propose_input)
                print(f"    Proposed: {proposal.model_name}")

                # Rename attempt dir to include model name
                named_dir = os.path.join(iter_dir, f"attempt_{attempt:03d}_{proposal.model_name}")
                os.rename(attempt_dir, named_dir)
                attempt_dir = named_dir
                attempt_storage = _make_storage(attempt_dir, run_name)

                # --- Implement → Validate (inner retry loop per proposal) ---
                # Load reference code once (shared across impl attempts for this proposal)
                ref_code: dict = {}
                if hasattr(proposal, 'inherited_components') and proposal.inherited_components:
                    from nodes.proposal_helpers import load_model_source
                    ref_models = set()
                    for ic in proposal.inherited_components:
                        mt = ic.from_model_type if hasattr(ic, 'from_model_type') else ic.get('from_model_type')
                        if mt:
                            ref_models.add(mt)
                    for mt in ref_models:
                        src = load_model_source(mt)
                        if src:
                            ref_code[mt] = src
                    if ref_code:
                        print(f"    Reference code: {list(ref_code.keys())} "
                              f"({sum(len(v.split(chr(10))) for v in ref_code.values())} lines)")

                valid_llm = llm_config.get("validate")
                previous_validation_failure: str | None = None

                for impl_attempt in range(1, max_impl_attempts + 1):
                    impl_suffix = (f" (impl {impl_attempt}/{max_impl_attempts})"
                                   if max_impl_attempts > 1 else "")
                    print(f"  [{iteration}.{attempt}] Implementing{impl_suffix}...")
                    impl_input = local_full_spec(proposal, attempt_storage)
                    impl_input.plugin_dir = os.path.join(attempt_dir, "models")
                    impl_input.test_dir = os.path.join(attempt_dir, "tests")
                    if human_advice_implement is not None:
                        impl_input.human_advice = human_advice_implement
                    if ref_code:
                        impl_input.reference_code = ref_code
                    if previous_validation_failure is not None:
                        impl_input.previous_validation_failure = previous_validation_failure

                    impl_output = MLModelImplementor(
                        **llm_config.get("implement"),
                    ).run(impl_input)
                    print(f"    Plugin: {impl_output.model_file_path}")

                    # --- Validate ---
                    print(f"  [{iteration}.{attempt}] Validating...")
                    valid_input = local_all_fields(
                        impl_output, attempt_storage,
                        llm_provider=valid_llm.get("provider", "gemini"),
                        llm_model_id=valid_llm.get("model_id", "gemini-3.1-flash-lite-preview"),
                    )
                    if human_advice_validate is not None:
                        valid_input.human_advice = human_advice_validate
                    if hasattr(proposal, 'inherited_components') and proposal.inherited_components:
                        valid_input.inherited_components = proposal.inherited_components

                    validation = MLCodeValidatorAgent(
                        **valid_llm,
                    ).run(valid_input)

                    if validation.passed:
                        print(f"    All 7 checks passed.\n")
                        break

                    previous_validation_failure = validation.error_message or "Unknown validation error"
                    print(f"    Validation FAILED: {previous_validation_failure}")
                    if impl_attempt < max_impl_attempts:
                        print(f"    Retrying implementation with validator feedback...\n")

                if validation and validation.passed:
                    break

                # All impl attempts for this proposal exhausted
                previous_failures.append(previous_validation_failure or "Unknown error")
                if attempt < max_proposal_attempts:
                    print(f"    Retrying with a new proposal...\n")

            except Exception as e:
                error_msg = f"Node error: {type(e).__name__}: {e}"
                print(f"    ERROR: {error_msg}")
                previous_failures.append(error_msg)
                if attempt < max_proposal_attempts:
                    print(f"    Retrying with failure feedback...\n")

        if not validation or not validation.passed:
            print(f"\n  Iteration {iteration}: exhausted {max_proposal_attempts} proposal "
                  f"attempts without passing validation. Skipping to next iteration.")
            continue

        # --- Tune (set up storage + run-scoped plugin dir up front) ---
        tuning_dir = os.path.join(iter_dir, proposal.model_name)
        os.makedirs(tuning_dir, exist_ok=True)
        tuning_storage = _make_storage(tuning_dir, run_name)

        # --- Register validated plugin into the tuner's run-scoped dir so
        #     the training subprocess picks it up via SIDERIUS_PLUGIN_DIRS
        #     (docs/run_scoped_plugins.md, Phase 4). The tuner's sandbox has
        #     not been constructed yet, but ``get_plugin_dir`` is the
        #     single source of truth for the layout, so the workflow can
        #     write here safely; the sandbox will ``_ensure_dir`` the same
        #     path moments later without disturbing existing contents.
        from core.sandbox_executor import get_plugin_dir
        dest_plugin_dir = get_plugin_dir(tuning_dir, run_name)
        _register_plugin(impl_output, proposal.model_name, dest_plugin_dir)

        print(f"  [{iteration}] Tuning '{proposal.model_name}' for {max_rounds} rounds...")
        tune_llm = llm_config.get("tune")
        tune_input = local_validated_model(
            validation, proposal, tuning_storage,
            max_rounds=max_rounds,
            file_index=file_index,
            llm_provider=tune_llm.get("provider", "gemini"),
            llm_model_id=tune_llm.get("model_id", "gemini-3.1-flash-lite-preview"),
            reflect_provider=tune_llm.get("reflect_provider"),
            reflect_model_id=tune_llm.get("reflect_model_id"),
            is_trial=is_trial,
            trial_strategy=trial_strategy,
            trial_portion=trial_portion,
            target_files=target_files,
            train_portion=train_portion,
            eval_strategy=eval_strategy,
            eval_portion=eval_portion,
            train_validation_align=train_validation_align,
            sampling_seed=sampling_seed,
            train_base_seed=train_base_seed,
            cleanup_denoised=cleanup_denoised,
            max_epochs=max_epochs,
            max_retries=tune_llm.get("max_retries"),
            plan_overrides=plan_overrides,
            trial_time_budget_minutes=trial_time_budget_minutes,
            formal_time_budget_minutes=formal_time_budget_minutes,
            data_dir=data_dir,
            trial_vram_budget_gb=trial_vram_budget_gb,
            formal_vram_budget_gb=formal_vram_budget_gb,
            formal_strategy=formal_strategy,
            formal_portion=formal_portion,
            formal_train_portion=formal_train_portion,
            attempts_per_round=attempts_per_round,
            attempts_per_formal_round=attempts_per_formal_round,
            max_fail_rounds=max_fail_rounds,
        )
        if human_advice_tune is not None:
            tune_input.human_advice = human_advice_tune

        tune_output = HyperparamTuningAgent().run(tune_input)
        iteration_results.append(tune_output)
        # Phase K.7.5 — retain for the next iteration's local_full_context
        # call so its gate_exhaustion (if any) reaches the next proposer.
        previous_tune_output = tune_output

        # --- Update long-term memory for next iteration ---
        all_model_types.append(proposal.model_name)

        # Build ModelRunSummary for the newly tuned model (fed to iter N+1 as new_summaries)
        new_model_summaries = tuning_outputs_to_summaries([tune_output])
        for s in new_model_summaries:
            # Attach description so iter N+1 interpretation agent can find it
            # without filesystem access to the attempt directory
            s.model_description = proposal.model_description
        latest_new_summary = new_model_summaries[0]

        # Update knowledge cache from interpretation output
        if hasattr(interpretation, "model_knowledge_cache") and interpretation.model_knowledge_cache:
            model_knowledge_cache = dict(interpretation.model_knowledge_cache)
            print(f"  [{iteration}] Knowledge cache: {len(model_knowledge_cache)} models cached.")

        # Update runtime vocab from interpretation output
        previous_proposal_data = proposal.model_dump()
        if hasattr(interpretation, "runtime_vocab") and interpretation.runtime_vocab:
            current_runtime_vocab = [
                v if hasattr(v, "name") else VocabEntry.model_validate(v)
                for v in interpretation.runtime_vocab
            ]
            print(f"  [{iteration}] Vocab updated: {len(current_runtime_vocab)} entries "
                  f"({sum(1 for v in current_runtime_vocab if v.kind == 'discovery')} discoveries)")

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
        run_dir, run_name, started_at, finished_at,
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
        "--data_dir", type=str, default=None,
        help="Root data directory containing existing tuning results.",
    )
    parser.add_argument(
        "--models", type=str, nargs="+", required=True,
        help="Model types to include in initial interpretation (e.g. punet wavenet rnn).",
    )
    parser.add_argument(
        "--source_run_name", type=str, required=True,
        help="Run name to load initial tuning results from (e.g. 'v3_file6'). "
             "One output per model is loaded from {data_dir}/{model}/{source_run_name}/agent/.",
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
    # LLM configuration
    parser.add_argument(
        "--llm_config", type=str, default=None,
        help="Path to a JSON file with per-node LLM config. "
             "Format: {\"interpret\": {\"provider\": \"gemini\", \"model_id\": \"...\"}, ...}. "
             "Nodes not listed use their built-in defaults.",
    )
    parser.add_argument(
        "--provider", type=str, default=None, choices=["gemini", "openai"],
        help="LLM provider for ALL nodes (shorthand — overridden by --llm_config).",
    )
    parser.add_argument(
        "--model_id", type=str, default=None,
        help="LLM model ID for ALL nodes (shorthand — overridden by --llm_config).",
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

    if args.data_dir is None:
        from execute_tools.data_paths import SIDERIUS_DATA_DIR
        args.data_dir = SIDERIUS_DATA_DIR

    # Build LLM config: --llm_config file takes precedence, then --provider/--model_id
    if args.llm_config:
        wf_llm_config = WorkflowLLMConfig.from_json(args.llm_config)
    elif args.provider and args.model_id:
        wf_llm_config = WorkflowLLMConfig.uniform(args.provider, args.model_id)
    elif args.provider:
        wf_llm_config = WorkflowLLMConfig.uniform(args.provider, "gemini-3.1-flash-lite-preview")
    else:
        wf_llm_config = None  # each node uses its own default

    run_workflow(
        data_dir=args.data_dir,
        model_types=args.models,
        source_run_name=args.source_run_name,
        workspace=args.workspace,
        run_name=args.run_name,
        max_iterations=args.max_iterations,
        max_rounds=args.max_rounds,
        max_proposal_attempts=args.max_proposal_attempts,
        target_score=args.target_score,
        file_index=args.file_index,
        llm_config=wf_llm_config,
        human_advice_interpret=args.advice_interpret,
        human_advice_propose=args.advice_propose,
        human_advice_implement=args.advice_implement,
        human_advice_validate=args.advice_validate,
        human_advice_tune=args.advice_tune,
    )


if __name__ == "__main__":
    main()
