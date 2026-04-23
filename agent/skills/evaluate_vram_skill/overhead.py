"""Operational footprint model — Phase 6.6 §3.3 (Hybrid Design).

Decomposes the VRAM overhead beyond the structural probe (§3.2) into two
categories with different epistemic footings:

1. **Weight-proportional (analytical).** Gradients and optimizer state scale
   exactly with ``params_bytes``, via dtype arithmetic and the optimizer's
   algorithmic definition. No measurement needed; no hardware dependence.

2. **Fixed residuals (calibrated).** The per-process CUDA context, cuDNN
   forward workspace, and cuDNN backward-algorithm scratch are properties
   of the driver + cuDNN build and are empirically stable across re-runs
   on the same host. A one-time calibration pass (Appendix A.5) pins them.

Calibration origin (Appendix A.5)
----------------------------------
Captured 2026-04-23 on ligroup (lilab RTX 5090), torch 2.10.0+cu128, CUDA
12.8, replaying Stage 2 iter_001 attempt_003 ``dynamic_depth_simple``:

- ``_CUDA_CONTEXT_BYTES = 185 MB``. This closes the inference residual
  (anchor 431.3 MB − probe prediction 246.2 MB = 185.0 MB). Appears in
  BOTH training and inference phases — it is the per-process context
  footprint plus cuDNN forward workspace.

- ``_CUDNN_BACKWARD_WORKSPACE_BYTES = 50 MB``. This closes the training-
  minus-inference residual (anchor delta 411.5 MB − probe-predicted delta
  360.8 MB = 50.7 MB, rounded to 50). Appears in training phase ONLY —
  autograd's backward pass is what triggers the allocation.

Refresh policy
--------------
If the driver stack moves enough to invalidate the numbers (e.g. a major
cuDNN upgrade), re-run ``docs/phase66_telemetry/reconcile_probe_vs_anchors.py``
on the new stack and update both constants in a single commit. Do NOT fold
new allocation classes (DDP buckets, activation checkpointing) into an
existing constant — add a new named term instead, so attribution stays
traceable.

Principle 2 invariant
---------------------
This module reads no model-type strings and contains no architecture names.
It operates on bytes and optimizer identifiers only. The guardrail test
``tests/unit/guardrails/test_no_model_name_branches.py`` (A.12) enforces this.
"""
from __future__ import annotations

from typing import Literal, Optional

# ── Calibrated constants (Appendix A.5, RTX 5090 / torch 2.10.0+cu128) ──────

_CUDA_CONTEXT_BYTES:             int = 185 * 1024 ** 2   # 185 MB — both phases
_CUDNN_BACKWARD_WORKSPACE_BYTES: int = 50  * 1024 ** 2   # 50  MB — training only

# ── Analytical multipliers (optimizer algebra, no measurement) ──────────────

_OPTIMIZER_STATE_MULTIPLIER: dict[str, int] = {
    "adam":  2,   # first + second moment
    "adamw": 2,   # first + second moment (decoupled weight decay, same state)
    "sgd":   0,   # plain SGD has no momentum state
    # Add "sgd+momentum": 1 when the project actually uses it. Do not
    # speculate — a silently-wrong multiplier is worse than a hard error.
}


# ── Weight-proportional (analytical) ────────────────────────────────────────

def training_overhead_bytes(params_bytes: int, optimizer: str) -> int:
    """Grads + optimizer state. Both scale exactly with ``params_bytes``.

    Breakdown:
      grads = 1 × params_bytes   (same dtype as the parameters)
      opt   = k × params_bytes   (k from ``_OPTIMIZER_STATE_MULTIPLIER``)

    Args:
        params_bytes: Total bytes held by model parameters (from the
            structural probe's ``total_param_bytes``).
        optimizer:    Optimizer identifier. Case-insensitive. Must be a key
            of ``_OPTIMIZER_STATE_MULTIPLIER`` — unknown values raise
            ``ValueError`` rather than silently falling back.

    Returns:
        grads + optimizer state, in bytes.

    Raises:
        ValueError: on an unknown optimizer identifier. No guessing — the
            deterministic design refuses silent fallbacks.
    """
    key = optimizer.lower() if isinstance(optimizer, str) else optimizer
    if key not in _OPTIMIZER_STATE_MULTIPLIER:
        raise ValueError(
            f"Unknown optimizer: {optimizer!r}. Known optimizers: "
            f"{sorted(_OPTIMIZER_STATE_MULTIPLIER)}. Add an explicit entry "
            f"to _OPTIMIZER_STATE_MULTIPLIER rather than guessing."
        )
    grad_bytes = params_bytes
    opt_bytes  = _OPTIMIZER_STATE_MULTIPLIER[key] * params_bytes
    return grad_bytes + opt_bytes


# ── Fixed residuals (calibrated) ────────────────────────────────────────────

def cuda_context_bytes() -> int:
    """Per-process CUDA context + cuDNN forward workspace.

    Appears in BOTH training and inference phases — loading the CUDA driver
    into a process costs this up-front, regardless of whether autograd is on.
    """
    return _CUDA_CONTEXT_BYTES


def cudnn_backward_workspace_bytes() -> int:
    """cuDNN backward-algorithm scratch.

    Training phase ONLY. Inference runs under ``torch.no_grad()`` and never
    allocates this buffer — which is why the anchor delta in Appendix A.5
    exists in the first place.
    """
    return _CUDNN_BACKWARD_WORKSPACE_BYTES


# ── Composer: per-phase total overhead (convenience for the estimators) ────

def phase_overhead_bytes(
    params_bytes: int,
    mode: Literal["training", "inference"],
    optimizer: Optional[str] = None,
) -> int:
    """Sum the right overhead terms for the given phase.

    - ``inference``: ``cuda_context_bytes()``. Optimizer is ignored (and
      should be ``None``) — inference does not allocate grads or optimizer
      state.
    - ``training``: ``training_overhead_bytes(params_bytes, optimizer) +
      cuda_context_bytes() + cudnn_backward_workspace_bytes()``. Optimizer
      is REQUIRED — passing ``None`` raises ``ValueError`` because the
      training peak is not defined without it.

    This composer exists so ``training_skill/estimator.py`` (A.6) and
    ``inference_skill/estimator.py`` (A.7) can ask one question instead of
    summing primitives — and so the "what's in overhead per phase" answer
    lives in exactly one place.

    Raises:
        ValueError: mode=="training" with optimizer=None, or unknown mode,
            or unknown optimizer (propagated from ``training_overhead_bytes``).
    """
    if mode == "inference":
        return cuda_context_bytes()

    if mode == "training":
        if optimizer is None:
            raise ValueError(
                "training mode requires an optimizer identifier — the "
                "training peak is not defined without grads + optimizer state."
            )
        return (
            training_overhead_bytes(params_bytes, optimizer)
            + cuda_context_bytes()
            + cudnn_backward_workspace_bytes()
        )

    raise ValueError(
        f"Unknown mode: {mode!r}. Expected 'training' or 'inference'."
    )
