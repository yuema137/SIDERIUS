"""
evaluate_vram_skill/wrapper.py

Proactively estimates GPU VRAM usage for a proposed experiment config and
checks it against a per-mode operator budget (optional) combined with a
defensive 80% cap on currently available VRAM.

Call this BEFORE training to avoid OOM crashes.

Memory model (worst-case, float32 training):
  - Model weights:         num_params × 4 B
  - Gradients:             num_params × 4 B
  - Adam optimizer states: num_params × 8 B  (m + v)
  - Output logits:         batch × 256 × seg_size × 4 B
  - Activations (bwd):     ~2 × output_logits (rough conv/rnn estimate)
  - Focal one_hot:         batch × 256 × seg_size × 8 B  (int64, only for focal loss)
  - Transformer attention: batch × nhead × seg² × 4 B × num_layers  (transformer only)

Limit selection (Phase K):
  - vram_budget_gb is None  → limit = free_bytes × 0.8 (backward-compat floor).
                              The 4 GB minimum-free hard-error stays active.
  - vram_budget_gb is set   → limit = min(free_bytes × 0.8, budget_gb × GB).
                              The 4 GB minimum-free hard-error is skipped so a
                              contended GPU produces a feasibility verdict (and
                              a skipped_oom_risk record) instead of crashing
                              the tuning loop. A contention log is emitted when
                              the defensive cap drops below half the budget.

See docs/resource_estimator_implement.md §10.5 / §10.7.
"""

from typing import Optional

import torch
from pydantic import ValidationError
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


def _extract_schema_violations(exc: ValidationError) -> list[dict]:
    """Turn a pydantic ``ValidationError`` into a serializable list of
    per-field records.

    Each entry has:
      * ``loc``  — dotted path to the offending field (e.g. ``"context_stem_channels"``
        or ``"__root__"`` for ``@model_validator(mode='after')`` cross-field rules).
      * ``type`` — pydantic error type slug (``value_error``, ``multiple_of``,
        ``greater_than_equal`` …). Lets the tuner planner distinguish per-field
        bounds from cross-field invariants.
      * ``msg``  — human-readable error message.
      * ``input`` — the raw input value that pydantic rejected (``None`` when
        the error came from an ``@model_validator`` body, since the validator
        ran on the fully-built model rather than one input field).

    Phase D.4 — `docs/improving_validation_awareness.md`. See that doc for why
    we surface the structured entries rather than the raw error string: the
    tuner's next-attempt planner reads these back via the saved
    ``skipped_schema_violation`` record's ``memory.memory_update`` field.
    """
    violations: list[dict] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ())) or "__root__"
        violations.append({
            "loc":   loc,
            "type":  err.get("type", "unknown"),
            "msg":   err.get("msg", ""),
            "input": err.get("input"),
        })
    return violations


