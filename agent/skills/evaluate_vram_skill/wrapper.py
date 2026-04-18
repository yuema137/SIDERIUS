"""
evaluate_vram_skill/wrapper.py

Peak-VRAM aggregator over the three execution phases. Estimates the
worst-case GPU VRAM ceiling a proposed experiment will hit and checks it
against a per-mode operator budget (optional) combined with a defensive
80% cap on currently available VRAM.

Call this BEFORE training to avoid OOM crashes.

Aggregation (K.2.5):
  The three phases — training, inference, scoring — run in *isolated
  subprocesses* via ``core.sandbox_executor.execute_*``, so each phase
  gets the whole GPU to itself. The binding constraint is the single
  phase with the highest peak, not a sum. This wrapper calls the three
  per-phase estimators and takes the max:

      training_skill/estimator.py:estimate_peak_bytes
      inference_skill/estimator.py:estimate_peak_bytes
      denoising_score_skill/estimator.py:estimate_peak_bytes   (= 0)

  Per-phase VRAM formulae live next to the code that actually allocates
  the tensors in each phase — see each estimator's docstring. This
  wrapper only picks the peak.

Limit selection (Phase K):
  - vram_budget_gb is None  → limit = free_bytes × 0.8 (backward-compat floor).
                              The 4 GB minimum-free hard-error stays active.
  - vram_budget_gb is set   → limit = min(free_bytes × 0.8, budget_gb × GB).
                              The 4 GB minimum-free hard-error is skipped so a
                              contended GPU produces a feasibility verdict (and
                              a skipped_oom_risk record) instead of crashing
                              the tuning loop. A contention log is emitted when
                              the defensive cap drops below half the budget.

See docs/resource_estimator_implement.md §10.5 / §10.7 / §10.14 Commit 5.
"""

from typing import Optional

import torch
from pydantic import ValidationError
from ml_models.models_sandbox import MODEL_REGISTRY
from ml_models.models_format_sandbox import get_config_class

from agent.skills.training_skill        import estimator as _training_est
from agent.skills.inference_skill       import estimator as _inference_est
from agent.skills.denoising_score_skill import estimator as _scoring_est


# ── constants ────────────────────────────────────────────────────────────────
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

        # ── 2. Peak-VRAM aggregation over the 3 phases ────────────────────
        # Phases run in isolated subprocesses via sandbox_executor, so the
        # binding constraint is the single phase with the highest peak,
        # not a sum. See §10.5.
        training_phase  = _training_est.estimate_peak_bytes(
            model_type, model_cfg, train_cfg, loss_cfg, num_params,
        )
        inference_phase = _inference_est.estimate_peak_bytes(
            model_type, model_cfg, num_params,
        )
        scoring_phase   = _scoring_est.estimate_peak_bytes()
        phases          = [training_phase, inference_phase, scoring_phase]
        dominant        = max(phases, key=lambda p: p["total_bytes"])
        total_est       = dominant["total_bytes"]
        phase_breakdown = {p["phase"]: p for p in phases}

        # ── 3. Query actual VRAM via nvidia interface ─────────────────────
        if device != "cuda":
            # CPU mode — no VRAM constraint
            print("    Device is CPU — skipping VRAM check.")
            return {
                "status":          "success",
                "feasible":        True,
                "verdict":         "CPU mode — no VRAM constraint.",
                "num_params":      num_params,
                "dominant_phase":  dominant["phase"],
                "phase_breakdown": phase_breakdown,
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
            f"Dominant phase: {dominant['phase']}."
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
            "status":          "success",
            "feasible":        feasible,
            "verdict":         verdict,
            "suggestion":      suggestion,
            "num_params":      num_params,
            "dominant_phase":  dominant["phase"],
            "phase_breakdown": phase_breakdown,
            "vram_free_gb":    round(free_bytes  / _GB, 3),
            "vram_total_gb":   round(total_vram  / _GB, 1),
            "estimated_gb":    round(total_est   / _GB, 3),
            "limit_gb":        round(limit_bytes / _GB, 3),
            "vram_budget_gb":  vram_budget_gb,
        }

    except Exception as e:
        import traceback
        msg = f"ResourceEval error: {e}\n{traceback.format_exc()}"
        print(f"!!! [ResourceEval] {msg}")
        return {"status": "error", "message": msg}
