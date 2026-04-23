"""Phase 6.6 A.2 — Reconciliation: structural_probe predictions vs. A.13 anchors.

Runs `probe_activation_footprint` on the exact Stage 2 iter_001 attempt_003
config under both `training` and `inference` modes, compares the predicted
activation bytes against the `max_memory_allocated` anchors captured by
`capture_stage2_vram_telemetry.py`, and prints a reconciliation table
identifying the residual gap that `overhead.py` (A.3) must close.

Success criterion (set by the user):
  - Training mode: the autograd-tape walker should close the ~400 MB
    delta between inference peak and training peak. If it does not, the
    `saved_tensors_hooks` approach is broken.
  - Inference mode: `input_bytes + model_output_bytes` should land within
    a small residual of the 0.42 GB anchor. The residual is the CUDA
    context + allocator overhead — A.3's territory.

Usage (from repo root):
    .venv/bin/python docs/phase66_telemetry/reconcile_probe_vs_anchors.py
        [--device cuda | cuda:0 | 0]
        [--anchor-path docs/phase66_telemetry/stage2_iter_001_telemetry.json]

Intended to be run after A.1 (torchinfo installed) and A.2 (structural_probe
implemented). Zero production-code blast radius — purely a measurement
reconciliation artefact.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "ml_models"))

import torch
import torch.nn as nn

from agent.skills.evaluate_vram_skill.structural_probe import (
    probe_activation_footprint,
)
from ml_models.loss_models_sandbox import FocalLoss1D
from ml_models.models_format_sandbox import LossConfig


# ── Stage 2 iter_001 attempt_003 configs (inlined, same as telemetry) ─────

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
TRAIN_CONFIG = {"batch_size": 8}
LOSS_CONFIG = {
    "loss_type":         "focal",
    "alpha":             0.25,
    "gamma":             2.0,
    "beta":              None,
    "reduction":         "mean",
    "use_class_weights": False,
}
INFERENCE_BATCH = 25


class DynamicDepthSimple(nn.Module):
    """Stage 2 iter_001 attempt_003 plugin, verbatim."""
    def __init__(self, cfg: dict):
        super().__init__()
        self.embedding = nn.Embedding(256, cfg["embed_dim"])
        self.causal_conv = nn.Conv1d(
            cfg["embed_dim"], cfg["gate_channels"],
            cfg["kernel_size"], padding=cfg["kernel_size"] // 2,
        )
        self.skip_conv = nn.Conv1d(
            cfg["gate_channels"] // 2, cfg["skip_channels"], 1,
        )
        self.output_conv = nn.Conv1d(cfg["skip_channels"], 256, 1)
        self.gate_channels = cfg["gate_channels"]

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        embedded = self.embedding(x).transpose(1, 2)
        h = self.causal_conv(embedded)
        f = h[:, : self.gate_channels // 2]
        g = h[:, self.gate_channels // 2 :]
        z = torch.tanh(f) * torch.sigmoid(g)
        skip = self.skip_conv(z)
        return self.output_conv(skip)


# ── Reconciliation ──────────────────────────────────────────────────────────

def _mb(bytes_: int) -> str:
    return f"{bytes_ / (1024 ** 2):.1f} MB"


def _gb(bytes_: int) -> str:
    return f"{bytes_ / (1024 ** 3):.4f} GB"


def _pct(delta: int, anchor: int) -> str:
    if anchor == 0:
        return "—"
    return f"{100 * delta / anchor:+.1f}%"


def reconcile(device: str, anchor_path: Path) -> dict:
    anchors = json.loads(anchor_path.read_text())
    train_anchor_bytes = anchors["phases"]["training"]["peak_allocated_bytes"]
    infer_anchor_bytes = anchors["phases"]["inference"]["peak_allocated_bytes"]

    # ── Training mode ───────────────────────────────────────────────────────
    model_tr = DynamicDepthSimple(MODEL_CONFIG)
    loss_tr = FocalLoss1D(LossConfig(**LOSS_CONFIG))
    B = TRAIN_CONFIG["batch_size"]
    T = MODEL_CONFIG["segmentation_size"]
    x_tr = torch.randint(0, 256, (B, T), dtype=torch.long)
    y_tr = torch.randint(0, 256, (B, T), dtype=torch.long)

    tr = probe_activation_footprint(
        model=model_tr, loss_module=loss_tr,
        input_sample=x_tr, target_sample=y_tr,
        mode="training", device=device,
    )

    # Probe's contribution to training-phase VRAM:
    #   autograd_tape_bytes: every intermediate the backward will retain
    #   input_bytes + output_bytes: live non-saved tensors at the peak
    #   total_param_bytes: weights (small)
    probe_tr_bytes = (
        tr.autograd_tape.total_saved_bytes
        + tr.input_bytes
        + tr.output_bytes
        + tr.model_forward.total_param_bytes
    )
    train_residual = train_anchor_bytes - probe_tr_bytes

    # ── Inference mode ──────────────────────────────────────────────────────
    model_inf = DynamicDepthSimple(MODEL_CONFIG)
    x_inf = torch.randint(0, 256, (INFERENCE_BATCH, T), dtype=torch.long)

    inf = probe_activation_footprint(
        model=model_inf, loss_module=None,
        input_sample=x_inf, target_sample=None,
        mode="inference", device=device,
    )

    # Inference: no autograd tape. Peak ≈ final output (the largest tensor)
    # + input (alive until return) + params. For sequential models ending in
    # their biggest layer, `output_bytes == forward_output_bytes_max`, so
    # using both double-counts. We take the larger; any pre-output
    # intermediate is much smaller in the Stage 2 config and is folded into
    # the overhead residual that A.3 will close.
    inf_peak_activation = max(
        inf.output_bytes, inf.model_forward.forward_output_bytes_max
    )
    probe_inf_bytes = (
        inf.input_bytes
        + inf_peak_activation
        + inf.model_forward.total_param_bytes
    )
    infer_residual = infer_anchor_bytes - probe_inf_bytes

    # ── Report ─────────────────────────────────────────────────────────────
    print()
    print("=" * 78)
    print(" Phase 6.6 A.2 — Probe vs. A.13 ground-truth reconciliation")
    print("=" * 78)
    print(f"Device: {torch.cuda.get_device_name() if torch.cuda.is_available() else 'cpu'}")
    print(f"Host:   {socket.gethostname()}")
    print(f"Anchor: {anchor_path}")
    print()

    print("── TRAINING MODE ─────────────────────────────────────────────────")
    print(f"  autograd_tape.total_saved_bytes : {_mb(tr.autograd_tape.total_saved_bytes):>10s}")
    print(f"  input_bytes                     : {_mb(tr.input_bytes):>10s}")
    print(f"  output_bytes (logits)           : {_mb(tr.output_bytes):>10s}")
    print(f"  total_param_bytes               : {_mb(tr.model_forward.total_param_bytes):>10s}")
    print(f"  -------------------------------- ")
    print(f"  probe_predicted_bytes           : {_mb(probe_tr_bytes):>10s}  ({_gb(probe_tr_bytes)})")
    print(f"  anchor_bytes (A.13)             : {_mb(train_anchor_bytes):>10s}  ({_gb(train_anchor_bytes)})")
    print(f"  residual for A.3                : {_mb(train_residual):>10s}  ({_pct(train_residual, train_anchor_bytes)})")

    print()
    print("── INFERENCE MODE ────────────────────────────────────────────────")
    print(f"  peak_activation = max(max_out, out): {_mb(inf_peak_activation):>10s}")
    print(f"    (output_bytes={_mb(inf.output_bytes)}, ")
    print(f"     max_layer_output={_mb(inf.model_forward.forward_output_bytes_max)})")
    print(f"  input_bytes                     : {_mb(inf.input_bytes):>10s}")
    print(f"  total_param_bytes               : {_mb(inf.model_forward.total_param_bytes):>10s}")
    print(f"  -------------------------------- ")
    print(f"  probe_predicted_bytes           : {_mb(probe_inf_bytes):>10s}  ({_gb(probe_inf_bytes)})")
    print(f"  anchor_bytes (A.13)             : {_mb(infer_anchor_bytes):>10s}  ({_gb(infer_anchor_bytes)})")
    print(f"  residual for A.3                : {_mb(infer_residual):>10s}  ({_pct(infer_residual, infer_anchor_bytes)})")

    print()
    print("── LOSS ATTRIBUTION (torchinfo, for Memory Killer report) ─────────")
    if tr.loss_forward is not None:
        for li in tr.loss_forward.layers:
            if li.is_leaf:
                print(f"    {li.var_name or li.class_name:20s}  out={li.output_shape}  "
                      f"{_mb(li.output_bytes)}")
        print(f"  loss.forward_output_bytes_sum   : {_mb(tr.loss_forward.forward_output_bytes_sum):>10s}")
        print(f"    (note: torchinfo only sees submodules — FocalLoss1D has none,")
        print(f"     so forward_output_bytes_sum is the scalar loss output. The")
        print(f"     400 MB delta is visible only via the autograd tape above.)")

    print()
    print("── VERDICT ───────────────────────────────────────────────────────")
    tr_gap_ok = 0 < train_residual < 500 * 1024 * 1024
    inf_gap_ok = 0 < infer_residual < 500 * 1024 * 1024
    if tr_gap_ok and inf_gap_ok:
        print("  ✅ Both residuals are small & positive — overhead.py (A.3) needs")
        print(f"     to model ~{_mb(max(train_residual, infer_residual))} of CUDA-context +")
        print("     allocator working-set bytes to close the gate.")
    elif train_residual < 0 or infer_residual < 0:
        print("  ❌ Probe over-predicts — dedup or forward logic is wrong.")
    else:
        print("  ⚠️  Residual is large — the probe is missing a structural")
        print("     contribution we have not accounted for yet.")

    out = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "hostname": socket.gethostname(),
        "device_name": torch.cuda.get_device_name() if torch.cuda.is_available() else "cpu",
        "training": {
            "probe_predicted_bytes":      probe_tr_bytes,
            "anchor_bytes":               train_anchor_bytes,
            "residual_bytes":             train_residual,
            "autograd_tape_bytes":        tr.autograd_tape.total_saved_bytes,
            "autograd_unique_storages":   tr.autograd_tape.unique_storage_count,
            "input_bytes":                tr.input_bytes,
            "output_bytes":               tr.output_bytes,
            "param_bytes":                tr.model_forward.total_param_bytes,
        },
        "inference": {
            "probe_predicted_bytes":      probe_inf_bytes,
            "anchor_bytes":               infer_anchor_bytes,
            "residual_bytes":             infer_residual,
            "peak_activation_bytes":      inf_peak_activation,
            "forward_output_bytes_max":   inf.model_forward.forward_output_bytes_max,
            "input_bytes":                inf.input_bytes,
            "output_bytes":               inf.output_bytes,
            "param_bytes":                inf.model_forward.total_param_bytes,
        },
    }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 6.6 A.2 reconciliation")
    ap.add_argument(
        "--device", type=str, default="cuda",
        help="torch device for probing. Must be CUDA to match A.13 anchors.",
    )
    ap.add_argument(
        "--anchor-path", type=Path,
        default=_REPO_ROOT / "docs" / "phase66_telemetry" / "stage2_iter_001_telemetry.json",
        help="Path to the A.13 ground-truth JSON.",
    )
    ap.add_argument(
        "--output", type=Path, default=None,
        help="Optional JSON output path for the reconciliation result.",
    )
    args = ap.parse_args()

    if not args.anchor_path.exists():
        sys.exit(f"anchor file not found: {args.anchor_path}")

    result = reconcile(args.device, args.anchor_path)

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        sys.stderr.write(f"\nWrote: {args.output}\n")


if __name__ == "__main__":
    main()
