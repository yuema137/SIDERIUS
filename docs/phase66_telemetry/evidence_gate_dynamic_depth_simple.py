"""
Phase 6.6 A.14 — Evidence Gate for the deterministic VRAM estimator.

Compares the new ``evaluate_vram_skill`` predictions against the ground-truth
telemetry captured by ``capture_stage2_vram_telemetry.py`` (Stage 2 iter_001
attempt_003, ``dynamic_depth_simple``). Per §5.2 of the design doc, the gate
fails if any per-phase prediction diverges by more than ±10% from the measured
peak.

Two comparisons per phase so the result isolates *formula accuracy* from
*batch-selection policy*:

  • **Skill-path prediction**   — full ``run_skill`` invocation, honouring
    whatever batch the resolver picks. Records what the tuner would actually
    see at runtime.
  • **Apples-to-apples probe**  — direct primitives call at the exact batch
    the telemetry capture used (training B=8, inference B=25). This is the
    number we compare against the measured peak — the only fair check of
    composition fidelity.

Usage (from repo root, on a GPU host — lilab or SDSC):
    .venv/bin/python docs/phase66_telemetry/evidence_gate_dynamic_depth_simple.py

Output: JSON payload + rendered Appendix A.2 row to stdout. Also writes
``docs/phase66_telemetry/evidence_gate_result.json`` for the doc-sync step.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "ml_models"))

# Point the plugin loader at the live Stage 2 attempt_003 plugin dir BEFORE
# importing anything that walks MODEL_REGISTRY. plugin_loader's env-var scan
# runs on import when the registry is first extended.
_PLUGIN_DIR = (
    "/tmp/pytest-of-yuema137/pytest-811/test_two_iterations_under_budg0/"
    "stage2_smoke/stage2_iter_001/iteration_001/attempt_003_dynamic_depth_simple/"
    "models"
)
os.environ["SIDERIUS_PLUGIN_DIRS"] = _PLUGIN_DIR

import torch  # noqa: E402

from ml_models.loss_models_sandbox    import get_criterion  # noqa: E402
from ml_models.models_format_sandbox  import LossConfig, PLUGIN_CONFIG_REGISTRY  # noqa: E402
from ml_models.models_sandbox         import MODEL_REGISTRY  # noqa: E402
from ml_models.plugin_loader          import extend_registries  # noqa: E402

# Force plugin registration — ``evaluate_vram_skill`` reads MODEL_REGISTRY
# directly, so the plugin must already be loaded before we call run_skill.
_loaded = extend_registries(MODEL_REGISTRY, PLUGIN_CONFIG_REGISTRY)
assert "dynamic_depth_simple" in _loaded, (
    f"Expected dynamic_depth_simple plugin to load from {_PLUGIN_DIR}; "
    f"loaded={_loaded}"
)

from agent.skills.evaluate_vram_skill.wrapper import (  # noqa: E402
    _build_model,
    _compose_inference_peak,
    _compose_training_peak,
    run_skill,
)
from agent.skills.evaluate_vram_skill.structural_probe import (  # noqa: E402
    probe_activation_footprint,
)
from core.hardware_context import discover  # noqa: E402


# ── Telemetry to compare against (from stage2_iter_001_telemetry.json) ──────

MEASURED = {
    "training": {
        "batch_size":           8,
        "segmentation_size":    10000,
        "peak_allocated_bytes": 883_782_656,
        "peak_allocated_gb":    0.8231,
    },
    "inference": {
        "inference_batch":      25,
        "segmentation_size":    10000,
        "peak_allocated_bytes": 452_210_176,
        "peak_allocated_gb":    0.4212,
    },
}

# Configs: verbatim copies of what the live Stage 2 run used. Kept in sync
# with capture_stage2_vram_telemetry.py on purpose — diverging them would
# invalidate the apples-to-apples comparison.
MODEL_CONFIG = {
    "model_type":         "dynamic_depth_simple",
    "segmentation_size":  10000,
    "batch_size":         8,
    "input_channels":     16,
    "residual_channels":  32,
    "gate_channels":      64,
    "kernel_size":        5,
    "skip_channels":      32,
    "embed_dim":          64,
    "num_blocks":         2,
}
TRAIN_CONFIG = {
    "lr":             0.0003,
    "epochs":         1,
    "batch_size":     8,
    "optimizer_type": "adamw",  # overhead primitive normalises adamw → adam
    "weight_decay":   1e-05,
    "device":         "cuda",
}
LOSS_CONFIG = {
    "loss_type":         "focal",
    "alpha":             0.25,
    "gamma":             2.0,
    "beta":              None,
    "reduction":         "mean",
    "use_class_weights": False,
}


_GB = 1024 ** 3


# ── Apples-to-apples probes at the measured batch sizes ──────────────────────

def _apples_training_peak() -> tuple[int, dict]:
    """Compose the training peak at the exact (B=8, T=10000) the telemetry
    capture used. Bypasses the resolver — the resolver picks its own batch."""
    model = _build_model("dynamic_depth_simple", MODEL_CONFIG, "focal")
    loss_module = get_criterion(LossConfig(**LOSS_CONFIG))
    B, T = MEASURED["training"]["batch_size"], MEASURED["training"]["segmentation_size"]
    inp = torch.zeros((B, T), dtype=torch.long)
    # Focal loss uses CE-family target shape (class indices).
    tgt = torch.zeros((B, T), dtype=torch.long)
    probe = probe_activation_footprint(
        model=model, loss_module=loss_module,
        input_sample=inp, target_sample=tgt,
        mode="training",
    )
    # adamw normalises to adam in overhead.training_overhead_bytes — the
    # scaling factor is the same (3 × P: grads + optimizer 1st + 2nd moment).
    peak, breakdown = _compose_training_peak(probe, optimizer="adam")
    return peak, breakdown


def _apples_inference_peak() -> tuple[int, dict]:
    """Compose the inference peak at the legacy B=25 used by the telemetry.
    The new resolver will pick a larger batch on a 5090 — that's validated
    separately via the full skill-path invocation."""
    model = _build_model("dynamic_depth_simple", MODEL_CONFIG, "focal")
    B = MEASURED["inference"]["inference_batch"]
    T = MEASURED["inference"]["segmentation_size"]
    inp = torch.zeros((B, T), dtype=torch.long)
    probe = probe_activation_footprint(
        model=model, loss_module=None,
        input_sample=inp, target_sample=None,
        mode="inference",
    )
    peak, breakdown = _compose_inference_peak(probe)
    return peak, breakdown


# ── Skill-path invocation (records what the tuner will see at runtime) ──────

def _skill_path_result() -> dict:
    ctx = discover()
    return run_skill(
        sandbox=None,
        model_type="dynamic_depth_simple",
        model_config=MODEL_CONFIG,
        train_config=TRAIN_CONFIG,
        loss_config=LOSS_CONFIG,
        hardware_context=ctx,
    )


# ── Tolerance check + pretty output ──────────────────────────────────────────

def _delta(predicted: int, measured: int) -> tuple[float, bool]:
    """Return (signed relative delta, within-±10%)."""
    rel = (predicted - measured) / measured
    return rel, abs(rel) <= 0.10


def main() -> None:
    train_peak, train_bd = _apples_training_peak()
    inf_peak,   inf_bd   = _apples_inference_peak()
    skill_result         = _skill_path_result()

    train_delta, train_ok = _delta(train_peak, MEASURED["training"]["peak_allocated_bytes"])
    inf_delta,   inf_ok   = _delta(inf_peak,   MEASURED["inference"]["peak_allocated_bytes"])
    gate_pass = train_ok and inf_ok

    payload = {
        "phases": {
            "training": {
                "batch_size":           MEASURED["training"]["batch_size"],
                "segmentation_size":    MEASURED["training"]["segmentation_size"],
                "measured_peak_bytes":  MEASURED["training"]["peak_allocated_bytes"],
                "measured_peak_gb":     MEASURED["training"]["peak_allocated_gb"],
                "predicted_peak_bytes": train_peak,
                "predicted_peak_gb":    round(train_peak / _GB, 4),
                "relative_delta":       round(train_delta, 4),
                "within_10pct":         train_ok,
                "breakdown":            train_bd,
            },
            "inference": {
                "inference_batch":      MEASURED["inference"]["inference_batch"],
                "segmentation_size":    MEASURED["inference"]["segmentation_size"],
                "measured_peak_bytes":  MEASURED["inference"]["peak_allocated_bytes"],
                "measured_peak_gb":     MEASURED["inference"]["peak_allocated_gb"],
                "predicted_peak_bytes": inf_peak,
                "predicted_peak_gb":    round(inf_peak / _GB, 4),
                "relative_delta":       round(inf_delta, 4),
                "within_10pct":         inf_ok,
                "breakdown":            inf_bd,
            },
        },
        "gate_pass": gate_pass,
        "skill_path_snapshot": {
            "status":          skill_result.get("status"),
            "feasible":        skill_result.get("feasible"),
            "estimated_gb":    skill_result.get("estimated_gb"),
            "dominant_phase":  skill_result.get("dominant_phase"),
            "inference_batch": skill_result.get("inference_batch"),
            "phase_breakdown": {
                k: {"total_bytes": v["total_bytes"]}
                for k, v in (skill_result.get("phase_breakdown") or {}).items()
            },
        },
    }

    print("\n" + "=" * 72)
    print("PHASE 6.6 A.14 — EVIDENCE GATE (dynamic_depth_simple, Stage 2 iter_001)")
    print("=" * 72)

    def _row(name: str, measured: float, predicted: float, delta: float, ok: bool) -> str:
        flag = "PASS" if ok else "FAIL"
        return (
            f"  {name:<10} | measured {measured:.4f} GB | predicted {predicted:.4f} GB "
            f"| Δ {delta:+.2%} | {flag}"
        )

    print(_row(
        "training",
        MEASURED["training"]["peak_allocated_gb"],
        train_peak / _GB, train_delta, train_ok,
    ))
    print(_row(
        "inference",
        MEASURED["inference"]["peak_allocated_gb"],
        inf_peak / _GB, inf_delta, inf_ok,
    ))
    print(f"\n  Gate: {'PASS' if gate_pass else 'FAIL'} (tolerance ±10%)")
    print(f"\n  Skill-path snapshot: estimated_gb={skill_result.get('estimated_gb')}, "
          f"dominant={skill_result.get('dominant_phase')}, "
          f"inference_batch={skill_result.get('inference_batch')}")
    print("=" * 72 + "\n")

    out_path = _REPO_ROOT / "docs" / "phase66_telemetry" / "evidence_gate_result.json"
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Wrote: {out_path}\n")


if __name__ == "__main__":
    main()
