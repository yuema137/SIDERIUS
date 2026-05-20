"""
Phase 6.6 A.13 — Ground-truth VRAM telemetry capture.

Replays the Stage 2 iter_001 ``dynamic_depth_simple`` training and inference
phases under ``torch.cuda.max_memory_allocated`` instrumentation. Each phase
runs in a *fresh subprocess* so its CUDA context and peak counters are
independent — matching how SIDERIUS's ``core/sandbox_executor.py`` runs the
two phases in production.

Source of configs (read from disk, then inlined to keep this script
self-contained and reproducible):
  /tmp/pytest-of-yuema137/pytest-811/test_two_iterations_under_budg0/
  stage2_smoke/stage2_iter_001/iteration_001/dynamic_depth_simple/configs/
  stage2_iter_001/{model,train,loss,trial,train_sample_set}_config_*_003.json

Source of plugin code (inlined below for self-containment):
  /tmp/pytest-of-yuema137/pytest-811/test_two_iterations_under_budg0/
  stage2_smoke/stage2_iter_001/iteration_001/attempt_003_dynamic_depth_simple/
  models/dynamic_depth_simple.py

Design principle: this is a one-off measurement artefact. It does NOT modify
any production code path. The alternative — wiring ``max_memory_allocated``
into sandbox_executor — would require touching the subprocess entry points
for a single one-time reading; not worth the blast radius. The VRAM peak is
a function of model + config + batch shapes, all of which this script
replicates exactly from the saved Stage 2 artefacts.

Usage (from repo root):
    .venv/bin/python docs/phase66_telemetry/capture_stage2_vram_telemetry.py \\
        --phase end_to_end \\
        --output docs/phase66_telemetry/stage2_iter_001_telemetry.json

Single-phase mode (for debugging):
    .venv/bin/python docs/phase66_telemetry/capture_stage2_vram_telemetry.py \\
        --phase training
    .venv/bin/python docs/phase66_telemetry/capture_stage2_vram_telemetry.py \\
        --phase inference
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

# SIDERIUS's sandbox model modules use flat (non-packaged) imports among
# themselves (e.g. loss_models_sandbox.py does ``from models_format_sandbox
# import LossConfig``). Add both the repo root and ml_models/ to sys.path so
# our imports resolve whether the script is run from the repo root or from
# a different cwd.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "ml_models"))

import torch
import torch.nn as nn

# Use SIDERIUS's production focal loss so intermediate-tensor shapes match
# exactly what the real training loop would allocate.
from ml_models.loss_models_sandbox import FocalLoss1D
from ml_models.models_format_sandbox import LossConfig

# ── Stage 2 iter_001 attempt 003 configs (copied verbatim from saved JSONs) ──

MODEL_CONFIG = {
    "model_type": "dynamic_depth_simple",
    "segmentation_size": 10000,
    "batch_size": 8,
    "input_channels": 16,
    "residual_channels": 32,
    "gate_channels": 64,
    "kernel_size": 5,
    "skip_channels": 32,
    "embed_dim": 64,
    "num_blocks": 2,
}

TRAIN_CONFIG = {
    "lr": 0.0003,
    "epochs": 1,
    "batch_size": 8,
    "optimizer_type": "adamw",
    "weight_decay": 1e-05,
    "device": "cuda",
}

LOSS_CONFIG = {
    "loss_type": "focal",
    "alpha": 0.25,
    "gamma": 2.0,
    "beta": None,
    "reduction": "mean",
    "use_class_weights": False,
}

# Current runtime inference batch for model_types not in
# core/inference_defaults._INFERENCE_BATCH_SIZES is the silent fallback 25.
# Documented as "inference_batch_uncalibrated=True" — exactly the pathology
# Phase 6.6 WS-A is replacing.
INFERENCE_BATCH = 25


# ── Plugin code: Stage 2 iter_001 attempt_003 (inlined) ─────────────────────


class DynamicDepthSimple(nn.Module):
    """Stage 2 iter_001 attempt_003 model. Copied verbatim from the passing
    plugin at ``attempt_003_dynamic_depth_simple/models/dynamic_depth_simple.py``.
    Forward contract: input ``[B, T]`` int64 → output ``[B, 256, T]`` float32."""

    def __init__(self, model_config: dict):
        super().__init__()
        self.embedding = nn.Embedding(256, model_config["embed_dim"])
        self.causal_conv = nn.Conv1d(
            model_config["embed_dim"],
            model_config["gate_channels"],
            model_config["kernel_size"],
            padding=model_config["kernel_size"] // 2,
        )
        self.skip_conv = nn.Conv1d(
            model_config["gate_channels"] // 2,
            model_config["skip_channels"],
            1,
        )
        self.output_conv = nn.Conv1d(model_config["skip_channels"], 256, 1)
        self.gate_channels = model_config["gate_channels"]

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        embedded = self.embedding(x).transpose(1, 2)
        h = self.causal_conv(embedded)
        f = h[:, : self.gate_channels // 2]
        g = h[:, self.gate_channels // 2 :]
        z = torch.tanh(f) * torch.sigmoid(g)
        skip = self.skip_conv(z)
        y_hat = self.output_conv(skip)
        return y_hat


# ── Phase runners ────────────────────────────────────────────────────────────


def _resolve_device_index(override: str | None) -> int:
    """Return an integer CUDA device index.

    Priority: explicit ``--device`` arg → ``torch.cuda.current_device()`` (which
    honors ``CUDA_VISIBLE_DEVICES``). Never hardcodes 0 — the script must work
    on any lilab / SDSC Expanse / future setup regardless of how the scheduler
    masks GPUs. Calls ``torch.cuda.set_device(idx)`` so all subsequent no-arg
    CUDA calls (``reset_peak_memory_stats``, ``max_memory_allocated``) target
    the resolved device.
    """
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA not available. This telemetry MUST run on a GPU host.")
    if override is None or override == "":
        idx = torch.cuda.current_device()
    elif override.startswith("cuda:"):
        idx = int(override.split(":", 1)[1])
    elif override == "cuda":
        idx = torch.cuda.current_device()
    else:
        idx = int(override)
    n = torch.cuda.device_count()
    if idx < 0 or idx >= n:
        raise RuntimeError(
            f"Requested CUDA device index {idx}, but only {n} device(s) visible. "
            f"Check $CUDA_VISIBLE_DEVICES or pass --device <correct_index>."
        )
    torch.cuda.set_device(idx)
    # Force context initialization so the first reset_peak_memory_stats has a
    # live context to operate on (some PyTorch builds raise 'Invalid device
    # argument' if the context has not been bootstrapped yet).
    torch.cuda.init()
    return idx


def _device_info(idx: int) -> dict:
    props = torch.cuda.get_device_properties(idx)
    return {
        "device_index": idx,
        "device_name": torch.cuda.get_device_name(idx),
        "device_total_bytes": props.total_memory,
        "compute_capability": [props.major, props.minor],
        "multiprocessor_count": props.multi_processor_count,
        "torch_version": torch.__version__,
        "cuda_runtime_version": torch.version.cuda,
        "hostname": socket.gethostname(),
        "captured_at_utc": datetime.now(UTC).isoformat(),
    }


def capture_training_phase(device_override: str | None = None) -> dict:
    """Instantiate, run 5 training steps, return peak bytes.

    5 steps is ample: the PyTorch allocator grabs its working set on the
    first forward+backward pair; subsequent steps reuse the same buffers.
    """
    idx = _resolve_device_index(device_override)
    device = torch.device(f"cuda:{idx}")
    torch.cuda.reset_peak_memory_stats(idx)
    torch.cuda.empty_cache()

    model = DynamicDepthSimple(MODEL_CONFIG).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=TRAIN_CONFIG["lr"],
        weight_decay=TRAIN_CONFIG["weight_decay"],
    )
    criterion = FocalLoss1D(LossConfig(**LOSS_CONFIG)).to(device)

    B = TRAIN_CONFIG["batch_size"]
    T = MODEL_CONFIG["segmentation_size"]
    # Synthetic batch — VRAM peak is determined by tensor shapes + ops, not
    # by data values. Real TIDMAD h5 loading adds CPU-side overhead but does
    # not change peak GPU allocation beyond the batch transfer itself, which
    # we reproduce here.
    x = torch.randint(0, 256, (B, T), device=device, dtype=torch.long)
    y = torch.randint(0, 256, (B, T), device=device, dtype=torch.long)

    STEPS = 5
    for _ in range(STEPS):
        optimizer.zero_grad(set_to_none=True)
        logits = model(x)
        loss = criterion(logits, y)
        loss.backward()
        optimizer.step()

    torch.cuda.synchronize(idx)
    peak_alloc = torch.cuda.max_memory_allocated(idx)
    peak_reserved = torch.cuda.max_memory_reserved(idx)

    out = {
        "phase": "training",
        "peak_allocated_bytes": peak_alloc,
        "peak_reserved_bytes": peak_reserved,
        "peak_allocated_gb": round(peak_alloc / (1024**3), 4),
        "peak_reserved_gb": round(peak_reserved / (1024**3), 4),
        "steps": STEPS,
        "batch_size": B,
        "segmentation_size": T,
        "num_params": sum(p.numel() for p in model.parameters()),
        "optimizer": TRAIN_CONFIG["optimizer_type"],
        "loss": LOSS_CONFIG["loss_type"],
    }
    out.update(_device_info(idx))
    return out


def capture_inference_phase(device_override: str | None = None) -> dict:
    """Instantiate, run a single no_grad forward at the runtime fallback
    inference batch (25), return peak bytes."""
    idx = _resolve_device_index(device_override)
    device = torch.device(f"cuda:{idx}")
    torch.cuda.reset_peak_memory_stats(idx)
    torch.cuda.empty_cache()

    model = DynamicDepthSimple(MODEL_CONFIG).to(device)
    model.eval()

    B = INFERENCE_BATCH
    T = MODEL_CONFIG["segmentation_size"]
    x = torch.randint(0, 256, (B, T), device=device, dtype=torch.long)

    with torch.no_grad():
        _ = model(x)

    torch.cuda.synchronize(idx)
    peak_alloc = torch.cuda.max_memory_allocated(idx)
    peak_reserved = torch.cuda.max_memory_reserved(idx)

    out = {
        "phase": "inference",
        "peak_allocated_bytes": peak_alloc,
        "peak_reserved_bytes": peak_reserved,
        "peak_allocated_gb": round(peak_alloc / (1024**3), 4),
        "peak_reserved_gb": round(peak_reserved / (1024**3), 4),
        "inference_batch": B,
        "segmentation_size": T,
        "num_params": sum(p.numel() for p in model.parameters()),
    }
    out.update(_device_info(idx))
    return out


# ── Subprocess orchestration (end_to_end) ────────────────────────────────────

_CHILD_MARKER = "--__child"


def _spawn_child(phase: str, device_override: str | None = None) -> dict:
    cmd = [sys.executable, __file__, "--phase", phase, _CHILD_MARKER]
    if device_override:
        cmd.extend(["--device", device_override])
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        cwd=os.environ.get("PWD", "."),
    )
    if result.returncode != 0:
        sys.stderr.write(f"\n!!! Child subprocess for phase={phase} failed:\n")
        sys.stderr.write(result.stderr)
        sys.stderr.write(f"\n(stdout follows)\n{result.stdout}\n")
        sys.exit(result.returncode)

    # Child writes one JSON object as the final non-empty line of stdout.
    for line in reversed(result.stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise RuntimeError(
        f"No JSON payload in child stdout for phase={phase}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def run_end_to_end(device_override: str | None = None) -> dict:
    training = _spawn_child("training", device_override)
    inference = _spawn_child("inference", device_override)
    max_peak = max(training["peak_allocated_bytes"], inference["peak_allocated_bytes"])
    dominant = (
        "training"
        if training["peak_allocated_bytes"] >= inference["peak_allocated_bytes"]
        else "inference"
    )
    return {
        "phases": {
            "training": training,
            "inference": inference,
        },
        "max_peak_bytes": max_peak,
        "max_peak_gb": round(max_peak / (1024**3), 4),
        "dominant_phase": dominant,
        "device_name": training["device_name"],
        "device_total_bytes": training["device_total_bytes"],
        "device_total_gb": round(training["device_total_bytes"] / (1024**3), 4),
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "hostname": socket.gethostname(),
        "source_artefact": "/tmp/pytest-of-yuema137/pytest-811/test_two_iterations_under_budg0/stage2_smoke/stage2_iter_001/iteration_001/attempt_003_dynamic_depth_simple",
    }


# ── CLI ──────────────────────────────────────────────────────────────────────


def _emit(payload: dict, output_path: Path | None) -> None:
    as_json = json.dumps(payload, indent=2)
    print(as_json)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(as_json + "\n")
        sys.stderr.write(f"\nWrote: {output_path}\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 6.6 A.13 VRAM telemetry capture")
    ap.add_argument(
        "--phase",
        choices=["training", "inference", "end_to_end"],
        required=True,
        help="Which phase to measure. 'end_to_end' spawns two fresh subprocesses.",
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON to this path in addition to stdout.",
    )
    ap.add_argument(
        "--device",
        type=str,
        default=None,
        help=(
            "CUDA device override. Accepts '0', 'cuda:0', or 'cuda'. "
            "If omitted, uses torch.cuda.current_device() (which honors "
            "$CUDA_VISIBLE_DEVICES)."
        ),
    )
    ap.add_argument(
        _CHILD_MARKER,
        dest="_child",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = ap.parse_args()

    if args._child:
        if args.phase == "training":
            result = capture_training_phase(args.device)
        elif args.phase == "inference":
            result = capture_inference_phase(args.device)
        else:
            raise ValueError("end_to_end cannot run in child mode")
        print(json.dumps(result))
        return

    if args.phase == "training":
        _emit(capture_training_phase(args.device), args.output)
    elif args.phase == "inference":
        _emit(capture_inference_phase(args.device), args.output)
    else:
        _emit(run_end_to_end(args.device), args.output)


if __name__ == "__main__":
    main()
