#!/usr/bin/env python3
"""
run_comparison.py — Compare baseline vs agent-assisted exploration for a given TIDMAD model.

Phases:
  1. Baseline: Train/infer/score using exact legacy configs from the TIDMAD paper.
               Computed ONCE per model and reused across all run_names — auto-skipped
               if already present.
  2. Seed:     Pre-populate the agent's summary.json with the baseline result so the
               agent knows what benchmark it must beat from round 1.
  3. Agent:    Launch nodes/ml_hyperparameter_tune_agent.py for --max_rounds exploration rounds, locked to
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

import argparse
import glob
import json
import os
import subprocess
import sys
import time

# Ensure SIDERIUS root is importable regardless of where script is invoked from
SIDERIUS_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SIDERIUS_ROOT)

from datetime import UTC

from core.sandbox_executor import TidmadSandbox
from execute_tools.build_anchor_map import load_anchor_map
from execute_tools.data_paths import SIDERIUS_DATA_DIR, TIDMAD_DATA_DIR
from execute_tools.sample_set_builder import build_sample_set
from execute_tools.scoring_utils import score_vector

ROOT_DATA_DIR = SIDERIUS_DATA_DIR
DATA_DIR = TIDMAD_DATA_DIR
LEGACY_CONFIGS_PATH = os.path.join(SIDERIUS_ROOT, "ml_models", "legacy_baseline_configs.json")


def _agent_env() -> dict:
    """
    Build a subprocess environment with all SIDERIUS paths on PYTHONPATH
    so that flat imports in nodes/ml_hyperparameter_tune_agent.py, train_engine_sandbox.py, etc. resolve.
    """
    extra = [
        SIDERIUS_ROOT,
        os.path.join(SIDERIUS_ROOT, "ml_models"),
        os.path.join(SIDERIUS_ROOT, "execute_tools"),
    ]
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(extra + ([existing] if existing else []))
    return env


# ==========================================
# Phase 1: Baseline
# ==========================================


def run_baseline(
    model_type: str, baseline_workspace: str, progress_bar: bool = False, file_index: int = 6
) -> dict:
    """
    Runs the full pipeline (train -> inference -> score) with the exact legacy config
    from the TIDMAD paper. Returns the final record dict.
    """
    with open(LEGACY_CONFIGS_PATH) as f:
        legacy = json.load(f)

    if model_type not in legacy:
        raise ValueError(
            f"No legacy config found for model '{model_type}' in {LEGACY_CONFIGS_PATH}"
        )

    cfg = legacy[model_type]
    m_cfg = cfg["model_cfg"]
    t_cfg = cfg["train_cfg"]
    l_cfg = cfg["loss_cfg"]

    run_name = f"baseline_{model_type}"
    exp_id = f"baseline_{model_type}_{int(time.time())}"

    sandbox = TidmadSandbox(
        metadata_source="local",
        run_name=run_name,
        workspace=baseline_workspace,
        progress_bar=progress_bar,
        file_index=file_index,
    )

    print(f"\n{'=' * 60}")
    print(f"  PHASE 1 — BASELINE: {model_type.upper()}")
    print(f"{'=' * 60}")
    print(f"  model_cfg  : {m_cfg}")
    print(f"  train_cfg  : {t_cfg}")
    print(f"  loss_cfg   : {l_cfg}")
    print()

    # --- Train ---
    t0 = time.time()
    train_result = sandbox.execute_training(
        exp_id=exp_id,
        run_name=run_name,
        model_type=model_type,
        m_cfg=m_cfg,
        t_cfg=t_cfg,
        l_cfg=l_cfg,
    )
    train_time = round(time.time() - t0, 1)
    if train_result["status"] != "success":
        raise RuntimeError(f"Baseline training failed:\n{train_result.get('message')}")

    # --- Inference ---
    t0 = time.time()
    inf_result = sandbox.execute_inference(
        exp_id=exp_id,
        run_name=run_name,
        model_type=model_type,
        m_cfg=m_cfg,
        l_cfg=l_cfg,
    )
    inference_time = round(time.time() - t0, 1)
    if inf_result["status"] != "success":
        raise RuntimeError(f"Baseline inference failed:\n{inf_result.get('message')}")

    # --- Score ---
    t0 = time.time()
    score_result = sandbox.execute_scoring(
        exp_id=exp_id,
        run_name=run_name,
        model_type=model_type,
        m_cfg=m_cfg,
        t_cfg=t_cfg,
        l_cfg=l_cfg,
    )
    scoring_time = round(time.time() - t0, 1)
    if score_result["status"] != "success":
        raise RuntimeError(f"Baseline scoring failed:\n{score_result.get('message')}")

    # Extract results from each stage
    train_res = train_result.get("results", {})
    score_res = score_result.get("results", {})

    record = {
        "exp_id": exp_id,
        "status": "success",
        "model_type": model_type,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "file_index": file_index,
        "params": {
            "exp_id": exp_id,
            "run_name": run_name,
            "model_type": model_type,
            "model_config": m_cfg,
            "train_config": t_cfg,
            "loss_config": l_cfg,
        },
        "final_loss": train_res.get("final_loss"),
        "loss_history": train_res.get("loss_history"),
        "model_params": train_res.get("model_params"),
        "denoising_score": score_res.get("denoising_score"),
        "timing": {
            "train_time_s": train_time,
            "inference_time_s": inference_time,
            "scoring_time_s": scoring_time,
        },
        "memory": {
            "expert_advice_followed": "Legacy TIDMAD paper baseline — no agent involvement.",
            "hypothesis": "Original hardcoded baseline configuration from the TIDMAD paper.",
            "conclusion": (
                f"Baseline {model_type.upper()} achieved "
                f"denoising_score={score_res.get('denoising_score', 'N/A')}."
            ),
            "discovery": (
                "This is the paper's reference result. All subsequent agent experiments "
                "should aim to surpass this benchmark."
            ),
            "memory_update": (
                f"Baseline {model_type.upper()} performance established. "
                f"Score: {score_res.get('denoising_score', 'N/A')}. "
                "Use this as the minimum target for improvement."
            ),
        },
    }

    sandbox.save_record(record)
    print(f"\n  Baseline complete. Denoising score: {score_res.get('denoising_score', 'N/A')}")
    return record


def run_baseline_trial(
    model_type: str, baseline_workspace: str, progress_bar: bool = False
) -> dict:
    """
    Runs baseline with the TIDMAD paper config using the trial pipeline:
    - Training: all 20 files, train_portion=0.1 (subsampled per epoch),
      streamed via run_experiment_streaming
    - Inference: all 20 files, all segments
    - Scoring: anchor-normalized score_vector (parallel)

    No LLM call — config is hardcoded from legacy_baseline_configs.json.
    Produces scores on the same anchor-normalized scale as agent trial/formal runs.
    """
    with open(LEGACY_CONFIGS_PATH) as f:
        legacy = json.load(f)

    if model_type not in legacy:
        raise ValueError(
            f"No legacy config found for model '{model_type}' in {LEGACY_CONFIGS_PATH}"
        )

    cfg = legacy[model_type]
    m_cfg = cfg["model_cfg"]
    t_cfg = cfg["train_cfg"]
    l_cfg = cfg["loss_cfg"]

    run_name = f"baseline_{model_type}"
    exp_id = f"baseline_{model_type}_{int(time.time())}"

    # Override epochs to match paper (10 epochs with 10% subsampling ≈ paper's training)
    t_cfg = dict(t_cfg)
    t_cfg["epochs"] = 10

    sandbox = TidmadSandbox(
        metadata_source="local",
        run_name=run_name,
        workspace=baseline_workspace,
        progress_bar=progress_bar,
        file_index=6,  # unused in trial mode but required by TidmadSandbox
    )

    print(f"\n{'=' * 60}")
    print(f"  PHASE 1 — BASELINE (trial pipeline): {model_type.upper()}")
    print(f"{'=' * 60}")
    print(f"  model_cfg   : {m_cfg}")
    print(f"  train_cfg   : {t_cfg}")
    print(f"  loss_cfg    : {l_cfg}")
    print("  train scope : all 20 files, portion=1.0, train_portion=0.1/epoch")
    print("  eval scope  : all 20 files, all segments")
    print()

    # Build SampleSets — full coverage, deterministic seed
    train_sample_set = build_sample_set(
        is_trial=True,
        trial_strategy="snapshot",
        trial_portion=1.0,
        seed=0,
    )
    eval_sample_set = build_sample_set(
        is_trial=True,
        trial_strategy="snapshot",
        trial_portion=1.0,
        seed=0,
    )

    # --- Train (streaming, all 20 files, 10% subsample/epoch) ---
    t0 = time.time()
    train_result = sandbox.execute_training(
        exp_id=exp_id,
        run_name=run_name,
        model_type=model_type,
        m_cfg=m_cfg,
        t_cfg=t_cfg,
        l_cfg=l_cfg,
        sample_set=train_sample_set,
        train_portion=0.1,
        train_base_seed=42,
    )
    train_time = round(time.time() - t0, 1)
    if train_result["status"] != "success":
        raise RuntimeError(f"Baseline training failed:\n{train_result.get('message')}")

    # --- Inference (all 20 files, all segments) ---
    t0 = time.time()
    inf_result = sandbox.execute_inference(
        exp_id=exp_id,
        run_name=run_name,
        model_type=model_type,
        m_cfg=m_cfg,
        l_cfg=l_cfg,
        sample_set=eval_sample_set,
    )
    inference_time = round(time.time() - t0, 1)
    if inf_result["status"] != "success":
        raise RuntimeError(f"Baseline inference failed:\n{inf_result.get('message')}")

    # --- Score (anchor-normalized, parallel) ---
    t0 = time.time()
    anchor_map_path = os.path.join(DATA_DIR, "segment_anchors.json")
    anchor_data = load_anchor_map(anchor_map_path)

    def _denoised_fn(fi):
        return f"abra_validation_denoised_{model_type}_{run_name}_{exp_id}_{fi:04d}.h5"

    file_vector, final_scalar, _, _ = score_vector(
        data_dir=baseline_workspace,
        sample_set=eval_sample_set,
        anchor_map=anchor_data["anchors"],
        s_max=anchor_data["s_max"],
        denoised_filename_fn=_denoised_fn,
        raw_data_dir=DATA_DIR,
    )
    scoring_time = round(time.time() - t0, 1)

    # Extract training results
    train_res = train_result.get("results", {})

    record = {
        "exp_id": exp_id,
        "status": "success",
        "model_type": model_type,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "file_index": 6,
        "params": {
            "exp_id": exp_id,
            "run_name": run_name,
            "model_type": model_type,
            "model_config": m_cfg,
            "train_config": t_cfg,
            "loss_config": l_cfg,
        },
        "final_loss": train_res.get("final_loss"),
        "loss_history": train_res.get("loss_history"),
        "model_params": train_res.get("model_params"),
        "denoising_score": final_scalar,
        "file_vector": file_vector,
        "is_trial": False,
        "trial_strategy": "snapshot",
        "trial_portion": 1.0,
        "train_portion": 0.1,
        "training_psd_segments": sum(len(v) for v in train_sample_set.values()),
        "eval_psd_segments": sum(len(v) for v in eval_sample_set.values()),
        "timing": {
            "train_time_s": train_time,
            "inference_time_s": inference_time,
            "scoring_time_s": scoring_time,
        },
        "memory": {
            "expert_advice_followed": "Legacy TIDMAD paper baseline — no agent involvement.",
            "hypothesis": "Original paper configuration with anchor-normalized scoring.",
            "conclusion": (
                f"Baseline {model_type.upper()} achieved "
                f"denoising_score={final_scalar:.4f} (anchor-normalized)."
            ),
            "discovery": (
                "This is the paper's reference result scored with anchor normalization. "
                "All subsequent agent experiments use the same scoring scale."
            ),
            "memory_update": (
                f"Baseline {model_type.upper()} performance established. "
                f"Anchor-normalized score: {final_scalar:.4f}. "
                "Use this as the minimum target for improvement."
            ),
        },
    }

    sandbox.save_record(record)
    print(f"\n  Baseline complete. Anchor-normalized score: {final_scalar:.4f}")
    print(f"  Timing: train={train_time}s, infer={inference_time}s, score={scoring_time}s")
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
            with open(summary_path, encoding="utf-8") as f:
                existing = json.load(f)
        except (OSError, json.JSONDecodeError):
            existing = []

    already_seeded = any(r.get("exp_id") == baseline_record.get("exp_id") for r in existing)
    if not already_seeded:
        existing.insert(0, baseline_record)
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=4, ensure_ascii=False)
        print(f"\n  Agent memory seeded with baseline record → {summary_path}")
    else:
        print("\n  Agent memory already contains baseline record — skipping seed.")


# ==========================================
# Phase 3: Agent exploration
# ==========================================


def run_agent(
    model_type: str,
    agent_workspace: str,
    agent_run_name: str,
    provider: str,
    model_id: str,
    max_rounds: int,
    progress_bar: bool = False,
    file_index: int = 6,
    is_trial: bool = False,
    human_advice: str = None,
    cleanup_denoised: bool = False,
    reflect_provider: str = None,
    reflect_model_id: str = None,
    formal_strategy: str = "snapshot",
    formal_portion: float = 0.1,
    formal_train_portion: float = 1.0,
):
    """
    Launches nodes/ml_hyperparameter_tune_agent.py as a subprocess, locked to
    model_type, for max_rounds rounds.

    The tuner makes two distinct LLM calls per round (planner + reflector).
    By default both use the same provider+model. Pass `reflect_provider`
    and/or `reflect_model_id` to route the reflector to a different
    provider+model than the planner.
    """
    expert_advice = (
        "You should actively try different model configs, loss types and train configs, "
        "while not exceeding the limit of GPU memory. "
        "The baseline result is already in your memory — "
        "your goal is to find configurations that outperform it."
        "CRITICAL: We are using an RTX 5090 (32GB VRAM), the single model should not use more than 10GB VRAM, but you should try to verify batch size and segmentation to make the best usage of the 10GB limit"
    )

    cmd = [
        sys.executable,
        os.path.join(SIDERIUS_ROOT, "nodes", "ml_hyperparameter_tune_agent.py"),
        "--provider",
        provider,
        "--model_id",
        model_id,
        "--force_model",
        model_type,
        "--max_rounds",
        str(max_rounds),
        "--run_name",
        agent_run_name,
        "--workspace",
        agent_workspace,
        "--expert_advice",
        expert_advice,
    ]
    if reflect_provider:
        cmd.extend(["--reflect_provider", reflect_provider])
    if reflect_model_id:
        cmd.extend(["--reflect_model_id", reflect_model_id])
    if is_trial:
        cmd.append("--is_trial")
    else:
        cmd.extend(["--file_index", str(file_index)])
    if human_advice:
        cmd.extend(["--human_advice", human_advice])
    if progress_bar:
        cmd.append("--progress_bar")
    if cleanup_denoised:
        cmd.append("--cleanup_denoised")
    # Phase M — formal-mode training levers (eval side locked in tuner)
    cmd.extend(["--formal_strategy", formal_strategy])
    cmd.extend(["--formal_portion", str(formal_portion)])
    cmd.extend(["--formal_train_portion", str(formal_train_portion)])

    print(f"\n{'=' * 60}")
    print(f"  PHASE 3 — AGENT EXPLORATION: {model_type.upper()}")
    print(f"  Rounds:    {max_rounds}")
    print(f"  Workspace: {agent_workspace}")
    print(f"  Planner:   {provider} / {model_id}")
    if reflect_provider or reflect_model_id:
        eff_reflect_provider = reflect_provider or provider
        eff_reflect_model_id = reflect_model_id or model_id
        print(f"  Reflector: {eff_reflect_provider} / {eff_reflect_model_id}")
    else:
        print("  Reflector: (same as planner)")
    print(f"{'=' * 60}\n")

    subprocess.run(cmd, cwd=SIDERIUS_ROOT, env=_agent_env(), check=True)


# ==========================================
# Entry point
# ==========================================


def main():
    parser = argparse.ArgumentParser(
        description="SIDERIUS: Compare baseline vs agent-assisted exploration for a TIDMAD model."
    )
    parser.add_argument(
        "--model",
        type=str,
        required=True,
        help="Model architecture to explore (any model in MODEL_REGISTRY or legacy_baseline_configs).",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="gemini",
        choices=["gemini", "openai"],
        help="LLM provider for the planner sub-call (default: gemini). "
        "Also the default for the reflector when --reflect_provider is unset.",
    )
    parser.add_argument(
        "--model_id",
        type=str,
        default="gemini-3.1-flash-lite-preview",
        help="Model ID for the planner sub-call (default: gemini-3.1-flash-lite-preview). "
        "Also the default for the reflector when --reflect_model_id is unset.",
    )
    parser.add_argument(
        "--reflect_provider",
        type=str,
        default=None,
        choices=["gemini", "openai"],
        help="Optional separate provider for the reflector sub-call. "
        "When unset, the reflector uses --provider. Set to a different "
        "vendor (e.g. 'openai') to route the reflector to an entirely "
        "different provider.",
    )
    parser.add_argument(
        "--reflect_model_id",
        type=str,
        default=None,
        help="Optional separate model for the reflector sub-call. "
        "When unset for the gemini provider, defaults to 'gemini-2.5-flash' "
        "(unlimited daily quota, GA model, well-suited for the templated "
        "reflection step). When unset for non-gemini providers, falls "
        "back to --model_id (legacy behavior).",
    )
    parser.add_argument(
        "--max_rounds",
        type=int,
        default=50,
        help="Number of agent exploration rounds (default: 50).",
    )
    parser.add_argument(
        "--progress_bar",
        action="store_true",
        help="Stream live tqdm progress bars from training/inference/scoring subprocesses.",
    )
    parser.add_argument(
        "--run_name",
        type=str,
        default="v1",
        help=(
            "Name for this comparison run (default: v1). "
            "Use different names (e.g. 'test', 'v1', 'v2') to keep runs isolated. "
            "Agent results go to {ROOT_DATA_DIR}/{model}/{run_name}/agent/. "
            "Baseline is shared at {ROOT_DATA_DIR}/{model}/baseline/."
        ),
    )
    parser.add_argument(
        "--override_old_run",
        action="store_true",
        help=(
            "Delete any existing data for --run_name and start fresh. "
            "Without this flag the script will error if the run_name already exists."
        ),
    )
    parser.add_argument(
        "--file_index",
        type=int,
        default=6,
        help="Validation/training file index (default: 6). Ignored when --is_trial.",
    )
    parser.add_argument(
        "--is_trial",
        action="store_true",
        help="Enable trial-explore mode with multi-file sparse sampling.",
    )
    parser.add_argument(
        "--human_advice",
        type=str,
        default=None,
        help="Human guidance for the agent (free-form string, single value).",
    )
    parser.add_argument(
        "--human_advice_file",
        type=str,
        default=None,
        help=(
            "Path to a per-agent human advice JSON file. The file must contain a "
            "single key matching the agent receiving the advice — for the tuner, "
            'use {"tune": "..."}. Strict subset of the aggregated advice file '
            "format used at workflow/chain levels (which has all 5 agent keys). "
            "If both --human_advice and --human_advice_file are given, the file "
            "takes precedence."
        ),
    )
    parser.add_argument(
        "--cleanup_denoised",
        action="store_true",
        help="Delete denoised HDF5 files after scoring each round to save disk space.",
    )
    # --- Formal-mode training levers (Phase M, docs §12) ---
    # Forwarded to the agent subprocess. Formal eval strategy is locked to
    # ``snapshot``; the portion defaults to 1.0 (production full-clone,
    # §12.2) and can be opted down via the agent CLI's
    # ``--formal_eval_portion`` (Phase R, §13) — not surfaced here because
    # this script is a baseline benchmark runner, not a chain entry point.
    parser.add_argument(
        "--formal_strategy",
        type=str,
        default="snapshot",
        choices=["snapshot", "anchors", "target"],
        help="Training-side strategy on formal rounds (default snapshot).",
    )
    parser.add_argument(
        "--formal_portion",
        type=float,
        default=0.1,
        help="Fraction of segments per file for formal training scope (default 0.1).",
    )
    parser.add_argument(
        "--formal_train_portion",
        type=float,
        default=1.0,
        help="Per-epoch iteration fraction for formal training (default 1.0).",
    )
    args = parser.parse_args()

    # --- Resolve reflect provider/model defaults ---
    # The reflector sub-call does templated extraction (not reasoning), so it
    # benefits from a faster/cheaper/higher-quota model than the planner. For
    # the gemini provider, default the reflector to gemini-2.5-flash (GA model,
    # unlimited daily quota, strong JSON-mode). For other providers, leave
    # unset = legacy behavior (reflector uses the planner's model).
    reflect_provider = args.reflect_provider
    reflect_model_id = args.reflect_model_id
    if reflect_model_id is None and reflect_provider is None and args.provider == "gemini":
        # Apply the gemini-specific default. Stays on the gemini provider.
        reflect_model_id = "gemini-2.5-flash"

    # --- Resolve human advice (file > CLI flag > None) ---
    human_advice: str = args.human_advice or ""
    if args.human_advice_file:
        if not os.path.exists(args.human_advice_file):
            raise SystemExit(f"\n[ERROR] --human_advice_file not found: {args.human_advice_file}")
        with open(args.human_advice_file, encoding="utf-8") as f:
            advice_blob = json.load(f)
        if not isinstance(advice_blob, dict) or "tune" not in advice_blob:
            raise SystemExit(
                f"\n[ERROR] Per-agent advice file for the tuner must contain a "
                f"'tune' key. Got keys: {list(advice_blob.keys()) if isinstance(advice_blob, dict) else type(advice_blob).__name__}"
            )
        human_advice = advice_blob["tune"] or ""
        print(f"  Loaded human advice from: {args.human_advice_file}")

    model_type = args.model
    model_root = os.path.join(ROOT_DATA_DIR, model_type)
    run_dir = os.path.join(model_root, args.run_name)
    # Trial and single-file baselines are on different scoring scales — keep separate
    baseline_subdir = "baseline_trial" if args.is_trial else "baseline"
    baseline_workspace = os.path.join(model_root, baseline_subdir)
    agent_workspace = os.path.join(run_dir, "agent")
    agent_run_name = f"{args.run_name}_agent"

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

    print(f"\n{'#' * 60}")
    print(f"  SIDERIUS Comparison Run — {model_type.upper()}")
    print(f"  Baseline  : {baseline_workspace}")
    print(f"  Agent     : {agent_workspace}")
    print(f"  Rounds    : {args.max_rounds}")
    print(f"{'#' * 60}")

    # --- Phase 1: Baseline (computed once, reused across all run_names) ---
    matches = glob.glob(os.path.join(baseline_workspace, "summary_*.json"))
    baseline_done = False
    if matches:
        try:
            with open(matches[0]) as f:
                history = json.load(f)
            if history:
                baseline_record = history[0]
                baseline_done = True
                print(
                    f"\n  Baseline already computed: {baseline_record.get('exp_id')} "
                    f"(score={baseline_record.get('denoising_score', 'N/A')}) — skipping."
                )
        except (OSError, json.JSONDecodeError):
            pass

    if not baseline_done:
        if args.is_trial:
            baseline_record = run_baseline_trial(
                model_type,
                baseline_workspace,
                progress_bar=args.progress_bar,
            )
        else:
            baseline_record = run_baseline(
                model_type,
                baseline_workspace,
                progress_bar=args.progress_bar,
                file_index=args.file_index,
            )

    # --- Phase 2: Seed agent memory ---
    seed_agent_memory(baseline_record, agent_workspace, agent_run_name)

    # --- Write tuner-level run metadata before launching the agent ---
    from datetime import datetime

    from agent.schemas.hyperparam_tuning import ExpertAdvice
    from agent.schemas.run_metadata import (
        PerAgentAdvice,
        TunerRunMetadata,
        capture_env_info,
        capture_git_info,
        write_metadata,
    )

    # Legacy free-form preamble used by run_agent() — captured here so the
    # metadata snapshot reflects exactly what the tuner will see in its prompt.
    legacy_expert_preamble = (
        "You should actively try different model configs, loss types and train configs, "
        "while not exceeding the limit of GPU memory. "
        "The baseline result is already in your memory — "
        "your goal is to find configurations that outperform it."
        "CRITICAL: We are using an RTX 5090 (32GB VRAM), the single model should not use more than 10GB VRAM, but you should try to verify batch size and segmentation to make the best usage of the 10GB limit"
    )

    tuner_meta = TunerRunMetadata(
        run_name=agent_run_name,
        workspace=os.path.abspath(agent_workspace),
        started_at=datetime.now(UTC).isoformat(),
        git=capture_git_info(repo_root=SIDERIUS_ROOT),
        env=capture_env_info(),
        argv=list(sys.argv),
        advice={
            "tune": PerAgentAdvice(
                human=human_advice,
                expert=ExpertAdvice(freeform_notes=legacy_expert_preamble),
            ),
        },
        human_advice_file=args.human_advice_file,
        model_type=model_type,
        llm_provider=args.provider,
        llm_model_id=args.model_id,
        reflect_provider=reflect_provider,
        reflect_model_id=reflect_model_id,
        max_rounds=args.max_rounds,
        file_index=None if args.is_trial else args.file_index,
        is_trial=args.is_trial,
        baseline_score=baseline_record.get("denoising_score"),
    )
    metadata_path = os.path.join(agent_workspace, "tuner_run_metadata.json")
    write_metadata(tuner_meta, metadata_path)
    print(f"  Tuner run metadata written: {metadata_path}")

    # --- Phase 3: Agent exploration ---
    run_agent(
        model_type=model_type,
        agent_workspace=agent_workspace,
        agent_run_name=agent_run_name,
        provider=args.provider,
        model_id=args.model_id,
        reflect_provider=reflect_provider,
        reflect_model_id=reflect_model_id,
        max_rounds=args.max_rounds,
        progress_bar=args.progress_bar,
        file_index=args.file_index,
        is_trial=args.is_trial,
        human_advice=human_advice or None,
        cleanup_denoised=args.cleanup_denoised,
        formal_strategy=args.formal_strategy,
        formal_portion=args.formal_portion,
        formal_train_portion=args.formal_train_portion,
    )

    print(f"\n{'#' * 60}")
    print(f"  Comparison run complete for {model_type.upper()}")
    print(f"  Baseline results : {baseline_workspace}")
    print(f"  Agent results    : {agent_workspace}")
    print(f"{'#' * 60}\n")


if __name__ == "__main__":
    main()
