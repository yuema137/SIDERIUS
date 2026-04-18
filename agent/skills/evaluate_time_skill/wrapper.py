"""
evaluate_time_skill/wrapper.py

Sum-time aggregator over the three execution phases. Estimates the
total wall-time a proposed experiment will take and checks it against
the per-mode time budget.

Call this BEFORE training to avoid burning the round on a config that
won't finish in time.

Aggregation (K.2.5):
  The three phases — training, inference, scoring — run *sequentially*
  (execute_training → execute_inference → execute_scoring). The total
  wall-time is the sum of each phase's seconds. This wrapper calls the
  three per-phase estimators and sums:

      training_skill/estimator.py:estimate_wall_time_seconds
      inference_skill/estimator.py:estimate_wall_time_seconds
      denoising_score_skill/estimator.py:estimate_wall_time_seconds

  Per-phase formulae live next to the code that actually executes each
  phase — see each estimator's docstring. This wrapper owns the
  warmup infrastructure (the real-dataset ms/step measurement that
  feeds the training + inference phases) and picks the sum.

Warmup -> per-phase ms/step derivation:
  * Training ms/step     = the measured warmup value (training estimator
                           applies k(gpu, model_type) + SAFETY_MULTIPLIER).
  * Inference ms/step    = measured training ms/step × 1/3 (no backward
                           pass). See inference_skill/estimator.py.
  * Scoring wall-time    = total_psd_segments × per_psd_segment_seconds /
                           num_workers, from core/server_configs/{hostname}.py.
  * Fallback: if warmup fails / no CUDA / no data_dir, each estimator
    falls back to its own static formula; static ms/step for training
    uses ``num_params × seg × bs × 6e-10`` (Phase B behaviour,
    breakdown.source == "static_formula_phase_b").

Breakdown contract:
  The flat ``breakdown`` dict in the return preserves the pre-K.2.5
  keys that downstream callers depend on. In particular,
  ``nodes/ml_hyperparameter_tune_agent.py`` reads ``breakdown.source``
  and ``breakdown.gpu_name`` to decide when to trigger the Phase F
  per-GPU EMA update. The three-phase split is surfaced separately
  under ``phase_breakdown``.

See docs/resource_estimator_implement.md §10.5 / §10.14 Commit 6.
"""

from __future__ import annotations

import gc
import math
import os
import time
import traceback

from execute_tools.dataset_config import SEGMENT_LENGTH as PSD_SEGMENT_LENGTH

from agent.skills.training_skill        import estimator as _training_est
from agent.skills.inference_skill       import estimator as _inference_est
from agent.skills.denoising_score_skill import estimator as _scoring_est


# Inference has no backward pass; training ms/step includes bwd+optimizer+loss.
# Mirrors inference_skill/estimator.py's _INFERENCE_VS_TRAINING_RATIO so the
# warmup-derived inference ms/step matches the static formula's slope.
_INFERENCE_VS_TRAINING_RATIO: float = 1.0 / 3.0


# ── pure helpers (testable without torch) ────────────────────────────────────


def _suggest_lever(ms_per_step: float, seg_size: int, batch_size: int) -> str:
    """Pick the dominant lever to recommend based on where time is going."""
    if ms_per_step > 50.0:
        return (
            "Reduce model depth/width (num_blocks, hidden_channels, "
            "embedding_dim) — per-step cost is dominant."
        )
    if seg_size < 10_000 and batch_size == 1:
        return (
            "Raise batch_size (amortises per-step cost without changing "
            "model capacity)."
        )
    return (
        "Raise segmentation_size to the next valid divisor of 10,000,000 "
        "so fewer steps cover the same data."
    )


# ── torch-dependent helpers (warmup infrastructure) ──────────────────────────


def _detect_gpu_name() -> str | None:
    """Return the active CUDA device name, or None on CPU-only / import-fail
    hosts. Stable across SDSC node reassignment because it queries the GPU,
    not the hostname (§2.6.4)."""
    try:
        import torch
    except ImportError:
        return None
    if not torch.cuda.is_available():
        return None
    try:
        return torch.cuda.get_device_name(0)
    except Exception:
        return None


def _count_params(model_type: str, model_config: dict, loss_type: str) -> int:
    """Instantiate the model on CPU and return exact parameter count.

    Kept in a function so tests can monkeypatch it without importing torch.
    """
    from ml_models.models_sandbox import MODEL_REGISTRY
    from ml_models.models_format_sandbox import get_config_class

    config_cls = get_config_class(model_type)
    config_obj = config_cls(**model_config)
    if model_type == "fcnet":
        model = MODEL_REGISTRY[model_type](config_obj, loss_type=loss_type)
    else:
        model = MODEL_REGISTRY[model_type](config_obj)
    return sum(p.numel() for p in model.parameters())


