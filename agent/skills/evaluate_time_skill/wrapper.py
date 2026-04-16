"""
evaluate_time_skill/wrapper.py

Pre-flight wall-time estimator for a proposed training experiment.

Pipeline (full design in docs/time_estimator_implement.md):
    1. Compute total step count from sample_set, seg_size, batch_size,
       train_portion, epochs (pure arithmetic).
    2. Count model params by instantiating the real model class.
    3. Measure ms/step — static formula in Phase B, real-dataset GPU warmup
       in Phase C.
    4. Apply learned per-GPU correction factor k(gpu, model_type) — Phase F.
    5. Multiply by SAFETY_MULTIPLIER; compare against time_budget_minutes.

Phase B (current): step counting, static-formula ms/step, feasibility gate,
suggestion logic. No live warmup, no calibration yet. The skill still returns
the full output contract so later phases only need to swap the ms/step source.
"""

from __future__ import annotations

import gc
import math
import os
import time
import traceback

from execute_tools.dataset_config import SEGMENT_LENGTH as PSD_SEGMENT_LENGTH


# Safety margin applied on top of (ms_per_step × k). Tight because the
# real-dataset warmup in Phase C will capture DataLoader / HDF5 / GPU path.
# In Phase B (static formula), the multiplier is effectively the only cushion.
SAFETY_MULTIPLIER: float = 1.1

# Static ms/step fallback used when Phase C warmup is unavailable (no CUDA /
# no data_dir / unit tests). Derived from ~6 FLOPs per param per sample (fwd+bwd)
# divided by a pessimistic 1e10 flops/ms throughput. This is order-of-magnitude
# only — real estimates come from the warmup in Phase C.
_STATIC_MS_PER_FLOP: float = 6e-10


# ── pure helpers (testable without torch) ────────────────────────────────────


def _total_train_steps(
    sample_set: dict,
    seg_size: int,
    batch_size: int,
    train_portion: float,
    epochs: int,
) -> int:
    """Compute total train steps across all epochs.

    Args:
        sample_set:     {file_index (str): [PSD segment indices]}.
        seg_size:       ML segmentation size; each PSD seg produces
                        ``PSD_SEGMENT_LENGTH // seg_size`` ML segments.
        batch_size:     ML batches per forward pass.
        train_portion:  Per-epoch subsampling fraction (0.01–1.0).
        epochs:         Number of training epochs.

    Returns:
        Total fwd+bwd step count across the whole training run.
    """
    n_psd = sum(len(v) for v in sample_set.values())
    ml_per_psd = PSD_SEGMENT_LENGTH // seg_size
    per_epoch = math.ceil(n_psd * ml_per_psd * train_portion / batch_size)
    return per_epoch * epochs


def _static_ms_per_step(num_params: int, seg_size: int, batch_size: int) -> float:
    """Coarse static estimate of ms per training step. Used only when the
    Phase C warmup is unavailable. Order-of-magnitude accuracy at best."""
    return num_params * seg_size * batch_size * _STATIC_MS_PER_FLOP


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


# ── torch-dependent helpers ──────────────────────────────────────────────────


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
    """Estimate training wall-time for the proposed config and gate against
    the time budget.

    Required kwargs: model_type, model_config, train_config, loss_config,
                     sample_set, time_budget_minutes.
    Optional kwargs: train_portion (default 1.0), data_dir (Phase C+).

    Returns a dict with keys: status, feasible, verdict, suggestion,
    estimated_minutes, limit_minutes, breakdown.
    """
    model_type = kwargs.get("model_type")
    model_config = kwargs.get("model_config", {})
    train_config = kwargs.get("train_config", {})
    loss_config = kwargs.get("loss_config", {})
    sample_set = kwargs.get("sample_set", {})
    train_portion = float(kwargs.get("train_portion", 1.0))
    budget_min = float(kwargs.get("time_budget_minutes", 0.0))
    data_dir = kwargs.get("data_dir")

    seg_size = int(model_config.get("segmentation_size", 1000))
    batch_size = int(train_config.get("batch_size", 1))
    epochs = int(train_config.get("epochs", 1))
    loss_type = loss_config.get("loss_type", "ce")

    print(
        f"\n>>> [Skill: TimeEval] Checking wall-time for {str(model_type).upper()} "
        f"(bs={batch_size}, seg={seg_size}, epochs={epochs}, budget={budget_min:.0f} min)..."
    )

    try:
        total_steps = _total_train_steps(
            sample_set, seg_size, batch_size, train_portion, epochs
        )
        num_params = _count_params(model_type, model_config, loss_type)
    except Exception as e:
        msg = f"TimeEval error: {e}\n{traceback.format_exc()}"
        print(f"!!! [TimeEval] {msg}")
        return {"status": "error", "message": msg}

    # Prefer the real-dataset live warmup; fall back to the static formula
    # when CUDA / data_dir / model build is unavailable (e.g. unit tests,
    # CPU-only hosts). Phase F will fold in the learned correction factor k.
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

    if measured is not None and measured > 0:
        ms_per_step = measured
        ms_source = "real_dataset_warmup"
    else:
        ms_per_step = _static_ms_per_step(num_params, seg_size, batch_size)
        ms_source = "static_formula_phase_b"

    k_correction = 1.0
    total_min = (
        total_steps * ms_per_step * k_correction * SAFETY_MULTIPLIER / 60_000.0
    )

    feasible = total_min <= budget_min
    breakdown = {
        "total_train_steps": total_steps,
        "ms_per_step_warmup": round(ms_per_step, 4),
        "k_correction": k_correction,
        "safety_multiplier": SAFETY_MULTIPLIER,
        "train_minutes": round(total_min, 2),
        "num_params": num_params,
        "source": ms_source,
    }

    verdict = (
        f"{'✅ FITS' if feasible else '❌ OVER BUDGET'} — "
        f"Est {total_min:.1f} min vs budget {budget_min:.1f} min "
        f"({total_steps:,} steps × {ms_per_step:.2f} ms/step × "
        f"{SAFETY_MULTIPLIER:g} safety)."
    )
    suggestion = "" if feasible else _suggest_lever(ms_per_step, seg_size, batch_size)

    print(f"    Parameters   : {num_params:,}")
    print(f"    Total steps  : {total_steps:,}")
    print(f"    ms/step      : {ms_per_step:.2f}  ({ms_source})")
    print(f"    Est minutes  : {total_min:.1f} / budget {budget_min:.1f}")
    print(f"    Feasible     : {'YES' if feasible else 'NO'}")
    if suggestion:
        print(f"    Suggestion   : {suggestion}")

    return {
        "status": "success",
        "feasible": feasible,
        "verdict": verdict,
        "suggestion": suggestion,
        "estimated_minutes": round(total_min, 2),
        "limit_minutes": budget_min,
        "breakdown": breakdown,
    }
