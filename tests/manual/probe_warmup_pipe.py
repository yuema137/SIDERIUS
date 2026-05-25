"""Phase 6.8 Commit 11 — Gate 1 (Option 1A): Warmup pipe accuracy probe.

Calls agent.skills.evaluate_time_skill.wrapper.run_skill directly with a real
data_dir and a tiny sample_set, then asserts ms_source == 'real_dataset_warmup'
in the breakdown.

This isolates the warmup plumbing from LLM and node orchestration so a green
result here proves the data path is genuinely open end-to-end.

Run:
    .venv/bin/python tests/manual/probe_warmup_pipe.py
"""

from __future__ import annotations

import json
import sys

from agent.skills.evaluate_time_skill import wrapper as time_skill

DATA_DIR = "/home/klz/Data/TIDMAD/"


def main() -> int:
    sample_set = {"0": list(range(0, 16))}

    model_type = "punet"
    model_config = {
        "model_type": "punet",
        "multi": 16,
        "depth": 2,
        "bilinear": True,
        "pe_factor": 1.0,
        "kernel_size": 9,
        "embedding_dim": 32,
        "segmentation_size": 1000,
    }
    train_config = {
        "batch_size": 8,
        "epochs": 1,
        "lr": 1e-3,
        "optimizer_type": "adamw",
        "weight_decay": 0.01,
    }
    loss_config = {"loss_type": "ce"}

    print(f"[env] data_dir         = {DATA_DIR}")
    print(f"[env] sample_set       = {sample_set}")
    print(f"[env] model_type       = {model_type}")
    print(f"[env] segmentation_size= {model_config['segmentation_size']}")
    print(f"[env] batch_size       = {train_config['batch_size']}")
    print()
    print("[step] invoking time_skill.run_skill with data_dir present...")
    print("-" * 70)

    result = time_skill.run_skill(
        sandbox=None,
        model_type=model_type,
        model_config=model_config,
        train_config=train_config,
        loss_config=loss_config,
        sample_set=sample_set,
        train_portion=0.1,
        time_budget_minutes=10.0,
        data_dir=DATA_DIR,
    )

    print("-" * 70)
    print("[result] full payload (truncated):")
    pruned = {k: v for k, v in result.items() if k not in ("phase_breakdown",)}
    print(json.dumps(pruned, indent=2, default=str))

    train_breakdown = result.get("phase_breakdown", {}).get("training", {}).get("breakdown", {})
    ms_source = train_breakdown.get("ms_source")
    ms_per_step = train_breakdown.get("ms_per_step")

    print()
    print("=== GATE 1 EVIDENCE ===")
    print(f"  ms_source     : {ms_source!r}")
    print(f"  ms_per_step   : {ms_per_step}")
    print(f"  k_correction  : {train_breakdown.get('k_correction')}")
    print(f"  gpu_name      : {train_breakdown.get('gpu_name')}")

    warmup_bd = result.get("phase_breakdown", {}).get("training", {}).get("warmup_breakdown")
    if warmup_bd is None:
        # surface from top-level if wrapper places it elsewhere
        warmup_bd = result.get("warmup_breakdown")
    print(f"  warmup_brkdwn : {warmup_bd}")

    ok = ms_source == "real_dataset_warmup"
    print(f"  GATE 1 status : {'PASS' if ok else 'FAIL'}")
    if not ok:
        print(
            "\n[FAIL DETAIL] expected ms_source == 'real_dataset_warmup' "
            f"but got {ms_source!r}. The warmup path was NOT entered "
            "despite data_dir being present — the plumbing is broken."
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
