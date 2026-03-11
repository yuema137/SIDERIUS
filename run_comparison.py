#!/usr/bin/env python3
"""
run_comparison.py — Compare baseline vs agent-assisted exploration for a given TIDMAD model.

Phases:
  1. Baseline: Train/infer/score using exact legacy configs from the TIDMAD paper.
               Computed ONCE per model and reused across all run_names — auto-skipped
               if already present.
  2. Seed:     Pre-populate the agent's summary.json with the baseline result so the
               agent knows what benchmark it must beat from round 1.
  3. Agent:    Launch agent_main.py for --max_rounds exploration rounds, locked to
               the same model type but free to vary config, loss, and train hparams.

Output structure:
  /home/klz/Data/SIDEREIS_DATA/
  └── {model}/
      ├── baseline/          ← shared baseline workspace (computed once)
      └── {run_name}/
          └── agent/         ← isolated agent workspace per run_name

Usage:
  python run_comparison.py --model punet
  python run_comparison.py --model punet --run_name v2 --max_rounds 50
  python run_comparison.py --model rnn --provider openai --model_id gpt-4o
"""

import os
import sys
import json
import time
import glob
import argparse
import subprocess

# Ensure SIDERIUS root is importable regardless of where script is invoked from
SIDERIUS_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SIDERIUS_ROOT)

from core.sandbox_executor import TidmadSandbox

ROOT_DATA_DIR = "/home/klz/Data/SIDEREIS_DATA"
LEGACY_CONFIGS_PATH = os.path.join(SIDERIUS_ROOT, "model_tools", "legacy_baseline_configs.json")


def _agent_env() -> dict:
    """
    Build a subprocess environment with all SIDERIUS paths on PYTHONPATH
    so that flat imports in agent_main.py, train_engine_sandbox.py, etc. resolve.
    """
    extra = [
        SIDERIUS_ROOT,
        os.path.join(SIDERIUS_ROOT, "model_tools"),
        os.path.join(SIDERIUS_ROOT, "execute_tools"),
    ]
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(extra + ([existing] if existing else []))
    return env


# ==========================================
# Phase 1: Baseline
# ==========================================

def run_baseline(model_type: str, baseline_workspace: str, progress_bar: bool = False) -> dict:
    """
    Runs the full pipeline (train -> inference -> score) with the exact legacy config
    from the TIDMAD paper. Returns the final record dict.
    """
    with open(LEGACY_CONFIGS_PATH, "r") as f:
        legacy = json.load(f)

    if model_type not in legacy:
        raise ValueError(f"No legacy config found for model '{model_type}' in {LEGACY_CONFIGS_PATH}")

    cfg = legacy[model_type]
    m_cfg = cfg["model_cfg"]
    t_cfg = cfg["train_cfg"]
    l_cfg = cfg["loss_cfg"]

    run_name = f"baseline_{model_type}"
    exp_id   = f"baseline_{model_type}_{int(time.time())}"

    sandbox = TidmadSandbox(
        metadata_source="local",
        run_name=run_name,
        workspace=baseline_workspace,
        progress_bar=progress_bar,
    )

    print(f"\n{'='*60}")
    print(f"  PHASE 1 — BASELINE: {model_type.upper()}")
    print(f"{'='*60}")
    print(f"  model_cfg  : {m_cfg}")
    print(f"  train_cfg  : {t_cfg}")
    print(f"  loss_cfg   : {l_cfg}")
    print()

    # --- Train ---
    t0 = time.time()
    train_result = sandbox.execute_training(
        exp_id=exp_id, run_name=run_name, model_type=model_type,
        m_cfg=m_cfg, t_cfg=t_cfg, l_cfg=l_cfg,
    )
    train_time = round(time.time() - t0, 1)
    if train_result["status"] != "success":
        raise RuntimeError(f"Baseline training failed:\n{train_result.get('message')}")

    # --- Inference ---
    t0 = time.time()
    inf_result = sandbox.execute_inference(
        exp_id=exp_id, run_name=run_name, model_type=model_type,
        m_cfg=m_cfg, l_cfg=l_cfg,
    )
    inference_time = round(time.time() - t0, 1)
    if inf_result["status"] != "success":
        raise RuntimeError(f"Baseline inference failed:\n{inf_result.get('message')}")

    # --- Score ---
    t0 = time.time()
    score_result = sandbox.execute_scoring(
        exp_id=exp_id, run_name=run_name, model_type=model_type,
        m_cfg=m_cfg, t_cfg=t_cfg, l_cfg=l_cfg,
    )
    scoring_time = round(time.time() - t0, 1)
    if score_result["status"] != "success":
        raise RuntimeError(f"Baseline scoring failed:\n{score_result.get('message')}")

    # Merge train + score results
    combined = {}
    if "results" in train_result:
        combined.update(train_result["results"])
    if "results" in score_result:
        combined.update(score_result["results"])

    record = {
        "exp_id":       exp_id,
        "status":       "success",
        "model_type":   model_type,
        "timestamp":    time.strftime("%Y-%m-%d %H:%M:%S"),
        "params": {
            "exp_id":        exp_id,
            "run_name":      run_name,
            "model_type":    model_type,
            "model_config":  m_cfg,
            "train_config":  t_cfg,
            "loss_config":   l_cfg,
        },
        "results":        combined,
        "denoising_score": combined.get("denoising_score"),
        "timing": {
            "train_time_s":     train_time,
            "inference_time_s": inference_time,
            "scoring_time_s":   scoring_time,
        },
        "memory": {
            "expert_advice_followed": "Legacy TIDMAD paper baseline — no agent involvement.",
            "hypothesis": "Original hardcoded baseline configuration from the TIDMAD paper.",
            "conclusion": (
                f"Baseline {model_type.upper()} achieved "
                f"denoising_score={combined.get('denoising_score', 'N/A')}."
            ),
            "discovery": (
                "This is the paper's reference result. All subsequent agent experiments "
                "should aim to surpass this benchmark."
            ),
            "memory_update": (
                f"Baseline {model_type.upper()} performance established. "
                f"Score: {combined.get('denoising_score', 'N/A')}. "
                "Use this as the minimum target for improvement."
            ),
        },
    }

    sandbox.save_record(record)
    print(f"\n  Baseline complete. Denoising score: {combined.get('denoising_score', 'N/A')}")
    return record


