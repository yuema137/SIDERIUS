# nodes/ml_hyperparameter_tune_agent.py
"""
tune_ml_hyperparam_agent — Node 1 in the SIDERIUS graph.

Optimizes hyperparameters for a given ML model architecture over N rounds.
Each round: plan (LLM) → resource check → train → infer → score → reflect (LLM).

Node contract:
  run(input: HyperparamTuningInput) -> HyperparamTuningOutput
  CLI: --provider, --model_id, --expert_advice, --max_rounds, --force_model,
       --run_name, --workspace, --file_index, --progress_bar
"""

import os
import time
import json
import argparse
import importlib
import traceback
from typing import Optional, Union

from core.sandbox_executor import TidmadSandbox
from agent.llm_bridge import LLMBridge
from agent.schemas.hyperparam_tuning import (
    HyperparamTuningInput,
    HyperparamTuningOutput,
    ExperimentRecord,
    ExperimentPlan,
    ExpertAdvice,
    TrialConfig,
    serialize_expert_advice,
)
from execute_tools.sample_set_builder import build_sample_set
from execute_tools.scoring_utils import score_vector, SampleSet
from execute_tools.dataset_config import TIDMAD as DATASET_CONFIG
from execute_tools.build_anchor_map import load_anchor_map


def _validate_data_config(
    trial_config: TrialConfig,
    segmentation_size: int,
    dataset_config=DATASET_CONFIG,
) -> None:
    """
    Validate integer relationships between dataset, PSD segments, ML segments,
    and sampling portions. Called in the agent loop where all configs converge.

    Raises:
        ValueError: If any constraint is violated.
    """
    psd = dataset_config.psd_segment_length
    segs_per_file = dataset_config.segments_per_file

    # 1. PSD segment must divide evenly into ML segments
    if psd % segmentation_size != 0:
        raise ValueError(
            f"psd_segment_length ({psd}) must be divisible by "
            f"segmentation_size ({segmentation_size}). "
            f"Remainder: {psd % segmentation_size}."
        )

    # 2. trial_portion must produce at least 1 PSD segment per file
    if trial_config.mode != "single_file":
        eval_segs = max(1, round(trial_config.trial_portion * segs_per_file))
        if eval_segs < 1:
            raise ValueError(
                f"trial_portion ({trial_config.trial_portion}) produces 0 segments "
                f"from {segs_per_file} segments per file."
            )

        # 3. train_portion must produce at least 1 PSD segment from the scope
        train_segs = max(1, round(trial_config.train_portion * eval_segs))
        if train_segs < 1:
            raise ValueError(
                f"train_portion ({trial_config.train_portion}) of "
                f"{eval_segs} scope segments produces 0 training segments."
            )


def _run_skill(skill_folder: str, sandbox: TidmadSandbox, **params) -> dict:
    """
    Dynamically loads and executes a research skill (Training, Inference, or Scoring).
    """
    module_path = f"agent.skills.{skill_folder}.wrapper"
    try:
        skill_module = importlib.import_module(module_path)
        return skill_module.run_skill(sandbox, **params)
    except Exception as e:
        print(f"Skill Error [{skill_folder}]: {str(e)}")
        return {"status": "error", "message": str(e)}


# _serialize_expert_advice is now shared — imported as serialize_expert_advice
_serialize_expert_advice = serialize_expert_advice


# ---------------------------------------------------------------------------
# Node implementation
# ---------------------------------------------------------------------------

