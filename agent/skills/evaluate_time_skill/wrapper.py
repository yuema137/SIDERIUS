"""
evaluate_time_skill/wrapper.py

Pre-flight wall-time estimator for a proposed training experiment.

Pipeline (once fully implemented, see docs/time_estimator_implement.md):
    1. Compute total step count from sample_set, seg_size, batch_size, epochs.
    2. Measure ms/step via a real-dataset GPU warmup (1 PSD x 3 fwd+bwd batches).
    3. Apply learned per-GPU correction factor k(gpu, model_type) via asymmetric EMA.
    4. Multiply by SAFETY_MULTIPLIER; compare against time_budget_minutes.

Phase A (current): skeleton only. run_skill returns a well-shaped dummy verdict so
downstream tuner wiring can be built against a stable contract. No step counting,
no warmup, no calibration yet.
"""

from __future__ import annotations

# Safety margin applied on top of (warmup_ms_per_step * k). Tight because the
# real-dataset warmup already captures DataLoader / HDF5 / GPU path; the
# multiplier only absorbs first-step autotune and minor variance.
SAFETY_MULTIPLIER: float = 1.1


def run_skill(sandbox, **kwargs) -> dict:
    """
    Phase A stub. Returns the output contract shape that later phases will fill in.

    Expected kwargs (see skill_config.json for the full schema):
        model_type (str), model_config (dict), train_config (dict),
        loss_config (dict), sample_set (dict), train_portion (float),
        time_budget_minutes (float), data_dir (str, optional).

    Returns:
        dict with keys: status, feasible, verdict, suggestion,
        estimated_minutes, limit_minutes, breakdown.
    """
    model_type = kwargs.get("model_type", "unknown")
    budget = float(kwargs.get("time_budget_minutes", 0.0))

    print(
        f"\n>>> [Skill: TimeEval] (phase A stub) model={model_type} "
        f"budget={budget} min — always reports feasible=True."
    )

    return {
        "status": "success",
        "feasible": True,
        "verdict": "STUB: Phase A skeleton; no real estimate computed.",
        "suggestion": "",
        "estimated_minutes": 0.0,
        "limit_minutes": budget,
        "breakdown": {
            "total_train_steps": 0,
            "ms_per_step_warmup": 0.0,
            "k_correction": 1.0,
            "safety_multiplier": SAFETY_MULTIPLIER,
            "train_minutes": 0.0,
        },
    }
