# ml_hyperparameter_tune_agent.py
import os
import time
import json
import argparse
import importlib
import traceback
from core.sandbox_executor import TidmadSandbox
from agent.llm_bridge import LLMBridge
from agent.schemas.hyperparam_tuning import (
    HyperparamTuningInput,
    HyperparamTuningOutput,
    ExperimentRecord,
)
from models_sandbox import MODEL_REGISTRY


def run_skill(skill_folder, sandbox, **params):
    """
    Dynamically loads and executes a research skill (Training, Inference, or Scoring).
    """
    module_path = f"agent.skills.{skill_folder}.wrapper"
    try:
        skill_module = importlib.import_module(module_path)
        return skill_module.run_skill(sandbox, **params)
    except Exception as e:
        print(f"🚨 Skill Error [{skill_folder}]: {str(e)}")
        return {"status": "error", "message": str(e)}


def main():
    # --- 1. Input Argument Handling ---
    parser = argparse.ArgumentParser(description="TIDMAD Autonomous Agent Kernel")

    # LLM Configuration
    parser.add_argument("--provider", type=str, choices=["gemini", "openai"], default="gemini",
                        help="LLM provider for the decision brain.")
    parser.add_argument("--model_id", type=str, default="gemini-3.1-flash-lite-preview",
                        help="Specific model ID (e.g., gemini-3.1-flash-lite-preview, gpt-4o).")

    # Research Guidance & Constraints
    parser.add_argument("--expert_advice", type=str, default="None",
                        help="Initial advice from a human expert to guide exploration.")
    parser.add_argument("--max_rounds", type=int, default=10,
                        help="Maximum number of experiment rounds to prevent token drain.")

    model_choices = list(MODEL_REGISTRY.keys()) + ["auto"]

    parser.add_argument("--force_model", type=str, choices=model_choices, default="auto",
                        help="Force a specific architecture or let the agent decide (auto).")

    # Project Name
    parser.add_argument("--run_name", type=str, default="test_run",
                        help="Run name for the auto-exploration.")

    # Storage
    parser.add_argument("--workspace", type=str, default="./siderius_workspace",
                        help="Root directory for all agent-generated outputs.")
    parser.add_argument("--progress_bar", action="store_true",
                        help="Stream live tqdm progress bars from training/inference subprocesses.")
    parser.add_argument("--file_index", type=int, default=6,
                        help="Validation/training file index (default: 6).")

    args = parser.parse_args()

    # --- 2. Explicit input validation against schema ---
    # Fails fast with a clear Pydantic error if any argument is out of range or invalid.
    agent_input = HyperparamTuningInput.model_validate({
        "model_type":   args.force_model,
        "file_index":   args.file_index,
        "max_rounds":   args.max_rounds,
        "expert_advice": args.expert_advice,
        "llm_provider": args.provider,
        "llm_model_id": args.model_id,
        "storage": {
            "backend": "local",
            "local": {"workspace": args.workspace, "run_name": args.run_name},
        },
        "progress_bar": args.progress_bar,
    })
    workspace = agent_input.storage.local.workspace
    run_name  = agent_input.storage.local.run_name
    print(f"✅ Input validated: model={agent_input.model_type} | rounds={agent_input.max_rounds} "
          f"| file_index={agent_input.file_index} | provider={agent_input.llm_provider}")

    # --- 3. Initialize sandbox and brain ---
    sandbox = TidmadSandbox(
        metadata_source="local",
        run_name=run_name,
        workspace=workspace,
        progress_bar=args.progress_bar,
        file_index=args.file_index,
    )
    brain = LLMBridge(provider=args.provider, model_id=args.model_id)

    # Save run configuration once — written at startup, never modified
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    run_config = {
        "provider":    args.provider,
        "model_id":    args.model_id,
        "run_name":    args.run_name,
        "force_model": args.force_model,
        "max_rounds":  args.max_rounds,
        "file_index":  args.file_index,
        "started_at":  started_at,
    }
    run_config_path = os.path.join(workspace, f"run_config_{run_name}.json")
    with open(run_config_path, "w", encoding="utf-8") as f:
        json.dump(run_config, f, indent=4)

    print(f"=== 🧠 TIDMAD Agent Activated ===")
    print(f"🤖 Provider: {args.provider} | Model: {args.model_id}")
    print(f"👨‍🔬 Expert Advice: {args.expert_advice}")
    print(f"🔢 Max Rounds: {args.max_rounds} | Strategy: {args.force_model}")

    # --- 💡 Get the config manual before starting ---
    print(f"📖 Reading model configuration manual...")
    config_manual = run_skill("check_config_format_skill", sandbox)
    if config_manual["status"] == "success":
        config_manual_data = config_manual["data"]
    else:
        raise ValueError("Config Manual not provided.")

    # --- 4. Autonomous Research Loop ---
    # Only rounds with a feasible config count toward max_rounds.
    # Infeasible (OOM-risk) attempts are saved to memory but do NOT consume a round slot.
    # A hard cap of max_rounds * 3 total attempts prevents infinite loops.
    completed_rounds = 0
    total_attempts   = 0
    max_attempts     = args.max_rounds * 3

    while completed_rounds < args.max_rounds and total_attempts < max_attempts:
        total_attempts += 1
        iteration       = completed_rounds + 1
        try:
            print(f"\n\n{'='*60}\n🔄 ROUND {iteration}/{args.max_rounds} (attempt {total_attempts}): Planning...\n{'='*60}")

            # A. OBSERVE: Retrieve full Research Memory from summary.json
            memory_history = sandbox.get_summary()

            # B. THINK: Plan next experiment with expert context and constraints
            decision = brain.plan(
                memory_history,
                expert_advice=args.expert_advice,
                force_model=args.force_model,
                config_manual=config_manual_data,
            )

            model_type = decision.get("model_type", "fcnet")
            exp_id     = f"{model_type}_{args.run_name}_{total_attempts:03d}"
            hypothesis = decision.get("hypothesis", "N/A")

            print(f"📍 Action: {model_type.upper()} | ID: {exp_id}")
            print(f"💡 Hypothesis: {hypothesis}")
            print(f"📝 Reasoning: {decision.get('reasoning', 'No reasoning provided.')}")

            # C. ACT: Execute the Atomic Skill Pipeline (Train -> Inf -> Score)
            active_params = {
                "exp_id":        exp_id,
                "run_name":      args.run_name,
                "model_type":    model_type,
                "model_config":  decision.get("model_config", {}),
                "train_config":  decision.get("train_config", {}),
                "loss_config":   decision.get("loss_config", {}),
            }

            print(f"\n[Step 0/3] Resource check...")
            resource_check = run_skill("evaluate_resource_skill", sandbox, **active_params)
            if resource_check.get("status") == "error":
                raise RuntimeError(f"Resource check error: {resource_check.get('message')}")

            if not resource_check.get("feasible", True):
                print(f"⛔ Resource check FAILED — this attempt does NOT count as a round.")
                print(f"   Verdict   : {resource_check.get('verdict', '')}")
                print(f"   Suggestion: {resource_check.get('suggestion', '')}")

                oom_record = {
                    "exp_id":          exp_id,
                    "status":          "skipped_oom_risk",
                    "model_type":      model_type,
                    "timestamp":       time.strftime("%Y-%m-%d %H:%M:%S"),
                    "file_index":      args.file_index,
                    "params":          active_params,
                    "results":         {},
                    "denoising_score": None,
                    "memory": {
                        "expert_advice_followed": args.expert_advice,
                        "hypothesis":    hypothesis,
                        "conclusion":    (
                            f"Skipped: estimated VRAM ({resource_check.get('estimated_gb', '?')} GB) "
                            f"exceeds 80% safety limit ({resource_check.get('limit_gb', '?')} GB)."
                        ),
                        "discovery":     resource_check.get("verdict", ""),
                        "memory_update": resource_check.get("suggestion", "Reduce batch_size or segmentation_size."),
                    },
                }
                # Explicit validation before saving
                ExperimentRecord.model_validate(oom_record)
                sandbox.save_record(oom_record)
                continue  # attempt consumed but completed_rounds NOT incremented

            print(f"\n[Step 1/3] Training...")
            t0 = time.time()
            train_status = run_skill("training_skill", sandbox, **active_params)
            train_time = round(time.time() - t0, 1)
            if train_status.get("status") == "error":
                continue

            print(f"[Step 2/3] Inference...")
            t0 = time.time()
            inf_status = run_skill("inference_skill", sandbox, **active_params)
            inference_time = round(time.time() - t0, 1)
            if inf_status.get("status") == "error":
                continue

            print(f"[Step 3/3] Scoring...")
            t0 = time.time()
            score_res = run_skill("denoising_score_skill", sandbox, **active_params)
            scoring_time = round(time.time() - t0, 1)

            # D. REFLECT: Analyze results and generate insights
            print(f"\n🤔 Generating Research Memory...")

            current_score     = score_res["results"].get("denoising_score")
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
                r["results"]["final_loss"]
                for r in successful
                if r.get("params", {}).get("loss_config", {}).get("loss_type") == current_loss_type
                and r.get("results", {}).get("final_loss") is not None
            ]
            current_final_loss = score_res["results"].get("final_loss")
            if current_final_loss is not None:
                all_same_loss_finals  = same_loss_finals + [current_final_loss]
                sorted_finals         = sorted(all_same_loss_finals)
                same_loss_loss_rank   = sorted_finals.index(current_final_loss) + 1
                same_loss_total       = len(all_same_loss_finals)
            else:
                same_loss_loss_rank = None
                same_loss_total     = len(same_loss_finals)

            current_params  = score_res["results"].get("model_params")
            current_epochs  = active_params["train_config"].get("epochs")
            baseline_params = baseline_record.get("results", {}).get("model_params") if baseline_record else None
            baseline_epochs = baseline_record.get("params", {}).get("train_config", {}).get("epochs") if baseline_record else None
            params_ratio    = round(current_params / baseline_params, 3) if (current_params and baseline_params) else None
            epochs_ratio    = round(current_epochs / baseline_epochs, 3) if (current_epochs and baseline_epochs) else None

            worst_score     = min(all_scores) if all_scores else None
            score_range     = (best_score - worst_score) if (best_score is not None and worst_score is not None and best_score != worst_score) else None
            score_threshold = (best_score - 0.05 * score_range) if score_range is not None else best_score
            best_params     = best_record.get("results", {}).get("model_params") if best_record else None
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
            }

            reflection = brain.reflect(exp_id, hypothesis, score_res["results"], reflection_context)

            print(f"{'-'*30}")
            print(f"📊 RESEARCH REFLECTION for {exp_id}:")
            print(f"📝 Conclusion  : {reflection.get('conclusion', 'N/A')}")
            print(f"🔑 Key Factor  : {reflection.get('key_factor', 'N/A')}")
            print(f"💡 Discovery   : {reflection.get('discovery', 'N/A')}")
            print(f"🧠 Memory Update: {reflection.get('memory_update', 'N/A')}")
            print(f"{'-'*30}")

            # E. COMMIT: Build, validate, and save the finalized record
            combined_results = {}
            if "results" in train_status:
                combined_results.update(train_status["results"])
            if "results" in score_res:
                combined_results.update(score_res["results"])

            final_record = {
                "exp_id":     exp_id,
                "status":     "success",
                "model_type": model_type,
                "timestamp":  time.strftime("%Y-%m-%d %H:%M:%S"),
                "file_index": args.file_index,
                "params":     active_params,
                "results":    combined_results,
                "denoising_score": combined_results.get("denoising_score"),
                "timing": {
                    "train_time_s":     train_time,
                    "inference_time_s": inference_time,
                    "scoring_time_s":   scoring_time,
                },
                "memory": {
                    "expert_advice_followed": args.expert_advice,
                    "hypothesis":    hypothesis,
                    "conclusion":    reflection.get("conclusion"),
                    "key_factor":    reflection.get("key_factor"),
                    "discovery":     reflection.get("discovery"),
                    "memory_update": reflection.get("memory_update"),
                },
            }

            # Explicit validation before saving — raises immediately if schema is violated
            ExperimentRecord.model_validate(final_record)
            sandbox.save_record(final_record)

            completed_rounds += 1
            print(f"✅ Round {completed_rounds}/{args.max_rounds} Complete. Score: {combined_results.get('denoising_score', 'N/A')}")

            time.sleep(2)  # Cool-down to avoid API rate limits

        except Exception as e:
            print(f"🚨 Loop Error: {e}")
            traceback.print_exc()
            time.sleep(5)

    # --- 5. Build, validate, and save the run output ---
    finished_at  = time.strftime("%Y-%m-%d %H:%M:%S")
    run_status   = "completed" if completed_rounds >= args.max_rounds else "partial"
    all_records  = sandbox.get_summary()
    successful_records = [
        r for r in all_records
        if r.get("status") == "success" and r.get("denoising_score") is not None
    ]
    top_record = max(successful_records, key=lambda r: r["denoising_score"]) if successful_records else None

    agent_output = HyperparamTuningOutput.model_validate({
        "run_name":            run_name,
        "model_type":          args.force_model,
        "file_index":          args.file_index,
        "status":              run_status,
        "completed_rounds":    completed_rounds,
        "total_attempts":      total_attempts,
        "best_exp_id":         top_record.get("exp_id") if top_record else None,
        "best_denoising_score": top_record.get("denoising_score") if top_record else None,
        "best_config":         top_record.get("params") if top_record else None,
        "all_records":         all_records,
        "started_at":          started_at,
        "finished_at":         finished_at,
    })

    output_path = os.path.join(workspace, f"run_output_{run_name}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(agent_output.model_dump_json(indent=4))
    print(f"✅ Output validated and saved → {output_path}")

    if completed_rounds >= args.max_rounds:
        print(f"\n🏁 Completed {completed_rounds} research rounds. Loop terminated.")
    else:
        print(f"\n⚠️  Reached attempt limit ({max_attempts}) with only {completed_rounds}/{args.max_rounds} rounds completed.")


if __name__ == "__main__":
    main()