def _measure_ms_per_step(
    model_type: str,
    model_config: dict,
    train_config: dict,
    loss_config: dict,
    data_dir: str,
    sample_set: dict,
    n_warmup_batches: int = 1,
    n_timed_batches: int = 2,
) -> float | None:
    """Measure real ms/step by running a micro training pass on 1+ real PSDs.

    Mirrors the training code path in ``execute_tools.train_engine_sandbox`` so
    the measurement captures GPU compute, disk/HDF5 load, DataLoader overhead,
    and the actual model+loss+optimizer combination in one shot.

    Returns ``None`` on any failure (missing CUDA, missing data_dir, model
    instantiation error, etc.) — caller falls back to the static formula.
    """
    if not data_dir or not os.path.isdir(data_dir):
        print("    [warmup skipped] no data_dir; falling back to static formula.")
        return None

    try:
        import torch
    except ImportError:
        return None
    if not torch.cuda.is_available():
        print("    [warmup skipped] CUDA not available; falling back to static formula.")
        return None

    try:
        import random
        from torch.utils.data import DataLoader

        from execute_tools.train_engine_sandbox import TIDMADEpochDataset
        from ml_models.models_sandbox import MODEL_REGISTRY
        from ml_models.models_format_sandbox import (
            LossConfig,
            TrainConfig,
            get_config_class,
        )
        from ml_models.loss_models_sandbox import get_criterion

        seg_size = int(model_config["segmentation_size"])
        batch_size = int(train_config.get("batch_size", 1))
        loss_type = loss_config.get("loss_type", "ce")

        # Pick a minimal slice of the sample_set large enough for the required batches.
        if not sample_set:
            return None
        first_key = sorted(sample_set.keys(), key=int)[0]
        first_psds = list(sample_set[first_key])
        if not first_psds:
            return None

        ml_per_psd = PSD_SEGMENT_LENGTH // seg_size
        required_segs = (n_warmup_batches + n_timed_batches) * batch_size
        n_psd_needed = max(1, math.ceil(required_segs / max(ml_per_psd, 1)))
        n_psd_needed = min(n_psd_needed, 5, len(first_psds))
        mini_sample_set = {first_key: first_psds[:n_psd_needed]}

        dataset = TIDMADEpochDataset(
            data_dir=data_dir,
            sample_set=mini_sample_set,
            seg_size=seg_size,
            train_portion=1.0,
            rng=random.Random(0),
        )
        if len(dataset) < required_segs:
            print(
                f"    [warmup skipped] mini dataset too small "
                f"({len(dataset)} < {required_segs} required); falling back."
            )
            return None
        loader = DataLoader(dataset, batch_size=batch_size, shuffle=False, drop_last=True)

        device = torch.device("cuda")

        config_cls = get_config_class(model_type)
        model_cfg_obj = config_cls(**model_config)
        if model_type == "fcnet":
            model = MODEL_REGISTRY[model_type](model_cfg_obj, loss_type=loss_type).to(device)
        else:
            model = MODEL_REGISTRY[model_type](model_cfg_obj).to(device)

        train_cfg_obj = TrainConfig(**train_config)
        loss_cfg_obj = LossConfig(**loss_config)
        criterion = get_criterion(loss_cfg_obj, class_weights=None)

        if train_cfg_obj.optimizer_type == "adamw":
            optimizer = torch.optim.AdamW(
                model.parameters(),
                lr=train_cfg_obj.lr,
                weight_decay=train_cfg_obj.weight_decay,
            )
        elif train_cfg_obj.optimizer_type == "adam":
            optimizer = torch.optim.Adam(model.parameters(), lr=train_cfg_obj.lr)
        else:
            optimizer = torch.optim.SGD(model.parameters(), lr=train_cfg_obj.lr)

        model.train()
        timings_ms = []
        it = iter(loader)
        for step in range(n_warmup_batches + n_timed_batches):
            try:
                x, y = next(it)
            except StopIteration:
                break
            x = x.to(device)
            y = y.to(device)
            if model_type == "fcnet":
                x = x.float()
            else:
                x = x.int()
            if loss_type in ("ce", "focal", "focal_cw"):
                y = y.long()
            else:
                y = y.float()

            torch.cuda.synchronize()
            t0 = time.perf_counter()
            optimizer.zero_grad()
            out = model(x)
            loss = criterion(out, y)
            loss.backward()
            optimizer.step()
            torch.cuda.synchronize()
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            if step >= n_warmup_batches:
                timings_ms.append(elapsed_ms)

        del model, optimizer, criterion, dataset, loader
        torch.cuda.empty_cache()
        gc.collect()

        if not timings_ms:
            return None
        return sum(timings_ms) / len(timings_ms)

    except Exception as exc:  # pragma: no cover — defensive
        print(f"    [warmup failed] {exc}\n{traceback.format_exc(limit=3)}")
        try:
            import torch

            torch.cuda.empty_cache()
        except Exception:
            pass
        return None


# ── public entry point ───────────────────────────────────────────────────────