# ==========================================
# Phase 2: Seed agent memory
# ==========================================

def seed_agent_memory(baseline_record: dict, agent_workspace: str, agent_run_name: str):
    """
    Writes the baseline record into the agent's summary_{run_name}.json so that
    on round 1 the agent immediately sees the benchmark it must beat.
    """
    os.makedirs(agent_workspace, exist_ok=True)
    summary_path = os.path.join(agent_workspace, f"summary_{agent_run_name}.json")

    # If the agent has already run some rounds, prepend baseline only if not present
    existing = []
    if os.path.exists(summary_path):
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, IOError):
            existing = []

    already_seeded = any(r.get("exp_id") == baseline_record.get("exp_id") for r in existing)
    if not already_seeded:
        existing.insert(0, baseline_record)
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=4, ensure_ascii=False)
        print(f"\n  Agent memory seeded with baseline record → {summary_path}")
    else:
        print(f"\n  Agent memory already contains baseline record — skipping seed.")


# ==========================================
# Phase 3: Agent exploration
# ==========================================

def run_agent(model_type: str, agent_workspace: str, agent_run_name: str,
              provider: str, model_id: str, max_rounds: int, progress_bar: bool = False):
    """
    Launches agent_main.py as a subprocess, locked to model_type, for max_rounds rounds.
    """
    expert_advice = (
        "You should actively try different model configs, loss types and train configs, "
        "while not exceeding the limit of GPU memory. "
        "The baseline result is already in your memory — "
        "your goal is to find configurations that outperform it."
    )

    cmd = [
        sys.executable,
        os.path.join(SIDERIUS_ROOT, "agent_main.py"),
        "--provider",    provider,
        "--model_id",    model_id,
        "--force_model", model_type,
        "--max_rounds",  str(max_rounds),
        "--run_name",    agent_run_name,
        "--workspace",   agent_workspace,
        "--expert_advice", expert_advice,
    ]
    if progress_bar:
        cmd.append("--progress_bar")

    print(f"\n{'='*60}")
    print(f"  PHASE 3 — AGENT EXPLORATION: {model_type.upper()}")
    print(f"  Rounds:    {max_rounds}")
    print(f"  Workspace: {agent_workspace}")
    print(f"  Provider:  {provider} / {model_id}")
    print(f"{'='*60}\n")

    subprocess.run(cmd, cwd=SIDERIUS_ROOT, env=_agent_env(), check=True)


# ==========================================
# Entry point
# ==========================================

