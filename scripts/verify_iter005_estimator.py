"""
scripts/verify_iter005_estimator.py

Hand-verification harness for the 2026-04-30 estimator hotfix.

Reconstructs the kwargs that the formal-round time gate saw on the
completed explore iter_005 record (gated_context_dualpath_tcn_iter_005_003)
and calls evaluate_time_skill.run_skill so we can compare:

    predicted_total  vs  actual_total

against the V7 formal budget of 120 minutes.

Two scenarios are reported:

  A. Static fallback (no warmup) — the path the gate takes when it
     cannot run a real-data warmup. Conservative / over-prediction.
  B. Synthetic warmup — feed in `actual_train_ms_per_step =
     train_time_s × 1000 / total_train_steps` as if the wrapper had
     measured exactly that. This isolates the per-phase math of the
     warmup path from variance in the warmup measurement itself.

This script is read-only: it does not write or modify any record. It is
meant to be run before committing the hotfix to confirm the recalibration
lands the iter_005 prediction in the user's 90-105 min target band.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from agent.skills.evaluate_time_skill import wrapper as ts
from agent.skills.inference_skill.estimator import _INFERENCE_VS_TRAINING_RATIO
from agent.skills.training_skill.estimator import SAFETY_MULTIPLIER
from core.server_configs.ligroup import CONFIG as LIGROUP

RECORD_DIR = Path(
    "/home/klz/Data/SIDEREIS_DATA/exploration_explore_novel_v7_0429/"
    "iter_005/iteration_001/gated_context_dualpath_tcn"
)
RECORD_PATH = RECORD_DIR / "records/iter_005/gated_context_dualpath_tcn_iter_005_003.json"
TRAIN_SAMPLE_PATH = (
    RECORD_DIR / "configs/iter_005/train_sample_set_gated_context_dualpath_tcn_iter_005_003.json"
)
EVAL_SAMPLE_PATH = (
    RECORD_DIR / "configs/iter_005/eval_sample_set_gated_context_dualpath_tcn_iter_005_003.json"
)
TRIAL_CONFIG_PATH = (
    RECORD_DIR / "configs/iter_005/trial_config_gated_context_dualpath_tcn_iter_005_003.json"
)


class _FakeSandbox:
    """run_skill receives a sandbox arg but does not call it."""


def _fmt(seconds: float) -> str:
    return f"{seconds:>7.1f}s ({seconds / 60:>5.1f} min)"


def _ratio(predicted: float, actual: float) -> str:
    if actual <= 0:
        return "    n/a"
    return f"{predicted / actual:>5.2f}×"


def _run(label: str, kwargs: dict, *, ms_per_step_warmup: float | None) -> None:
    """Invoke run_skill, print the breakdown, compare to actual."""
    actual = kwargs.pop("_actual_timing")
    record_meta = kwargs.pop("_meta")

    # _measure_ms_per_step is monkey-patched onto the wrapper module so we
    # can inject a synthetic warmup without firing up a GPU + DataLoader.
    if ms_per_step_warmup is not None:

        def _stub_warmup(**_kw):
            return ms_per_step_warmup, {
                "n_warmup_batches": 3,
                "n_timed_batches": 7,
                "timings_ms": [ms_per_step_warmup] * 10,
                "aggregator": "median",
            }

        ts._measure_ms_per_step = _stub_warmup
        kwargs["data_dir"] = "/synthetic/path"  # truthy → warmup path
    else:
        # Static fallback: do not inject data_dir, do not stub warmup.
        kwargs.pop("data_dir", None)

    # Patch _count_params on the wrapper so we don't have to instantiate
    # the agent_generated plugin (it isn't on disk anymore).
    ts._count_params = lambda mt, mc, lt: record_meta["model_params"]

    result = ts.run_skill(_FakeSandbox(), **kwargs)

    pb = result["phase_breakdown"]
    train_s = pb["training"]["seconds"]
    inf_s = pb["inference"]["seconds"]
    score_s = pb["scoring"]["seconds"]
    total_s = train_s + inf_s + score_s

    train_ms = pb["training"]["breakdown"]["ms_per_step"]
    inf_ms = pb["inference"]["breakdown"]["ms_per_step"]
    inf_steps = pb["inference"]["breakdown"]["total_inference_steps"]
    train_steps = pb["training"]["breakdown"]["total_train_steps"]

    print(f"  ── {label} ──")
    print(f"  ms/step (train, post-k×safety not applied to display): {train_ms:.2f}")
    print(f"  ms/step (inference, post-ratio):                       {inf_ms:.2f}")
    print(f"  total_train_steps: {train_steps}     total_inf_steps: {inf_steps}")
    print("  Phase            predicted          actual           pred/actual")
    print(
        f"  training      {_fmt(train_s)}    {_fmt(actual['train_time_s'])}    {_ratio(train_s, actual['train_time_s'])}"
    )
    print(
        f"  inference     {_fmt(inf_s)}    {_fmt(actual['inference_time_s'])}    {_ratio(inf_s, actual['inference_time_s'])}"
    )
    print(
        f"  scoring       {_fmt(score_s)}    {_fmt(actual['scoring_time_s'])}    {_ratio(score_s, actual['scoring_time_s'])}"
    )
    print(
        f"  TOTAL         {_fmt(total_s)}    {_fmt(sum(actual.values()))}    {_ratio(total_s, sum(actual.values()))}"
    )
    print(f"  dominant_phase: {result['dominant_phase']}")
    print()


def main() -> None:
    record = json.loads(RECORD_PATH.read_text())
    train_set = json.loads(TRAIN_SAMPLE_PATH.read_text())
    eval_set = json.loads(EVAL_SAMPLE_PATH.read_text())
    trial_config = json.loads(TRIAL_CONFIG_PATH.read_text())

    params = record["params"]
    timing = record["timing"]
    memory = record["memory"]

    # Normalize sample_set values to lists of ints (json loads them already
    # as lists, but defensively cast in case they came through as strings).
    train_set = {k: list(v) for k, v in train_set.items()}
    eval_set = {k: list(v) for k, v in eval_set.items()}

    n_train_psd = sum(len(v) for v in train_set.values())
    n_eval_psd = sum(len(v) for v in eval_set.values())
    seg = params["model_config"]["segmentation_size"]
    bs = params["train_config"]["batch_size"]
    epochs = params["train_config"]["epochs"]
    train_portion = trial_config["train_portion"]

    # Back out actual ms/step from the realised training time.
    from execute_tools.dataset_config import SEGMENT_LENGTH as PSD_LEN

    ml_per_psd = PSD_LEN // seg
    total_train_steps = math.ceil(n_train_psd * ml_per_psd * train_portion / bs) * epochs
    actual_train_ms_per_step = (timing["train_time_s"] * 1000.0) / total_train_steps

    print("=" * 72)
    print("iter_005 verification — gated_context_dualpath_tcn (formal, round 3)")
    print("=" * 72)
    print(f"  Record:          {RECORD_PATH.name}")
    print(f"  model_type:      {params['model_type']}")
    print(f"  num_params:      {record['model_params']:,}")
    print(f"  seg_size:        {seg}    batch_size: {bs}    epochs: {epochs}")
    print(f"  loss:            {params['loss_config']['loss_type']}")
    print(f"  train PSDs:      {n_train_psd}   (train_portion={train_portion})")
    print(f"  eval PSDs:       {n_eval_psd}    (eval_portion={trial_config['eval_portion']})")
    print(f"  inference_batch: {params['inference_batch']}")
    print()
    print("  Hotfix constants in effect:")
    print(f"    SAFETY_MULTIPLIER             = {SAFETY_MULTIPLIER}")
    print(f"    _INFERENCE_VS_TRAINING_RATIO  = {_INFERENCE_VS_TRAINING_RATIO}")
    print(f"    per_psd_segment_seconds       = {LIGROUP.per_psd_segment_seconds}")
    print()
    print(f"  Gate-time prediction at the original run: {memory['time_estimate_minutes']:.1f} min")
    print(f"  Actual realised total:                    {sum(timing.values()) / 60:.1f} min")
    print("  V7 formal budget after hotfix:            120.0 min")
    print("  User target band:                         90 - 105 min")
    print()
    print(f"  Backed-out actual training ms/step: {actual_train_ms_per_step:.1f}")
    print(f"    (train_time_s={timing['train_time_s']:.0f}, total_steps={total_train_steps})")
    print()

    base_kwargs = {
        "model_type": params["model_type"],
        "model_config": params["model_config"],
        "train_config": params["train_config"],
        "loss_config": params["loss_config"],
        "sample_set": train_set,
        "eval_sample_set": eval_set,
        "train_portion": train_portion,
        "time_budget_minutes": 120.0,
        "_actual_timing": timing,
        "_meta": {"model_params": record["model_params"]},
    }

    # Scenario A: static fallback (no warmup)
    _run("Scenario A: static fallback (no warmup)", dict(base_kwargs), ms_per_step_warmup=None)

    # Scenario B: synthetic warmup matching the realised training pace
    _run(
        f"Scenario B: synthetic warmup at {actual_train_ms_per_step:.0f} ms/step",
        dict(base_kwargs),
        ms_per_step_warmup=actual_train_ms_per_step,
    )


if __name__ == "__main__":
    main()
