"""
agent/skills/training_skill/estimator.py

Per-phase VRAM and wall-time estimator for the TRAINING phase of a
proposed experiment. Lifted from ``evaluate_vram_skill.wrapper._estimate_bytes``
and the step-count × ms/step × k logic in
``evaluate_time_skill.wrapper.run_skill`` during Phase K.2.5 so the two
resource aggregators (``evaluate_vram_skill`` = peak over phases;
``evaluate_time_skill`` = sum over phases) can compose training +
inference + scoring without each owning a copy of the training-phase
formulas.

Contract (K.2.5 Commit 2):
  * ``estimate_peak_bytes(model_type, model_config, train_config,
    loss_config, num_params)`` — worst-case float32 training memory:
    weights + grads + Adam m + v + output logits + backward activations
    + optional focal one_hot + optional transformer self-attention.
    Returns ``{"phase": "training", "total_bytes", "breakdown"}``.
  * ``estimate_wall_time_seconds(model_type, model_config, train_config,
    sample_set, *, train_portion, ms_per_step, gpu_name, num_params,
    loss_type)`` — total_steps × ms/step × k(gpu, model_type) ×
    SAFETY_MULTIPLIER. Returns ``{"phase": "training", "seconds",
    "breakdown"}``. When ``ms_per_step`` is not supplied, the static
    formula is used (k stays 1.0) — mirrors the wrapper's pre-K.2.5
    fallback so callers without a live warmup signal still get an order-
    of-magnitude estimate.

The estimator is pure (no side effects other than CPU model
instantiation for ``_count_params``): the real-dataset warmup stays in
the aggregator, keeping this module cheap and test-friendly.

See docs/resource_estimator_implement.md §10.5 + §10.14 Commit 2.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from execute_tools.dataset_config import SEGMENT_LENGTH as PSD_SEGMENT_LENGTH
from agent.skills.evaluate_time_skill import calibration


# ── constants (mirror the legacy wrapper verbatim) ───────────────────────────

_BYTES_F32 = 4
_BYTES_I64 = 8

# Safety margin applied on top of ms/step × k. Kept at the wrapper's value so
# aggregator output is byte-identical to the pre-K.2.5 training-only estimate
# for training-dominant configs.
SAFETY_MULTIPLIER: float = 1.1

# Static ms/step fallback used when the aggregator cannot supply a warmup-
# measured ms_per_step (CPU-only hosts, unit tests, failed warmup).
_STATIC_MS_PER_FLOP: float = 6e-10


# ── VRAM ─────────────────────────────────────────────────────────────────────


def estimate_peak_bytes(
    model_type: str,
    model_config: Dict[str, Any],
    train_config: Dict[str, Any],
    loss_config: Dict[str, Any],
    num_params: int,
) -> Dict[str, Any]:
    """Estimate peak training-phase VRAM for the given config.

    Worst-case float32 training memory:

      * ``num_params × 16 B``   (weights 4 + grads 4 + Adam m 4 + v 4)
      * output logits            (B × 256 × T × 4)
      * backward activations     (~2 × output_logits; 1× for fcnet)
      * focal one_hot            (B × 256 × T × 8; focal loss only)
      * transformer attention    (B × nhead × T² × 4 × num_layers; transformer only)

    Args:
        model_type:   Model architecture key (e.g. ``"rnn"``, ``"transformer"``).
        model_config: Model configuration dict (``segmentation_size`` etc.).
        train_config: Training configuration dict (``batch_size`` etc.).
        loss_config:  Loss configuration dict (``loss_type``).
        num_params:   Exact parameter count from a prior CPU instantiation.

    Returns:
        ``{"phase": "training", "total_bytes": int, "breakdown": {...}}``.
    """
    seg_size   = model_config.get("segmentation_size", 40000)
    batch_size = train_config.get("batch_size", 1)
    loss_type  = loss_config.get("loss_type", "ce")

    # weights (4) + grads (4) + Adam m (4) + Adam v (4) = 16 bytes per param.
    model_overhead = num_params * 16 * _BYTES_F32 // 4

    output_logits = batch_size * 256 * seg_size * _BYTES_F32

    act_factor = 1 if model_type == "fcnet" else 2
    activations = act_factor * output_logits

    focal_onehot = (
        batch_size * 256 * seg_size * _BYTES_I64 if loss_type == "focal" else 0
    )

    transformer_attn = 0
    if model_type == "transformer":
        nhead      = model_config.get("nhead", 2)
        num_layers = model_config.get("num_layers", 2)
        transformer_attn = (
            batch_size * nhead * seg_size * seg_size * _BYTES_F32 * num_layers
        )

    total = model_overhead + output_logits + activations + focal_onehot + transformer_attn

    return {
        "phase":       "training",
        "total_bytes": total,
        "breakdown": {
            "model_overhead_bytes":   model_overhead,
            "output_logits_bytes":    output_logits,
            "activations_bytes":      activations,
            "focal_onehot_bytes":     focal_onehot,
            "transformer_attn_bytes": transformer_attn,
        },
    }


# ── Wall time ────────────────────────────────────────────────────────────────


def _total_train_steps(
    sample_set: Dict[str, List[int]],
    seg_size: int,
    batch_size: int,
    train_portion: float,
    epochs: int,
) -> int:
    """Total fwd+bwd step count across the whole training run. Matches
    ``evaluate_time_skill.wrapper._total_train_steps`` exactly."""
    n_psd = sum(len(v) for v in sample_set.values())
    ml_per_psd = PSD_SEGMENT_LENGTH // seg_size
    per_epoch = math.ceil(n_psd * ml_per_psd * train_portion / batch_size)
    return per_epoch * epochs


def _static_ms_per_step(num_params: int, seg_size: int, batch_size: int) -> float:
    """Coarse static estimate of ms per training step. Order-of-magnitude only."""
    return num_params * seg_size * batch_size * _STATIC_MS_PER_FLOP


def _count_params(model_type: str, model_config: dict, loss_type: str) -> int:
    """Instantiate the model on CPU to get an exact parameter count.

    Module-level so tests can monkeypatch it without importing torch, and
    so the aggregator (commit 6) can pre-compute and pass ``num_params``
    to both ``estimate_peak_bytes`` and ``estimate_wall_time_seconds``
    without duplicating the instantiation.
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