def run_skill(sandbox, **kwargs) -> dict:
    """Estimate wall-time (training + inference + scoring) for the proposed
    config and gate against the time budget.

    Required kwargs: model_type, model_config, train_config, loss_config,
                     sample_set, time_budget_minutes.
    Optional kwargs: train_portion (default 1.0), data_dir (enables warmup).

    Returns a dict with keys: status, feasible, verdict, suggestion,
    estimated_minutes, limit_minutes, breakdown, dominant_phase,
    phase_breakdown.
    """
    model_type   = kwargs.get("model_type")
    model_config = kwargs.get("model_config", {})
    train_config = kwargs.get("train_config", {})
    loss_config  = kwargs.get("loss_config", {})
    sample_set   = kwargs.get("sample_set", {})
    train_portion = float(kwargs.get("train_portion", 1.0))
    budget_min   = float(kwargs.get("time_budget_minutes", 0.0))
    data_dir     = kwargs.get("data_dir")

    seg_size   = int(model_config.get("segmentation_size", 1000))
    batch_size = int(train_config.get("batch_size", 1))
    epochs     = int(train_config.get("epochs", 1))
    loss_type  = loss_config.get("loss_type", "ce")

    print(
        f"\n>>> [Skill: TimeEval] Checking wall-time for {str(model_type).upper()} "
        f"(bs={batch_size}, seg={seg_size}, epochs={epochs}, budget={budget_min:.0f} min)..."
    )

    try:
        num_params = _count_params(model_type, model_config, loss_type)

        # Real-dataset warmup — only with CUDA + data_dir. Feeds the
        # training estimator directly and the inference estimator after
        # scaling by _INFERENCE_VS_TRAINING_RATIO.
        measured = None
        if data_dir:
            measured = _measure_ms_per_step(
                model_type=model_type,
                model_config=model_config,
                train_config=train_config,
                loss_config=loss_config,
                data_dir=data_dir,
                sample_set=sample_set,
            )
        gpu_name = _detect_gpu_name()

        training = _training_est.estimate_wall_time_seconds(
            model_type, model_config, train_config, sample_set,
            train_portion=train_portion,
            ms_per_step=measured,
            gpu_name=gpu_name,
            num_params=num_params,
            loss_type=loss_type,
        )

        inference_ms = (
            measured * _INFERENCE_VS_TRAINING_RATIO
            if (measured is not None and measured > 0)
            else None
        )
        inference = _inference_est.estimate_wall_time_seconds(
            model_type, model_config, sample_set,
            inference_ms_per_step=inference_ms,
            num_params=num_params,
        )

        scoring = _scoring_est.estimate_wall_time_seconds(sample_set)

    except Exception as e:
        msg = f"TimeEval error: {e}\n{traceback.format_exc()}"
        print(f"!!! [TimeEval] {msg}")
        return {"status": "error", "message": msg}

    phases     = [training, inference, scoring]
    total_sec  = sum(p["seconds"] for p in phases)
    total_min  = total_sec / 60.0
    phase_breakdown = {p["phase"]: p for p in phases}
    dominant   = max(phases, key=lambda p: p["seconds"])["phase"]

    feasible = total_min <= budget_min

    # Flat breakdown: preserves the pre-K.2.5 contract so
    # nodes/ml_hyperparameter_tune_agent.py can still read `source` +
    # `gpu_name` to trigger the Phase F EMA update.
    tbd = training["breakdown"]
    breakdown = {
        "total_train_steps":  tbd["total_train_steps"],
        "ms_per_step_warmup": tbd["ms_per_step"],
        "k_correction":       tbd["k_correction"],
        "safety_multiplier":  tbd["safety_multiplier"],
        "train_minutes":      round(training["seconds"] / 60.0, 2),
        "num_params":         num_params,
        "source":             tbd["ms_source"],
        "gpu_name":           tbd["gpu_name"],
    }

    verdict = (
        f"{'✅ FITS' if feasible else '❌ OVER BUDGET'} — "
        f"Est {total_min:.1f} min vs budget {budget_min:.1f} min "
        f"(train {training['seconds']:.1f}s + inf {inference['seconds']:.1f}s "
        f"+ score {scoring['seconds']:.1f}s). Dominant phase: {dominant}."
    )
    suggestion = "" if feasible else _suggest_lever(
        tbd["ms_per_step"], seg_size, batch_size
    )

    print(f"    Parameters   : {num_params:,}")
    print(f"    Train steps  : {tbd['total_train_steps']:,}")
    print(f"    ms/step      : {tbd['ms_per_step']:.2f}  ({tbd['ms_source']})")
    print(
        f"    Phase sec    : train={training['seconds']:.1f} "
        f"inf={inference['seconds']:.1f} score={scoring['seconds']:.1f}"
    )
    print(f"    Est minutes  : {total_min:.1f} / budget {budget_min:.1f}  "
          f"(dominant: {dominant})")
    print(f"    Feasible     : {'YES' if feasible else 'NO'}")
    if suggestion:
        print(f"    Suggestion   : {suggestion}")

    return {
        "status":            "success",
        "feasible":          feasible,
        "verdict":           verdict,
        "suggestion":        suggestion,
        "estimated_minutes": round(total_min, 2),
        "limit_minutes":     budget_min,
        "breakdown":         breakdown,
        "dominant_phase":    dominant,
        "phase_breakdown":   phase_breakdown,
    }