class HyperparamTuningAgent:
    """
    Hyperparameter tuning agent — optimizes model configs over N rounds.

    Each round: plan (LLM) → resource check → train → infer → score → reflect (LLM).
    OOM-risk configs are skipped but saved to memory. A hard cap of max_rounds * 3
    total attempts prevents infinite loops.

    Constructor dependency injection (see ``docs/pseudo_test_infra.md`` §4A):
      * ``bridge_factory``: callable that constructs an ``LLMBridge``-compatible
        object. Defaults to the real ``LLMBridge`` class. In pseudo-mode tests,
        the ``tuner_factories`` fixture passes a factory that returns a
        ``RecordingLLMBridge`` pre-loaded with canned responses.
      * ``sandbox_factory``: callable that constructs a ``TidmadSandbox``-
        compatible object. Defaults to the real ``TidmadSandbox``. In
        pseudo-mode tests, the fixture passes a factory that returns a
        ``RecordingSandbox`` pre-loaded with canned subprocess results.

    Production code never passes these — the defaults are the real classes,
    so the existing call ``HyperparamTuningAgent().run(input)`` continues to
    work identically. Only tests inject the fakes.
    """

    def __init__(self, bridge_factory=None, sandbox_factory=None):
        self._bridge_factory = bridge_factory or LLMBridge
        self._sandbox_factory = sandbox_factory or TidmadSandbox

    def run(self, agent_input: HyperparamTuningInput) -> HyperparamTuningOutput:
        """
        Execute the hyperparameter tuning loop.

        Args:
            agent_input: Validated HyperparamTuningInput with model_type, max_rounds,
                         expert_advice, storage config, and LLM config.

        Returns:
            HyperparamTuningOutput with status, best score, best config, and all records.
        """
        # --- Validate input ---
        agent_input = HyperparamTuningInput.model_validate(agent_input)

        # --- Extract frequently used fields ---
        workspace = agent_input.storage.local.workspace
        run_name = agent_input.storage.local.run_name
        model_type_setting = agent_input.model_type
        max_rounds = agent_input.max_rounds
        file_index = agent_input.file_index
        trial_allowed = agent_input.is_trial
        expert_advice_str = _serialize_expert_advice(agent_input.expert_advice)
        if agent_input.human_advice:
            human_section = f"\n[Human Guidance (high priority)]:\n{agent_input.human_advice}"
            expert_advice_str = (expert_advice_str + human_section) if expert_advice_str else agent_input.human_advice

        print(f"Input validated: model={model_type_setting} | rounds={max_rounds} "
              f"| file_index={file_index} | trial_allowed={trial_allowed} "
              f"| provider={agent_input.llm_provider}")

        # --- Initialize sandbox and brain (via factory for DI / pseudo-mode) ---
        sandbox = self._sandbox_factory(
            metadata_source="local",
            run_name=run_name,
            workspace=workspace,
            progress_bar=agent_input.progress_bar,
            file_index=file_index,
        )
        brain = self._bridge_factory(
            provider=agent_input.llm_provider,
            model_id=agent_input.llm_model_id,
            reflect_provider=agent_input.reflect_provider,
            reflect_model_id=agent_input.reflect_model_id,
            max_retries=agent_input.max_retries,
        )

        # --- Pre-load anchor map if any round might use trial mode ---
        anchor_map_data: Optional[dict] = None
        if trial_allowed:
            anchor_map_path = os.path.join(
                sandbox.dirs["data"], "segment_anchors.json"
            )
            if os.path.exists(anchor_map_path):
                anchor_map_data = load_anchor_map(anchor_map_path)
            else:
                raise FileNotFoundError(
                    f"Trial mode requires segment_anchors.json at {anchor_map_path}. "
                    "Run execute_tools/build_anchor_map.py first."
                )
            print(f"Trial mode enabled: anchor map loaded.")

        # Save run configuration once
        started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        run_config = {
            "provider":       agent_input.llm_provider,
            "model_id":       agent_input.llm_model_id,
            "run_name":       run_name,
            "force_model":    model_type_setting,
            "max_rounds":     max_rounds,
            "file_index":     file_index,
            "trial_allowed":  trial_allowed,
            "started_at":     started_at,
        }
        run_config_path = os.path.join(workspace, f"run_config_{run_name}.json")
        with open(run_config_path, "w", encoding="utf-8") as f:
            json.dump(run_config, f, indent=4)

        print(f"=== TIDMAD Agent Activated ===")
        print(f"Provider: {agent_input.llm_provider} | Model: {agent_input.llm_model_id}")
        print(f"Expert Advice: {expert_advice_str}")
        print(f"Max Rounds: {max_rounds} | Strategy: {model_type_setting}")

        # --- Get the config manual before starting ---
        print(f"Reading model configuration manual...")
        config_manual = _run_skill("check_config_format_skill", sandbox)
        if config_manual["status"] == "success":
            config_manual_data = config_manual["data"]
        else:
            raise ValueError("Config Manual not provided.")

        # --- Load model description (architecture explanation for the LLM) ---
        model_description = None
        try:
            from ml_models.model_descriptions import get_model_description
            model_description = get_model_description(model_type_setting)
            print(f"Loaded model description for '{model_type_setting}' ({len(model_description)} chars)")
        except (FileNotFoundError, Exception) as e:
            print(f"No model description found for '{model_type_setting}': {e}")

        # --- Autonomous Research Loop ---
        completed_rounds = 0
        total_attempts = 0
        max_attempts = max_rounds * 3

        while completed_rounds < max_rounds and total_attempts < max_attempts:
            total_attempts += 1
            iteration = completed_rounds + 1
            try:
                print(f"\n\n{'='*60}\nROUND {iteration}/{max_rounds} "
                      f"(attempt {total_attempts}): Planning...\n{'='*60}")

                # A. OBSERVE: Retrieve full Research Memory from summary.json
                memory_history = sandbox.get_summary()

                # Build exploration checklist from config schema + past records
                from agent.prompts import build_exploration_checklist
                from ml_models.models_format_sandbox import get_config_class
                config_cls = get_config_class(model_type_setting)
                config_schema = config_cls.model_json_schema() if config_cls else {}
                checklist = build_exploration_checklist(
                    config_schema=config_schema,
                    memory_history=memory_history,
                )

                # B. THINK: Plan next experiment
                decision = brain.plan(
                    memory_history,
                    expert_advice=expert_advice_str,
                    force_model=model_type_setting,
                    config_manual=config_manual_data,
                    model_description=model_description,
                    exploration_checklist=checklist,
                    current_round=iteration,
                    max_rounds=max_rounds,
                    trial_allowed=trial_allowed,
                )

                # Validate LLM output into ExperimentPlan (with fallback)
                plan = ExperimentPlan.with_defaults(decision)

                # Apply hard overrides from operator config (before other overrides).
                # Unknown keys are warned and skipped; invalid values are warned
                # and skipped — the run continues with the LLM's original value.
                if agent_input.plan_overrides:
                    valid_fields = set(ExperimentPlan.model_fields.keys())
                    unknown = set(agent_input.plan_overrides) - valid_fields
                    if unknown:
                        print(f"  [WARN] plan_overrides: ignoring unknown keys: {unknown}")
                    safe_overrides = {k: v for k, v in agent_input.plan_overrides.items() if k in valid_fields}
                    if safe_overrides:
                        try:
                            merged = plan.model_dump(by_alias=True) | safe_overrides
                            plan = ExperimentPlan.model_validate(merged)
                            print(f"  Plan overrides applied: {list(safe_overrides.keys())}")
                        except Exception as e:
                            print(f"  [WARN] plan_overrides validation failed ({e}); "
                                  f"using LLM plan as-is")

                # Override chain: expert constraint → final-round constraint → hard caps
                is_last_needed_round = (completed_rounds == max_rounds - 1)
                if not trial_allowed:
                    plan.is_trial = False
                if is_last_needed_round:
                    plan.is_trial = False

                # Enforce max_epochs hard cap (prevents LLM from choosing excessively long training)
                if agent_input.max_epochs is not None:
                    planned_epochs = plan.train_cfg.get("epochs", 1)
                    if planned_epochs > agent_input.max_epochs:
                        print(f"  Clamping epochs: {planned_epochs} → {agent_input.max_epochs} (max_epochs)")
                        plan.train_cfg["epochs"] = agent_input.max_epochs

                # Build and validate TrialConfig from plan + overrides
                if plan.is_trial:
                    mode = "trial"
                elif trial_allowed:
                    mode = "formal"
                else:
                    mode = "single_file"

                # In formal mode, eval uses all segments (portion=1.0).
                # In trial mode, eval uses the LLM's eval_portion.
                eval_portion = plan.eval_portion if mode == "trial" else 1.0

                # Generate deterministic seeds for reproducibility.
                import hashlib
                seed_input = f"{run_name}_{total_attempts}".encode()
                seed_hash = int(hashlib.sha256(seed_input).hexdigest(), 16)
                train_sampling_seed = agent_input.sampling_seed if agent_input.sampling_seed is not None else seed_hash % (2**31)
                train_base_seed = agent_input.train_base_seed if agent_input.train_base_seed is not None else (seed_hash >> 31) % (2**31)
                # Eval seed: same as train when aligned, different otherwise
                if plan.train_validation_align:
                    eval_sampling_seed = train_sampling_seed
                else:
                    eval_sampling_seed = (seed_hash >> 62) % (2**31)

                trial_config = TrialConfig(
                    is_trial=plan.is_trial,
                    mode=mode,
                    # Training
                    trial_strategy=plan.trial_strategy if mode != "single_file" else "snapshot",
                    trial_portion=plan.trial_portion,
                    train_portion=plan.train_portion,
                    target_files=plan.target_files if plan.is_trial else [],
                    # Validation
                    eval_strategy=plan.eval_strategy if mode != "single_file" else "snapshot",
                    eval_portion=eval_portion,
                    # Alignment
                    train_validation_align=plan.train_validation_align,
                    # Legacy
                    file_index=file_index if mode == "single_file" else None,
                    # Seeds
                    train_sampling_seed=train_sampling_seed,
                    eval_sampling_seed=eval_sampling_seed,
                    train_base_seed=train_base_seed,
                )

                # Validate integer relationships between dataset, PSD, ML segments
                _validate_data_config(trial_config, plan.model_cfg.get("segmentation_size", 10000))

                # Build TWO independent SampleSets — training and validation
                if trial_config.mode in ("trial", "formal"):
                    train_sample_set = build_sample_set(
                        is_trial=True,
                        trial_strategy=trial_config.trial_strategy,
                        trial_portion=trial_config.trial_portion,
                        target_files=trial_config.target_files or None,
                        seed=trial_config.train_sampling_seed,
                    )
                    eval_sample_set = build_sample_set(
                        is_trial=True,
                        trial_strategy=trial_config.eval_strategy,
                        trial_portion=trial_config.eval_portion,
                        target_files=trial_config.target_files or None,
                        seed=trial_config.eval_sampling_seed,
                    )
                    print(f"  {trial_config.mode.capitalize()} mode: "
                          f"train: {trial_config.trial_strategy} portion={trial_config.trial_portion} "
                          f"| eval: {trial_config.eval_strategy} portion={trial_config.eval_portion} "
                          f"| train_portion/epoch={trial_config.train_portion} "
                          f"| align={trial_config.train_validation_align}")
                else:
                    train_sample_set = None
                    eval_sample_set = None
                    print(f"  Legacy mode: file_index={file_index}")

                # Segment counts for records and reflector context
                if train_sample_set:
                    train_psd_segments = sum(len(v) for v in train_sample_set.values())
                else:
                    train_psd_segments = DATASET_CONFIG.segments_per_file  # legacy single-file

                if eval_sample_set:
                    eval_psd_segments = sum(len(v) for v in eval_sample_set.values())
                else:
                    eval_psd_segments = DATASET_CONFIG.segments_per_file  # legacy single-file

                # When force_model is set, override the LLM's model_type choice.
                if model_type_setting != "auto":
                    model_type = model_type_setting
                else:
                    model_type = plan.model_type
                exp_id = f"{model_type}_{run_name}_{total_attempts:03d}"
                hypothesis = plan.hypothesis

                print(f"Action: {model_type.upper()} | ID: {exp_id}")
                print(f"Hypothesis: {hypothesis}")
                print(f"Reasoning: {plan.reasoning or 'No reasoning provided.'}")

                # Save validated TrialConfig
                trial_config_path = os.path.join(
                    sandbox.dirs["configs"], f"trial_config_{exp_id}.json"
                )
                with open(trial_config_path, "w", encoding="utf-8") as f:
                    json.dump(trial_config.model_dump(), f, indent=2)

                # C. ACT: Execute the Atomic Skill Pipeline (Train -> Inf -> Score)
                model_config = plan.model_cfg.copy()
                # Ensure model_config.model_type matches the forced model type
                model_config["model_type"] = model_type
                active_params = {
                    "exp_id":            exp_id,
                    "run_name":          run_name,
                    "model_type":        model_type,
                    "model_config":      model_config,
                    "train_config":      plan.train_cfg,
                    "loss_config":       plan.loss_cfg,
                    "sample_set":        train_sample_set,    # training data (from training files)
                    "train_portion":     trial_config.train_portion,
                    "train_base_seed":   trial_config.train_base_seed,
                    "eval_sample_set":   eval_sample_set,     # validation data (from validation files)
                }

                # Clean params for records — exclude bulky SampleSet dicts
                record_params = {
                    "exp_id":       exp_id,
                    "run_name":     run_name,
                    "model_type":   model_type,
                    "model_config": model_config,
                    "train_config": plan.train_cfg,
                    "loss_config":  plan.loss_cfg,
                }

                print(f"\n[Step 0/3] Resource check...")
                resource_check = _run_skill("evaluate_resource_skill", sandbox, **active_params)
                if resource_check.get("status") == "error":
                    raise RuntimeError(f"Resource check error: {resource_check.get('message')}")

                if not resource_check.get("feasible", True):
                    print(f"Resource check FAILED — this attempt does NOT count as a round.")
                    print(f"   Verdict   : {resource_check.get('verdict', '')}")
                    print(f"   Suggestion: {resource_check.get('suggestion', '')}")

                    oom_record = {
                        "exp_id":          exp_id,
                        "status":          "skipped_oom_risk",
                        "model_type":      model_type,
                        "timestamp":       time.strftime("%Y-%m-%d %H:%M:%S"),
                        "file_index":      file_index,
                        "params":          record_params,
                        "denoising_score": None,
                        "memory": {
                            "expert_advice_followed": expert_advice_str,
                            "hypothesis":    hypothesis,
                            "conclusion":    (
                                f"Skipped: estimated VRAM ({resource_check.get('estimated_gb', '?')} GB) "
                                f"exceeds 80% safety limit ({resource_check.get('limit_gb', '?')} GB)."
                            ),
                            "discovery":     resource_check.get("verdict", ""),
                            "memory_update": resource_check.get("suggestion", "Reduce batch_size or segmentation_size."),
                        },
                    }
                    ExperimentRecord.model_validate(oom_record)
                    sandbox.save_record(oom_record)
                    continue

                print(f"\n[Step 1/3] Training...")
                t0 = time.time()
                train_status = _run_skill("training_skill", sandbox, **active_params)
                train_time = round(time.time() - t0, 1)
                if train_status.get("status") == "error":
                    error_msg = train_status.get("message", "Unknown training error")
                    is_oom = "CUDA out of memory" in error_msg or "OutOfMemoryError" in error_msg
                    # Truncate long tracebacks — keep last 500 chars for the LLM
                    short_msg = error_msg[-500:] if len(error_msg) > 500 else error_msg
                    error_record = {
                        "exp_id":          exp_id,
                        "status":          "error_training_oom" if is_oom else "error_training",
                        "model_type":      model_type,
                        "timestamp":       time.strftime("%Y-%m-%d %H:%M:%S"),
                        "file_index":      file_index,
                        "params":          record_params,
                        "denoising_score": None,
                        "memory": {
                            "expert_advice_followed": expert_advice_str,
                            "hypothesis":    hypothesis,
                            "conclusion":    f"Training failed: {short_msg}",
                            "discovery":     "CUDA OOM — reduce model size, batch_size, or segmentation_size." if is_oom else f"Training crashed: {short_msg}",
                            "memory_update": "This config exceeds GPU memory. Try smaller architecture." if is_oom else "Fix the error before retrying this config.",
                        },
                    }
                    ExperimentRecord.model_validate(error_record)
                    sandbox.save_record(error_record)
                    print(f"  Saved error record: {error_record['status']}")
                    continue

                print(f"[Step 2/3] Inference...")
                t0 = time.time()
                inf_status = _run_skill("inference_skill", sandbox, **active_params)
                inference_time = round(time.time() - t0, 1)
                if inf_status.get("status") == "error":
                    error_msg = inf_status.get("message", "Unknown inference error")
                    is_oom = "CUDA out of memory" in error_msg or "OutOfMemoryError" in error_msg
                    short_msg = error_msg[-500:] if len(error_msg) > 500 else error_msg
                    error_record = {
                        "exp_id":          exp_id,
                        "status":          "error_inference_oom" if is_oom else "error_inference",
                        "model_type":      model_type,
                        "timestamp":       time.strftime("%Y-%m-%d %H:%M:%S"),
                        "file_index":      file_index,
                        "params":          record_params,
                        "denoising_score": None,
                        "memory": {
                            "expert_advice_followed": expert_advice_str,
                            "hypothesis":    hypothesis,
                            "conclusion":    f"Inference failed: {short_msg}",
                            "discovery":     "CUDA OOM during inference — reduce batch_size or model size." if is_oom else f"Inference crashed: {short_msg}",
                            "memory_update": "Inference OOM — the model trained but can't infer. Try smaller batch." if is_oom else "Fix the inference error before retrying.",
                        },
                    }
                    ExperimentRecord.model_validate(error_record)
                    sandbox.save_record(error_record)
                    print(f"  Saved error record: {error_record['status']}")
                    continue

                print(f"[Step 3/3] Scoring...")
                t0 = time.time()
                if anchor_map_data is not None:
                    # Anchor-normalized scoring (both trial and formal modes).
                    # Trial: sparse SampleSet. Formal: full SampleSet (all 20 × 200).
                    def _denoised_fn(fi):
                        return f"abra_validation_denoised_{model_type}_{run_name}_{exp_id}_{fi:04d}.h5"
                    file_vector, final_scalar = score_vector(
                        data_dir=sandbox.base_dir,
                        sample_set=eval_sample_set,
                        anchor_map=anchor_map_data["anchors"],
                        s_max=anchor_map_data["s_max"],
                        denoised_filename_fn=_denoised_fn,
                        raw_data_dir=sandbox.dirs["data"],
                    )
                    score_res = {
                        "status": "success",
                        "results": {
                            "denoising_score": final_scalar,
                            "file_vector": file_vector,
                        },
                    }
                else:
                    # Legacy single-file mode (trial_allowed=False, no anchor map)
                    score_res = _run_skill("denoising_score_skill", sandbox, **active_params)
                scoring_time = round(time.time() - t0, 1)

                # Extract results from each stage
                train_results = train_status.get("results", {})
                score_results = score_res.get("results", {})

                # Cleanup denoised files to save disk space
                if agent_input.cleanup_denoised:
                    import glob as _glob
                    pattern = os.path.join(
                        sandbox.base_dir,
                        f"abra_validation_denoised_*_{exp_id}_*.h5",
                    )
                    denoised_files = _glob.glob(pattern)
                    if denoised_files:
                        total_bytes = sum(os.path.getsize(f) for f in denoised_files)
                        for f in denoised_files:
                            os.remove(f)
                        print(f"  Cleaned up {len(denoised_files)} denoised files "
                              f"({total_bytes / (1024**3):.1f} GB freed)")

                # D. REFLECT: Analyze results and generate insights
                print(f"\nGenerating Research Memory...")

                current_score     = score_results.get("denoising_score")
                current_loss_type = active_params["loss_config"].get("loss_type")
                successful = [
                    r for r in memory_history
                    if r.get("status") == "success" and r.get("denoising_score") is not None
                ]
                baseline_record = next(
                    (r for r in memory_history if "baseline" in r.get("exp_id", "")), None
                )
                all_scores   = [r["denoising_score"] for r in successful]
                best_score   = max(all_scores) if all_scores else None
                best_record  = max(successful, key=lambda r: r["denoising_score"]) if successful else None
                sorted_scores = sorted(all_scores, reverse=True)
                rank = sorted_scores.index(current_score) + 1 if current_score in sorted_scores else None

                same_loss_finals = [
                    r["final_loss"]
                    for r in successful
                    if r.get("params", {}).get("loss_config", {}).get("loss_type") == current_loss_type
                    and r.get("final_loss") is not None
                ]
                current_final_loss = train_results.get("final_loss")
                if current_final_loss is not None:
                    all_same_loss_finals  = same_loss_finals + [current_final_loss]
                    sorted_finals         = sorted(all_same_loss_finals)
                    same_loss_loss_rank   = sorted_finals.index(current_final_loss) + 1
                    same_loss_total       = len(all_same_loss_finals)
                else:
                    same_loss_loss_rank = None
                    same_loss_total     = len(same_loss_finals)

                current_params  = train_results.get("model_params")
                current_epochs  = active_params["train_config"].get("epochs")
                baseline_params = baseline_record.get("model_params") if baseline_record else None
                baseline_epochs = baseline_record.get("params", {}).get("train_config", {}).get("epochs") if baseline_record else None
                params_ratio    = round(current_params / baseline_params, 3) if (current_params and baseline_params) else None
                epochs_ratio    = round(current_epochs / baseline_epochs, 3) if (current_epochs and baseline_epochs) else None

                worst_score     = min(all_scores) if all_scores else None
                score_range     = (best_score - worst_score) if (best_score is not None and worst_score is not None and best_score != worst_score) else None
                score_threshold = (best_score - 0.05 * score_range) if score_range is not None else best_score
                best_params     = best_record.get("model_params") if best_record else None
                best_epochs     = best_record.get("params", {}).get("train_config", {}).get("epochs") if best_record else None
                is_more_efficient = (
                    score_threshold is not None
                    and current_score is not None
                    and current_score >= score_threshold
                    and (
                        (current_params is not None and best_params is not None and current_params < best_params)
                        or (current_epochs is not None and best_epochs is not None and current_epochs < best_epochs)
                    )
                )

                reflection_context = {
                    "baseline_score":           baseline_record.get("denoising_score") if baseline_record else None,
                    "best_score_so_far":        best_score,
                    "is_new_best":              current_score is not None and (best_score is None or current_score > best_score),
                    "rank":                     rank,
                    "total_experiments":        len(successful),
                    "best_config_so_far":       best_record.get("params") if best_record else None,
                    "best_same_loss_final_loss": min(same_loss_finals) if same_loss_finals else None,
                    "current_loss_type":        current_loss_type,
                    "same_loss_loss_rank":      same_loss_loss_rank,
                    "same_loss_total":          same_loss_total,
                    "baseline_params":          baseline_params,
                    "baseline_epochs":          baseline_epochs,
                    "current_params":           current_params,
                    "current_epochs":           current_epochs,
                    "params_ratio":             params_ratio,
                    "epochs_ratio":             epochs_ratio,
                    "is_more_efficient":        is_more_efficient,
                    "training_psd_segments":    train_psd_segments,
                    "eval_psd_segments":        eval_psd_segments,
                    "baseline_psd_segments":    baseline_record.get("training_psd_segments") if baseline_record else None,
                    "trial_portion":            trial_config.trial_portion if trial_config.mode != "single_file" else None,
                    "eval_portion":             trial_config.eval_portion if trial_config.mode != "single_file" else None,
                }

                # Pass both training and scoring results to the reflector
                reflect_results = {**train_results, **score_results}
                reflection = brain.reflect(exp_id, hypothesis, reflect_results, reflection_context)

                # Defensive unwrap: LLM occasionally emits [{...}] instead of {...}.
                if isinstance(reflection, list) and len(reflection) == 1 and isinstance(reflection[0], dict):
                    print("[reflect] LLM returned a single-element list — unwrapping to dict.")
                    reflection = reflection[0]
                if not isinstance(reflection, dict):
                    print(f"[reflect] LLM returned non-dict ({type(reflection).__name__}); using empty reflection.")
                    reflection = {}

                print(f"{'-'*30}")
                print(f"RESEARCH REFLECTION for {exp_id}:")
                print(f"Conclusion  : {reflection.get('conclusion', 'N/A')}")
                print(f"Key Factor  : {reflection.get('key_factor', 'N/A')}")
                print(f"Discovery   : {reflection.get('discovery', 'N/A')}")
                print(f"Memory Update: {reflection.get('memory_update', 'N/A')}")
                print(f"{'-'*30}")

                # E. COMMIT: Build, validate, and save the finalized record
                final_record = {
                    "exp_id":     exp_id,
                    "status":     "success",
                    "model_type": model_type,
                    "timestamp":  time.strftime("%Y-%m-%d %H:%M:%S"),
                    "file_index": file_index,
                    "params":     record_params,
                    # Training results
                    "final_loss":    train_results.get("final_loss"),
                    "loss_history":  train_results.get("loss_history"),
                    "model_params":  train_results.get("model_params"),
                    # Scoring results
                    "denoising_score": score_results.get("denoising_score"),
                    "file_vector":     score_results.get("file_vector"),
                    # Data volume
                    "training_psd_segments": train_psd_segments,
                    "eval_psd_segments":    eval_psd_segments,
                    "timing": {
                        "train_time_s":     train_time,
                        "inference_time_s": inference_time,
                        "scoring_time_s":   scoring_time,
                    },
                    "memory": {
                        "expert_advice_followed": expert_advice_str,
                        "hypothesis":    hypothesis,
                        "conclusion":    reflection.get("conclusion"),
                        "key_factor":    reflection.get("key_factor"),
                        "discovery":     reflection.get("discovery"),
                        "memory_update": reflection.get("memory_update"),
                    },
                }
                # Trial context
                if trial_config.is_trial:
                    final_record["is_trial"] = True
                    final_record["trial_strategy"] = trial_config.trial_strategy
                    final_record["trial_portion"] = trial_config.trial_portion
                    final_record["eval_strategy"] = trial_config.eval_strategy
                    final_record["eval_portion"] = trial_config.eval_portion
                    final_record["train_portion"] = trial_config.train_portion
                    if trial_config.trial_strategy == "target":
                        final_record["target_files"] = trial_config.target_files

                ExperimentRecord.model_validate(final_record)
                sandbox.save_record(final_record)

                completed_rounds += 1
                print(f"Round {completed_rounds}/{max_rounds} Complete. "
                      f"Score: {score_results.get('denoising_score', 'N/A')}")

                time.sleep(2)  # Cool-down to avoid API rate limits

            except Exception as e:
                print(f"Loop Error: {e}")
                traceback.print_exc()
                time.sleep(5)

        # --- Build, validate, and save the run output ---
        finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
        run_status = "completed" if completed_rounds >= max_rounds else "partial"
        all_records = sandbox.get_summary()
        successful_records = [
            r for r in all_records
            if r.get("status") == "success" and r.get("denoising_score") is not None
        ]
        top_record = max(successful_records, key=lambda r: r["denoising_score"]) if successful_records else None

        agent_output = HyperparamTuningOutput.model_validate({
            "run_name":             run_name,
            "model_type":           model_type_setting,
            "file_index":           file_index,
            "status":               run_status,
            "completed_rounds":     completed_rounds,
            "total_attempts":       total_attempts,
            "best_exp_id":          top_record.get("exp_id") if top_record else None,
            "best_denoising_score": top_record.get("denoising_score") if top_record else None,
            "best_config":          top_record.get("params") if top_record else None,
            "best_file_vector":     top_record.get("file_vector") if top_record else None,
            "all_records":          all_records,
            "started_at":           started_at,
            "finished_at":          finished_at,
        })

        output_path = os.path.join(workspace, f"run_output_{run_name}.json")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(agent_output.model_dump_json(indent=4))
        print(f"Output validated and saved -> {output_path}")

        if completed_rounds >= max_rounds:
            print(f"\nCompleted {completed_rounds} research rounds. Loop terminated.")
        else:
            print(f"\nReached attempt limit ({max_attempts}) with only "
                  f"{completed_rounds}/{max_rounds} rounds completed.")

        return agent_output


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    """Thin CLI wrapper — parses args, builds HyperparamTuningInput, calls run()."""
    # Import MODEL_REGISTRY here (not at module level) because it depends on
    # ml_models/ being on PYTHONPATH, which is only guaranteed in CLI/pytest contexts.
    from ml_models.models_sandbox import MODEL_REGISTRY

    parser = argparse.ArgumentParser(description="TIDMAD Autonomous Agent Kernel")

    parser.add_argument("--provider", type=str, choices=["gemini", "openai"], default="gemini",
                        help="LLM provider for the planner sub-call (default for reflector when not overridden).")
    parser.add_argument("--model_id", type=str, default="gemini-3.1-flash-lite-preview",
                        help="Model ID for the planner sub-call (default for reflector when not overridden).")
    parser.add_argument("--reflect_provider", type=str, choices=["gemini", "openai"], default=None,
                        help="Optional separate provider for the reflector sub-call. "
                             "When None, the reflector uses --provider.")
    parser.add_argument("--reflect_model_id", type=str, default=None,
                        help="Optional separate model for the reflector sub-call (e.g., gemini-2.5-flash). "
                             "When None, the reflector uses --model_id.")
    parser.add_argument("--expert_advice", type=str, default="None",
                        help="Initial advice from a human expert to guide exploration.")
    parser.add_argument("--max_rounds", type=int, default=10,
                        help="Maximum number of experiment rounds to prevent token drain.")

    model_choices = list(MODEL_REGISTRY.keys()) + ["auto"]
    parser.add_argument("--force_model", type=str, choices=model_choices, default="auto",
                        help="Force a specific architecture or let the agent decide (auto).")

    parser.add_argument("--run_name", type=str, default="test_run",
                        help="Run name for the auto-exploration.")
    parser.add_argument("--workspace", type=str, default="./siderius_workspace",
                        help="Root directory for all agent-generated outputs.")
    parser.add_argument("--progress_bar", action="store_true",
                        help="Stream live tqdm progress bars from training/inference subprocesses.")
    parser.add_argument("--file_index", type=int, default=6,
                        help="Validation/training file index (default: 6). Ignored when --is_trial.")

    # Trial mode arguments
    parser.add_argument("--is_trial", action="store_true",
                        help="Enable trial-explore mode with multi-file sparse sampling.")
    parser.add_argument("--trial_strategy", type=str, default="snapshot",
                        choices=["snapshot", "anchors", "target"],
                        help="Training sampling strategy (default: snapshot).")
    parser.add_argument("--trial_portion", type=float, default=0.1,
                        help="Fraction of segments per file for training scope (default: 0.1).")
    parser.add_argument("--eval_strategy", type=str, default="snapshot",
                        choices=["snapshot", "anchors", "target"],
                        help="Validation sampling strategy (default: snapshot).")
    parser.add_argument("--eval_portion", type=float, default=0.1,
                        help="Fraction of segments per file for validation (default: 0.1).")
    parser.add_argument("--train_portion", type=float, default=0.1,
                        help="Per-epoch subsample from training scope (default: 0.1).")
    parser.add_argument("--human_advice", type=str, default=None,
                        help="Human guidance for the agent (injected alongside expert_advice).")
    parser.add_argument("--cleanup_denoised", action="store_true",
                        help="Delete denoised HDF5 files after scoring each round to save disk space.")

    args = parser.parse_args()

    input_dict = {
        "model_type":      args.force_model,
        "file_index":      args.file_index,
        "max_rounds":      args.max_rounds,
        "expert_advice":   args.expert_advice,
        "llm_provider":    args.provider,
        "llm_model_id":    args.model_id,
        "reflect_provider": args.reflect_provider,
        "reflect_model_id": args.reflect_model_id,
        "storage": {
            "backend": "local",
            "local": {"workspace": args.workspace, "run_name": args.run_name},
        },
        "progress_bar":      args.progress_bar,
        "cleanup_denoised":  args.cleanup_denoised,
        "is_trial":          args.is_trial,
    }
    if args.is_trial:
        input_dict.update({
            "trial_strategy":  args.trial_strategy,
            "trial_portion":   args.trial_portion,
            "eval_strategy":   args.eval_strategy,
            "eval_portion":    args.eval_portion,
            "train_portion":   args.train_portion,
        })
    if args.human_advice:
        input_dict["human_advice"] = args.human_advice

    agent_input = HyperparamTuningInput.model_validate(input_dict)

    agent = HyperparamTuningAgent()
    agent.run(agent_input)


if __name__ == "__main__":
    main()
