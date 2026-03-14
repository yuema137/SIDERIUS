"""
evaluate_resource_skill/wrapper.py

Proactively estimates GPU VRAM usage for a proposed experiment config and
checks it against the 80% safety limit of currently available VRAM.

Call this BEFORE training to avoid OOM crashes.

Memory model (worst-case, float32 training):
  - Model weights:         num_params × 4 B
  - Gradients:             num_params × 4 B
  - Adam optimizer states: num_params × 8 B  (m + v)
  - Output logits:         batch × 256 × seg_size × 4 B
  - Activations (bwd):     ~2 × output_logits (rough conv/rnn estimate)
  - Focal one_hot:         batch × 256 × seg_size × 8 B  (int64, only for focal loss)
  - Transformer attention: batch × nhead × seg² × 4 B × num_layers  (transformer only)
"""

import sys
import os

import torch
from ml_models.models_sandbox import MODEL_REGISTRY
from ml_models.models_format_sandbox import get_config_class


# ── constants ────────────────────────────────────────────────────────────────
_BYTES_F32  = 4
_BYTES_I64  = 8
_SAFETY_PCT = 0.80          # block if estimated > 80 % of free VRAM
_GB         = 1024 ** 3


def _count_params(model_type: str, model_cfg: dict, loss_type: str) -> int:
    """Instantiate the model on CPU and return exact parameter count."""
    config_cls = get_config_class(model_type)
    config_obj = config_cls(**model_cfg)

    if model_type == "fcnet":
        model = MODEL_REGISTRY[model_type](config_obj, loss_type=loss_type)
    else:
        model = MODEL_REGISTRY[model_type](config_obj)

    return sum(p.numel() for p in model.parameters())


def _estimate_bytes(
    model_type: str,
    model_cfg: dict,
    train_cfg: dict,
    loss_cfg: dict,
    num_params: int,
) -> dict:
    """Return a breakdown dict with byte estimates for each memory component."""
    seg_size   = model_cfg.get("segmentation_size", 40000)
    batch_size = train_cfg.get("batch_size", 1)
    loss_type  = loss_cfg.get("loss_type", "ce")

    # --- fixed model overhead (weights + grads + Adam m + v) ---
    model_overhead = num_params * 16 * _BYTES_F32 // 4   # = num_params * 16 B

    # --- output logits: [B, 256, T] float32 ---
    output_logits = batch_size * 256 * seg_size * _BYTES_F32

    # --- activations stored for backward pass (rough estimate) ---
    # For conv/rnn models activations ≈ 2× output; for fcnet (linear) ≈ 1×
    act_factor = 1 if model_type == "fcnet" else 2
    activations = act_factor * output_logits

    # --- focal loss one_hot: [B, 256, T] int64 ---
    focal_onehot = batch_size * 256 * seg_size * _BYTES_I64 if loss_type == "focal" else 0

    # --- transformer self-attention: [B, nhead, T, T] float32 per layer ---
    transformer_attn = 0
    if model_type == "transformer":
        nhead      = model_cfg.get("nhead", 2)
        num_layers = model_cfg.get("num_layers", 2)
        transformer_attn = batch_size * nhead * seg_size * seg_size * _BYTES_F32 * num_layers

    total = model_overhead + output_logits + activations + focal_onehot + transformer_attn

    return {
        "model_overhead_bytes":    model_overhead,
        "output_logits_bytes":     output_logits,
        "activations_bytes":       activations,
        "focal_onehot_bytes":      focal_onehot,
        "transformer_attn_bytes":  transformer_attn,
        "total_bytes":             total,
    }