def _format_schema_violation_verdict(violations: list[dict]) -> str:
    """Short human-readable one-liner for the tuner's stdout + record.

    Truncated intentionally — the full structured list goes into the record's
    ``violations`` field. This string is only for the log line and the
    ``memory.conclusion`` narrative."""
    if not violations:
        return "Schema rejected config (no details)."
    parts = []
    for v in violations[:3]:  # first 3 is plenty for a log line
        parts.append(f"{v['loc']}={v.get('input')!r} ({v['type']})")
    extra = "" if len(violations) <= 3 else f" (+{len(violations) - 3} more)"
    return "Schema rejected config: " + "; ".join(parts) + extra


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
    Optional kwargs:
      * vram_budget_gb — operator-set per-mode VRAM ceiling (GB). When set,
        the limit becomes ``min(free × 0.80, budget × GB)`` and the 4 GB
        minimum-free floor is skipped (Phase K). See module docstring.
    Returns a result dict with status, feasibility verdict, and breakdown.
    """
    model_type     = kwargs.get("model_type", "fcnet")
    model_cfg      = kwargs.get("model_config", {})
    train_cfg      = kwargs.get("train_config", {})
    loss_cfg       = kwargs.get("loss_config", {})
    vram_budget_gb: Optional[float] = kwargs.get("vram_budget_gb")
    loss_type      = loss_cfg.get("loss_type", "ce")
    device         = train_cfg.get("device", "cpu")

    print(f"\n>>> [Skill: VRAMEval] Checking VRAM for {model_type.upper()} "
          f"(bs={train_cfg.get('batch_size')}, seg={model_cfg.get('segmentation_size')}, "
          f"loss={loss_type})...")

    try:
        # ── 1. Count params by instantiating the model ────────────────────
        # Phase D.4: a Pydantic ``ValidationError`` from the plugin's
        # ``PLUGIN_CONFIG_CLASS`` signals a tuner-proposed config that violated
        # either a per-field bound (``ge`` / ``le`` / ``multiple_of``) or a
        # cross-field ``@model_validator(mode='after')`` invariant. The tuner's
        # planner cannot see the latter class of rule through
        # ``model_json_schema()`` (it drops validator bodies). Surface a
        # structured ``schema_violation`` so the tuner can save a dedicated
        # ``skipped_schema_violation`` record instead of crashing with a
        # generic "Loop Error". See docs/improving_validation_awareness.md §D.4.
        try:
            num_params = _count_params(model_type, model_cfg, loss_type)
        except ValidationError as ve:
            violations = _extract_schema_violations(ve)
            verdict = _format_schema_violation_verdict(violations)
            print(f"    SCHEMA REJECT: {verdict}")
            return {
                "status":           "schema_violation",
                "violations":       violations,
                "offending_config": model_cfg,
                "message":          verdict,
                "verdict":          verdict,
                "suggestion": (
                    "Propose a config that satisfies the plugin's schema "
                    "invariants. DO NOT repeat the same field/value combination."
                ),
            }
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

        # Phase K: the 4 GB minimum-free floor is a backward-compat safety net
        # for the no-budget path. When a budget is set, a contended GPU should
        # produce a feasibility verdict (so the tuner saves a skipped_oom_risk
        # record and keeps planning) rather than crash the tuning loop — so the
        # floor is skipped here.
        _MIN_FREE = 4 * _GB
        if vram_budget_gb is None and free_bytes < _MIN_FREE:
            msg = (
                f"GPU has only {free_bytes / _GB:.2f} GB free "
                f"(total {total_vram / _GB:.1f} GB, {already_used / _GB:.2f} GB in use). "
                f"Minimum required free VRAM is 4 GB. "
                "Free up GPU memory before running experiments."
            )
            print(f"    ERROR: {msg}")
            return {"status": "error", "message": msg}

        defensive_limit = free_bytes * _SAFETY_PCT
        if vram_budget_gb is None:
            limit_bytes = defensive_limit
        else:
            budget_limit = vram_budget_gb * _GB
            limit_bytes  = min(defensive_limit, budget_limit)
            # Contention log: the defensive free-VRAM cap has pinched the
            # effective limit below half the operator's nominal budget — some
            # other process is holding VRAM. See
            # docs/resource_estimator_implement.md §10.5.
            if defensive_limit < budget_limit * 0.5:
                print(
                    f"    [VRAM] Contention detected: "
                    f"budget={vram_budget_gb:.2f} GB, "
                    f"free-VRAM cap={defensive_limit / _GB:.2f} GB; "
                    f"using {limit_bytes / _GB:.2f} GB"
                )
        feasible = total_est <= limit_bytes

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

        if vram_budget_gb is None:
            limit_desc = (
                f"Safety limit: {limit_bytes / _GB:.2f} GB "
                f"({int(_SAFETY_PCT*100)}% of free)."
            )
        else:
            limit_desc = (
                f"Limit: {limit_bytes / _GB:.2f} GB "
                f"(min of defensive {defensive_limit / _GB:.2f} GB "
                f"and budget {vram_budget_gb:.2f} GB)."
            )
        verdict = (
            f"{'✅ FITS' if feasible else '❌ OOM RISK'} — "
            f"Estimated {total_est / _GB:.2f} GB vs "
            f"{free_bytes / _GB:.2f} GB free ({total_vram / _GB:.1f} GB total, "
            f"{already_used / _GB:.2f} GB already used). "
            f"{limit_desc} "
            f"Bottleneck: {bottleneck}."
        )

        # Phase K: per-lever guidance lives in the planner prompt (§10.3,
        # single-channel rule), not inside the skill. The suggestion is now a
        # one-line verdict-style summary.
        suggestion = ""
        if not feasible:
            suggestion = (
                "Config exceeds the VRAM limit — reduce model complexity "
                "(depth, width, batch_size, or segmentation_size)."
            )

        print(f"    VRAM free   : {free_bytes / _GB:.2f} GB / {total_vram / _GB:.1f} GB")
        print(f"    Estimated   : {total_est / _GB:.2f} GB")
        print(f"    Feasible    : {'YES' if feasible else 'NO'}")
        if suggestion:
            print(f"    Suggestion  : {suggestion}")

        return {
            "status":         "success",
            "feasible":       feasible,
            "verdict":        verdict,
            "suggestion":     suggestion,
            "num_params":     num_params,
            "breakdown":      breakdown_gb,
            "vram_free_gb":   round(free_bytes  / _GB, 3),
            "vram_total_gb":  round(total_vram  / _GB, 1),
            "estimated_gb":   round(total_est   / _GB, 3),
            "limit_gb":       round(limit_bytes / _GB, 3),
            "vram_budget_gb": vram_budget_gb,
        }

    except Exception as e:
        import traceback
        msg = f"ResourceEval error: {e}\n{traceback.format_exc()}"
        print(f"!!! [ResourceEval] {msg}")
        return {"status": "error", "message": msg}
