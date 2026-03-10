# agent_main.py
import os
import time
import json
import argparse
import importlib
import traceback
from core.sandbox_executor import TidmadSandbox
from agent.llm_bridge import LLMBridge
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
                        help="Root directory for all agent-generated outputs: configs, cached models, and records.")
    parser.add_argument("--progress_bar", action="store_true",
                        help="Stream live tqdm progress bars from training/inference subprocesses.")

    args = parser.parse_args()

    # Initialize "Body" (Sandbox) and "Brain" (LLM Bridge)
    sandbox = TidmadSandbox(metadata_source="local", run_name=args.run_name, workspace=args.workspace,
                            progress_bar=args.progress_bar)
    brain = LLMBridge(provider=args.provider, model_id=args.model_id)

    # Save run configuration once — written at startup, never modified
    run_config = {
        "provider":    args.provider,
        "model_id":    args.model_id,
        "run_name":    args.run_name,
        "force_model": args.force_model,
        "max_rounds":  args.max_rounds,
        "started_at":  time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    run_config_path = os.path.join(args.workspace, f"run_config_{args.run_name}.json")
    with open(run_config_path, "w", encoding="utf-8") as f:
        json.dump(run_config, f, indent=4)

    print(f"=== 🧠 TIDMAD Agent Activated ===")
    print(f"🤖 Provider: {args.provider} | Model: {args.model_id}")
    print(f"👨‍🔬 Expert Advice: {args.expert_advice}")
    print(f"🔢 Max Rounds: {args.max_rounds} | Strategy: {args.force_model}")
    
    # --- 💡 Get the config manual before starting---
    print(f"📖 Reading model configuration manual...")
    config_manual = run_skill("check_config_format_skill", sandbox)
    if config_manual["status"] == "success":
        # pass to brain.plan later
        config_manual_data = config_manual["data"]
    else:
        raise ValueError("Config Manual not provided.")

    # --- 2. Autonomous Research Loop ---
    # Only rounds with a feasible config count toward max_rounds.
    # Infeasible (OOM-risk) attempts are saved to memory but do NOT consume a round slot.
    # A hard cap of max_rounds * 3 total attempts prevents infinite loops.
    completed_rounds = 0
    total_attempts   = 0
    max_attempts     = args.max_rounds * 3

    while completed_rounds < args.max_rounds and total_attempts < max_attempts:
        total_attempts   += 1
        iteration         = completed_rounds + 1   # display number of the *next* round to complete
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
            exp_id = f"{model_type}_{args.run_name}_{total_attempts:03d}"
            hypothesis = decision.get("hypothesis", "N/A")

            print(f"📍 Action: {model_type.upper()} | ID: {exp_id}")
            print(f"💡 Hypothesis: {hypothesis}")
            print(f"📝 Reasoning: {decision.get('reasoning', 'No reasoning provided.')}")

            # C. ACT: Execute the Atomic Skill Pipeline (Train -> Inf -> Score)
            active_params = {
                "exp_id": exp_id,
                "run_name": args.run_name,
                "model_type": model_type,
                "model_config": decision.get("model_config", {}),
                "train_config": decision.get("train_config", {}),
                "loss_config": decision.get("loss_config", {})
            }

            print(f"\n[Step 0/3] Resource check...")
            resource_check = run_skill("evaluate_resource_skill", sandbox, **active_params)
            if resource_check.get("status") == "error":
                raise RuntimeError(f"Resource check error: {resource_check.get('message')}")
            if not resource_check.get("feasible", True):
                print(f"⛔ Resource check FAILED — this attempt does NOT count as a round.")
                print(f"   Verdict   : {resource_check.get('verdict', '')}")
                print(f"   Suggestion: {resource_check.get('suggestion', '')}")
                # Save to memory so the agent learns to propose smaller configs next time
                sandbox.save_record({
                    "exp_id":    exp_id,
                    "status":    "skipped_oom_risk",
                    "model_type": model_type,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "params":    active_params,
                    "results":   {},
                    "denoising_score": None,
                    "memory": {
                        "expert_advice_followed": args.expert_advice,
                        "hypothesis": hypothesis,
                        "conclusion": f"Skipped: estimated VRAM ({resource_check.get('estimated_gb', '?')} GB) exceeds 80% safety limit ({resource_check.get('limit_gb', '?')} GB).",
                        "discovery":  resource_check.get("verdict", ""),
                        "memory_update": resource_check.get("suggestion", "Reduce batch_size or segmentation_size."),
                    },
                })
                continue  # attempt consumed but completed_rounds NOT incremented

            print(f"\n[Step 1/3] Training...")
            train_status = run_skill("training_skill", sandbox, **active_params)
            if train_status.get("status") == "error": continue
            
            print(f"[Step 2/3] Inference...")
            inf_status = run_skill("inference_skill", sandbox, **active_params)
            if inf_status.get("status") == "error": continue
            
            print(f"[Step 3/3] Scoring...")
            score_res = run_skill("denoising_score_skill", sandbox, **active_params)

            # D. REFLECT: Analyze results and generate insights
            print(f"\n🤔 Generating Research Memory...")
            reflection = brain.reflect(exp_id, hypothesis, score_res["results"])
            
            # Console Feedback for Reflection
            print(f"{'-'*30}")
            print(f"📊 RESEARCH REFLECTION for {exp_id}:")
            print(f"📝 Conclusion: {reflection.get('conclusion', 'N/A')}")
            print(f"💡 Discovery: {reflection.get('discovery', 'N/A')}")
            print(f"🧠 Memory Update: {reflection.get('memory_update', 'N/A')}")
            print(f"{'-'*30}")

            # E. COMMIT: Save the finalized multi-modal record
            combined_results = {}
            if "results" in train_status:
                combined_results.update(train_status["results"]) 
            if "results" in score_res:
                combined_results.update(score_res["results"]) 
                
            final_record = {
                "exp_id": exp_id,
                "status": "success", 
                "model_type": model_type,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "params": active_params,
                "results": combined_results,
                "denoising_score": combined_results.get("denoising_score"), 
                "memory": {
                    "expert_advice_followed": args.expert_advice,
                    "hypothesis": hypothesis,
                    "conclusion": reflection.get("conclusion"),
                    "discovery": reflection.get("discovery"),
                    "memory_update": reflection.get("memory_update")
                }
            }
            
            sandbox.save_record(final_record)

            completed_rounds += 1
            print(f"✅ Round {completed_rounds}/{args.max_rounds} Complete. Score: {combined_results.get('denoising_score', 'N/A')}")

            # Cool-down to avoid API rate limits
            time.sleep(2)

        except Exception as e:
            print(f"🚨 Loop Error: {e}")
            traceback.print_exc()
            time.sleep(5)

    if completed_rounds >= args.max_rounds:
        print(f"\n🏁 Completed {completed_rounds} research rounds. Loop terminated.")
    else:
        print(f"\n⚠️  Reached attempt limit ({max_attempts}) with only {completed_rounds}/{args.max_rounds} rounds completed.")

if __name__ == "__main__":
    main()