def run_skill(sandbox, **kwargs):
    """
    Required kwargs: model_type, model_config, train_config, loss_config
    Returns a result dict with status, feasibility verdict, and breakdown.
    """
    model_type = kwargs.get("model_type", "fcnet")
    model_cfg  = kwargs.get("model_config", {})
    train_cfg  = kwargs.get("train_config", {})
    loss_cfg   = kwargs.get("loss_config", {})
    loss_type  = loss_cfg.get("loss_type", "ce")
    device     = train_cfg.get("device", "cpu")

    print(f"\n>>> [Skill: ResourceEval] Checking VRAM for {model_type.upper()} "
          f"(bs={train_cfg.get('batch_size')}, seg={model_cfg.get('segmentation_size')}, "
          f"loss={loss_type})...")

    try:
        # ── 1. Count params by instantiating the model ────────────────────
        num_params = _count_params(model_type, model_cfg, loss_type)
        print(f"    Parameters  : {num_params:,}")

        # ── 2. Estimate memory breakdown ──────────────────────────────────
        breakdown = _estimate_bytes(model_type, model_cfg, train_cfg, loss_cfg, num_params)
        total_est = breakdown["total_bytes"]

        # ── 3. Query actual VRAM via nvidia interface ─────────────────────
        if device != "cuda":
            # CPU mode — no VRAM constraint
            print("    Device is CPU — skipping VRAM check.")
            return {
                "status": "success",
                "feasible": True,
                "verdict": "CPU mode — no VRAM constraint.",
                "breakdown": {k: f"{v / _GB:.3f} GB" for k, v in breakdown.items()},
                "num_params": num_params,
            }

        if not torch.cuda.is_available():
            msg = "CUDA requested (device='cuda') but no GPU is available on this machine."
            print(f"    ERROR: {msg}")
            return {"status": "error", "message": msg}

        free_bytes, total_vram = torch.cuda.mem_get_info(0)
        already_used = total_vram - free_bytes

        _MIN_FREE = 4 * _GB
        if free_bytes < _MIN_FREE:
            msg = (
                f"GPU has only {free_bytes / _GB:.2f} GB free "
                f"(total {total_vram / _GB:.1f} GB, {already_used / _GB:.2f} GB in use). "
                f"Minimum required free VRAM is 4 GB. "
                "Free up GPU memory before running experiments."
            )
            print(f"    ERROR: {msg}")
            return {"status": "error", "message": msg}

        limit_bytes = free_bytes * _SAFETY_PCT
        feasible    = total_est <= limit_bytes

        # ── 4. Build human-readable report ────────────────────────────────
        breakdown_gb = {k: f"{v / _GB:.3f} GB" for k, v in breakdown.items()}

        # Identify bottleneck (largest single component)
        components = {
            "focal_onehot":      breakdown["focal_onehot_bytes"],
            "transformer_attn":  breakdown["transformer_attn_bytes"],
            "activations":       breakdown["activations_bytes"],
            "output_logits":     breakdown["output_logits_bytes"],
            "model_overhead":    breakdown["model_overhead_bytes"],
        }
        bottleneck = max(components, key=components.get)

        verdict = (
            f"{'✅ FITS' if feasible else '❌ OOM RISK'} — "
            f"Estimated {total_est / _GB:.2f} GB vs "
            f"{free_bytes / _GB:.2f} GB free ({total_vram / _GB:.1f} GB total, "
            f"{already_used / _GB:.2f} GB already used). "
            f"Safety limit: {limit_bytes / _GB:.2f} GB ({int(_SAFETY_PCT*100)}%). "
            f"Bottleneck: {bottleneck}."
        )

        suggestion = ""
        if not feasible:
            # Suggest the most effective reduction
            if bottleneck in ("focal_onehot", "output_logits", "activations"):
                safe_bs = int(train_cfg.get("batch_size", 1) * limit_bytes / total_est * 0.9)
                safe_bs = max(1, safe_bs)
                suggestion = (
                    f"Reduce batch_size to ~{safe_bs} "
                    f"or reduce segmentation_size."
                )
            elif bottleneck == "transformer_attn":
                suggestion = (
                    "Reduce segmentation_size (attention scales O(T²)), "
                    "or reduce nhead/num_layers."
                )
            else:
                suggestion = "Reduce model size (embedding_dim, latent_dims, num_layers)."

        print(f"    VRAM free   : {free_bytes / _GB:.2f} GB / {total_vram / _GB:.1f} GB")
        print(f"    Estimated   : {total_est / _GB:.2f} GB")
        print(f"    Feasible    : {'YES' if feasible else 'NO'}")
        if suggestion:
            print(f"    Suggestion  : {suggestion}")

        return {
            "status":      "success",
            "feasible":    feasible,
            "verdict":     verdict,
            "suggestion":  suggestion,
            "num_params":  num_params,
            "breakdown":   breakdown_gb,
            "vram_free_gb":  round(free_bytes  / _GB, 3),
            "vram_total_gb": round(total_vram  / _GB, 1),
            "estimated_gb":  round(total_est   / _GB, 3),
            "limit_gb":      round(limit_bytes / _GB, 3),
        }

    except Exception as e:
        import traceback
        msg = f"ResourceEval error: {e}\n{traceback.format_exc()}"
        print(f"!!! [ResourceEval] {msg}")
        return {"status": "error", "message": msg}