def estimate_wall_time_seconds(
    model_type: str,
    model_config: Dict[str, Any],
    train_config: Dict[str, Any],
    sample_set: Dict[str, List[int]],
    *,
    train_portion: float = 1.0,
    ms_per_step: Optional[float] = None,
    gpu_name: Optional[str] = None,
    num_params: Optional[int] = None,
    loss_type: str = "ce",
) -> Dict[str, Any]:
    """Estimate training-phase wall-time in seconds.

    Computes ``total_steps × ms/step × k(gpu, model_type) × SAFETY_MULTIPLIER``
    — byte-identical to the pre-K.2.5 single-phase formula in
    ``evaluate_time_skill.wrapper.run_skill``.

    Args:
        ms_per_step:   Warmup-measured ms per fwd+bwd step. ``None`` → static
                       fallback (``num_params × seg × bs × 6e-10``), k=1.0.
        gpu_name:      CUDA device name (e.g. ``"NVIDIA RTX 5090"``). Only
                       consulted with the warmup path; static fallback keeps
                       k=1.0 regardless.
        num_params:    Exact parameter count. Needed only when ``ms_per_step``
                       is ``None`` (static fallback). If not provided, the
                       model is instantiated internally via ``_count_params``.
        loss_type:     Only used by the optional internal ``_count_params`` for
                       ``fcnet`` (which takes ``loss_type`` at construction).

    Returns:
        ``{"phase": "training", "seconds": float, "breakdown": {...}}``.
    """
    seg_size   = int(model_config.get("segmentation_size", 1000))
    batch_size = int(train_config.get("batch_size", 1))
    epochs     = int(train_config.get("epochs", 1))

    total_steps = _total_train_steps(
        sample_set, seg_size, batch_size, train_portion, epochs
    )

    if ms_per_step is not None and ms_per_step > 0:
        ms_source = "real_dataset_warmup"
        if gpu_name:
            cal_table = calibration.load_table(gpu_name)
            k = calibration.lookup_k(cal_table, model_type)
        else:
            k = 1.0
    else:
        if num_params is None:
            num_params = _count_params(model_type, model_config, loss_type)
        ms_per_step = _static_ms_per_step(num_params, seg_size, batch_size)
        ms_source = "static_formula_phase_b"
        k = 1.0

    total_ms = total_steps * ms_per_step * k * SAFETY_MULTIPLIER
    seconds = total_ms / 1000.0

    return {
        "phase":   "training",
        "seconds": seconds,
        "breakdown": {
            "total_train_steps":  total_steps,
            "ms_per_step":        round(ms_per_step, 4),
            "ms_source":          ms_source,
            "k_correction":       round(k, 4),
            "safety_multiplier":  SAFETY_MULTIPLIER,
            "gpu_name":           gpu_name,
        },
    }