def main():
    parser = argparse.ArgumentParser(
        description="SIDERIUS: Compare baseline vs agent-assisted exploration for a TIDMAD model."
    )
    parser.add_argument(
        "--model", type=str, required=True,
        choices=["punet", "fcnet", "transformer", "wavenet", "rnn"],
        help="Model architecture to explore.",
    )
    parser.add_argument(
        "--provider", type=str, default="gemini", choices=["gemini", "openai"],
        help="LLM provider for the agent (default: gemini).",
    )
    parser.add_argument(
        "--model_id", type=str, default="gemini-3.1-flash-lite-preview",
        help="LLM model ID (default: gemini-3.1-flash-lite-preview).",
    )
    parser.add_argument(
        "--max_rounds", type=int, default=50,
        help="Number of agent exploration rounds (default: 50).",
    )
    parser.add_argument(
        "--progress_bar", action="store_true",
        help="Stream live tqdm progress bars from training/inference/scoring subprocesses.",
    )
    parser.add_argument(
        "--run_name", type=str, default="v1",
        help=(
            "Name for this comparison run (default: v1). "
            "Use different names (e.g. 'test', 'v1', 'v2') to keep runs isolated. "
            "Agent results go to {ROOT_DATA_DIR}/{model}/{run_name}/agent/. "
            "Baseline is shared at {ROOT_DATA_DIR}/{model}/baseline/."
        ),
    )
    parser.add_argument(
        "--override_old_run", action="store_true",
        help=(
            "Delete any existing data for --run_name and start fresh. "
            "Without this flag the script will error if the run_name already exists."
        ),
    )
    args = parser.parse_args()

    model_type         = args.model
    model_root         = os.path.join(ROOT_DATA_DIR, model_type)
    run_dir            = os.path.join(model_root, args.run_name)
    baseline_workspace = os.path.join(model_root, "baseline")       # shared across all runs
    agent_workspace    = os.path.join(run_dir, "agent")
    agent_run_name     = f"{args.run_name}_agent"

    # --- Guard: prevent accidental overwrite of existing run ---
    if os.path.exists(run_dir) and os.listdir(run_dir):
        if not args.override_old_run:
            raise SystemExit(
                f"\n[ERROR] Run '{args.run_name}' already exists at:\n"
                f"  {run_dir}\n\n"
                f"Options:\n"
                f"  1. Use a different run name:\n"
                f"       --run_name <new_name>\n\n"
                f"  2. Manually delete the existing run and restart:\n"
                f"       rm -rf {run_dir}\n\n"
                f"  3. Let the script delete it automatically:\n"
                f"       --override_old_run"
            )
        else:
            import shutil
            shutil.rmtree(run_dir)
            print(f"  [override] Deleted existing run at: {run_dir}")

    os.makedirs(baseline_workspace, exist_ok=True)
    os.makedirs(agent_workspace, exist_ok=True)

    print(f"\n{'#'*60}")
    print(f"  SIDERIUS Comparison Run — {model_type.upper()}")
    print(f"  Baseline  : {baseline_workspace}")
    print(f"  Agent     : {agent_workspace}")
    print(f"  Rounds    : {args.max_rounds}")
    print(f"{'#'*60}")

    # --- Phase 1: Baseline (computed once, reused across all run_names) ---
    matches = glob.glob(os.path.join(baseline_workspace, "summary_*.json"))
    baseline_done = False
    if matches:
        try:
            with open(matches[0], "r") as f:
                history = json.load(f)
            if history:
                baseline_record = history[0]
                baseline_done = True
                print(f"\n  Baseline already computed: {baseline_record.get('exp_id')} "
                      f"(score={baseline_record.get('denoising_score', 'N/A')}) — skipping.")
        except (json.JSONDecodeError, IOError):
            pass

    if not baseline_done:
        baseline_record = run_baseline(model_type, baseline_workspace, progress_bar=args.progress_bar)

    # --- Phase 2: Seed agent memory ---
    seed_agent_memory(baseline_record, agent_workspace, agent_run_name)

    # --- Phase 3: Agent exploration ---
    run_agent(
        model_type=model_type,
        agent_workspace=agent_workspace,
        agent_run_name=agent_run_name,
        provider=args.provider,
        model_id=args.model_id,
        max_rounds=args.max_rounds,
        progress_bar=args.progress_bar,
    )

    print(f"\n{'#'*60}")
    print(f"  Comparison run complete for {model_type.upper()}")
    print(f"  Baseline results : {baseline_workspace}")
    print(f"  Agent results    : {agent_workspace}")
    print(f"{'#'*60}\n")


if __name__ == "__main__":
    main()
