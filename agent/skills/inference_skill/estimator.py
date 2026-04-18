"""
agent/skills/inference_skill/estimator.py

Per-phase VRAM and wall-time estimator for the INFERENCE phase. Called
by the resource aggregators (K.2.5). Inference is a *dependent* phase:
same architecture, same ``model_config`` as training. The only
dedicated lever — ``inference_batch`` — is hard-coded in
``core/inference_defaults.py``, so the planner cannot move this phase
independently of the training-side config it already adjusted.

Key differences from training VRAM:
  * weights only (×4 B) — no grads, no Adam m/v.
  * activations ≈ 1× output logits (no backward storage).
  * no focal one_hot — loss is not computed at inference.
  * batch = ``inference_batch_for(model_type)`` (NOT ``train.batch_size``).

Key differences from training wall time:
  * total_steps = ``ceil(n_segments / inference_batch)``; no epochs,
    no train_portion (we run once over the eval set).
  * Phase F's ``k(gpu, model_type)`` correction is NOT applied —
    inference ms/step was never calibrated.
  * Static fallback: training-static formula scaled down by
    ``_INFERENCE_VS_TRAINING_RATIO`` to reflect "no backward pass".

Contract (K.2.5 Commit 3). Both entry points call
``assert_inference_batch_registered`` first: unregistered model types
(plugins without a batch entry) fail loudly here so the planning gate
cannot silently forecast against a guessed batch size. The executor
(``sandbox_executor.execute_inference``) keeps the silent fallback —
those two callers have asymmetric tolerance for being wrong, by
design. See ``core/inference_defaults.py`` docstring.

See docs/resource_estimator_implement.md §10.5 + §10.14 Commit 3.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from core.inference_defaults import (
    assert_inference_batch_registered,
    inference_batch_for,
)
from execute_tools.dataset_config import SEGMENT_LENGTH as PSD_SEGMENT_LENGTH


_BYTES_F32 = 4

# Inference has no backward pass; training ms/step includes bwd (~2×
# fwd) + optimizer step + loss overhead. 1/3 is the rough working ratio
# used by the static fallback and by the aggregator when it derives an
# inference ms/step from a training-warmup measurement.
_INFERENCE_VS_TRAINING_RATIO: float = 1.0 / 3.0

# Same 6e-10 ms/flop baseline as the training static formula. Scaled
# down by the training-vs-inference ratio below to approximate the
# missing backward pass.
_STATIC_MS_PER_FLOP: float = 6e-10


# ── VRAM ─────────────────────────────────────────────────────────────────────


def estimate_peak_bytes(
    model_type: str,
    model_config: Dict[str, Any],
    num_params: int,
) -> Dict[str, Any]:
    """Estimate peak inference-phase VRAM.

    Worst-case float32 inference memory:
      * weights:           ``num_params × 4 B`` (no grads / Adam)
      * output logits:     ``inf_batch × 256 × T × 4``
      * activations (fwd): ``1 × output_logits``  (no backward storage)
      * transformer attn:  ``inf_batch × nhead × T² × 4 × num_layers``

    Args:
        model_type:   Model architecture key.
        model_config: Model configuration dict (``segmentation_size``,
                      optional ``nhead`` / ``num_layers`` for transformer).
        num_params:   Exact parameter count from a prior CPU instantiation.

    Raises:
        ValueError: If ``model_type`` has no registered inference batch
            (via ``assert_inference_batch_registered``).

    Returns:
        ``{"phase": "inference", "total_bytes": int, "breakdown": {...}}``.
    """
    assert_inference_batch_registered(model_type)
    inf_batch = inference_batch_for(model_type)

    seg_size = model_config.get("segmentation_size", 40000)

    weights = num_params * _BYTES_F32
    output_logits = inf_batch * 256 * seg_size * _BYTES_F32
    activations = output_logits  # 1× at inference (no backward storage)

    transformer_attn = 0
    if model_type == "transformer":
        nhead      = model_config.get("nhead", 2)
        num_layers = model_config.get("num_layers", 2)
        transformer_attn = (
            inf_batch * nhead * seg_size * seg_size * _BYTES_F32 * num_layers
        )

    total = weights + output_logits + activations + transformer_attn

    return {
        "phase":       "inference",
        "total_bytes": total,
        "breakdown": {
            "weights_bytes":          weights,
            "output_logits_bytes":    output_logits,
            "activations_bytes":      activations,
            "transformer_attn_bytes": transformer_attn,
            "inference_batch":        inf_batch,
        },
    }


# ── Wall time ────────────────────────────────────────────────────────────────


def _total_inference_steps(
    sample_set: Dict[str, List[int]],
    seg_size: int,
    inf_batch: int,
) -> int:
    """Total forward-only step count to score the whole eval ``sample_set``."""
    n_psd = sum(len(v) for v in sample_set.values())
    ml_per_psd = PSD_SEGMENT_LENGTH // seg_size
    total_ml = n_psd * ml_per_psd
    return math.ceil(total_ml / max(inf_batch, 1))


def _static_inference_ms_per_step(
    num_params: int, seg_size: int, inf_batch: int,
) -> float:
    """Static ms/step fallback. Training-side formula scaled by the
    no-backward-pass ratio."""
    return (
        num_params * seg_size * inf_batch
        * _STATIC_MS_PER_FLOP * _INFERENCE_VS_TRAINING_RATIO
    )


def _count_params(model_type: str, model_config: dict) -> int:
    """Instantiate the model on CPU. Module-level for monkeypatching."""
    from ml_models.models_sandbox import MODEL_REGISTRY
    from ml_models.models_format_sandbox import get_config_class

    config_cls = get_config_class(model_type)
    config_obj = config_cls(**model_config)
    if model_type == "fcnet":
        # fcnet takes loss_type at construction; num_params is invariant
        # under the choice for a parameter count, so pass a safe default.
        model = MODEL_REGISTRY[model_type](config_obj, loss_type="ce")
    else:
        model = MODEL_REGISTRY[model_type](config_obj)
    return sum(p.numel() for p in model.parameters())


def estimate_wall_time_seconds(
    model_type: str,
    model_config: Dict[str, Any],
    sample_set: Dict[str, List[int]],
    *,
    inference_ms_per_step: Optional[float] = None,
    num_params: Optional[int] = None,
) -> Dict[str, Any]:
    """Estimate inference wall-time in seconds.

    ``total_steps × inference_ms_per_step / 1000``. Phase F's
    ``k(gpu, model_type)`` is NOT applied — inference ms/step wasn't
    calibrated.

    Args:
        inference_ms_per_step: ms per forward-only step. The aggregator
            is expected to pass ``training_ms_per_step × 1/3`` when it
            has a warmup measurement. ``None`` → internal static fallback.
        num_params: Only needed by the static fallback. If absent, the
            model is instantiated internally via ``_count_params``.

    Raises:
        ValueError: If ``model_type`` has no registered inference batch.

    Returns:
        ``{"phase": "inference", "seconds": float, "breakdown": {...}}``.
    """
    assert_inference_batch_registered(model_type)
    inf_batch = inference_batch_for(model_type)

    seg_size = int(model_config.get("segmentation_size", 1000))

    total_steps = _total_inference_steps(sample_set, seg_size, inf_batch)

    if inference_ms_per_step is not None and inference_ms_per_step > 0:
        ms_per_step = inference_ms_per_step
        ms_source = "derived_from_training_warmup"
    else:
        if num_params is None:
            num_params = _count_params(model_type, model_config)
        ms_per_step = _static_inference_ms_per_step(num_params, seg_size, inf_batch)
        ms_source = "static_formula"

    seconds = total_steps * ms_per_step / 1000.0

    return {
        "phase":   "inference",
        "seconds": seconds,
        "breakdown": {
            "total_inference_steps": total_steps,
            "inference_batch":       inf_batch,
            "ms_per_step":           round(ms_per_step, 6),
            "ms_source":             ms_source,
        },
    }
