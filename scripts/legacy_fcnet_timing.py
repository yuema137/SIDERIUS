#!/usr/bin/env python
"""Official legacy FCNet timing track (C12 sub-track).

Measures the REAL runtime behaviour of the official TIDMAD FCNet on each
of the four official frequency bands, using the legacy model definition
itself — not a reimplementation.

READ-ONLY CONTRACT
------------------
`/home/tidmad/TIDMAD` is evidence, not a workspace. This script:

* imports exactly ONE symbol from it — ``network.AE`` — and executes
  nothing else there;
* never runs `train.py`/`inference.py`, because both write checkpoints
  and denoised files to RELATIVE paths (`torch.save(model,
  f'FCNet_{a}_{b}.pth')`, train.py:169) that would land wherever the
  process happens to be;
* runs with `PYTHONDONTWRITEBYTECODE=1` so importing `network` cannot
  add to the `__pycache__` directories already present there;
* fingerprints the legacy tree before and after and refuses to report
  success if anything changed.

The legacy `network.py` imports `torchsnooper` at line 9 but never uses
it — every call site (lines 96, 144, 183, 270, 406, 583) is commented
out. It is not installed in this venv, so a stub is injected into
`sys.modules` before the import. That satisfies the import without
modifying, patching or shadowing any legacy file.

WORKLOAD FIDELITY
-----------------
Every constant below is read from the legacy source, not remembered:

    input_size  = 40000                     train.py:41
    sample_size = 10                        train.py:44
    batchsize   = 1                         train.py:45
    max_index   = 2000000000                train.py:57
    reshape     = (-1, sample_size, batchsize, input_size)   train.py:58-59
    bands       = [0,4,10,15,20]            train.py:74  -> 0-3/4-9/10-14/15-19
    model       = AE(input_size)            train.py:102
    loss        = nn.SmoothL1Loss()         train.py:103  (fcnet branch)
    optimizer   = Adam(lr=0.0005)           train.py:113
    steps/file  = 2e9 // (10*1*40000) = 5000        (from train.py:57-58)
    inference   : input_size 40000          inference.py:69
                  batchsize   25            inference.py:70
                  reshape (-1, batchsize, input_size)       inference.py:94
    AE dims     : 40000 -> 4000 -> 400 -> 40 -> 400 -> 4000 -> 40000
                  scale_factor [0.1,0.01,0.001]  network.py:291
                  realized parameter count 323,280,840

Phases
------
A  bounded probe: real init, real load, 3 warmup + N timed training
   steps, bounded inference, VRAM + contention, projections.
B  bounded real execution: a wall-clock-capped segment of the real
   loop, compared against Phase A's projection.

Nothing runs without ``--run``; the default prints the plan.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.dont_write_bytecode = True

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

LEGACY_ROOT = Path("/home/tidmad/TIDMAD")
DEFAULT_DATA_DIR = Path("/home/klz/Data/TIDMAD")
DEFAULT_OUTPUT_ROOT = Path("/home/klz/Data/SIDEREIS_DATA/runtime_validation/legacy_fcnet")

# --- constants transcribed from the legacy source (see module docstring) ---
INPUT_SIZE = 40_000
SAMPLE_SIZE = 10
BATCH_SIZE = 1
LEARNING_RATE = 0.0005
MAX_INDEX = 2_000_000_000
INFERENCE_BATCH = 25
BANDS: dict[str, tuple[int, int]] = {
    "0-3": (0, 4),
    "4-9": (4, 10),
    "10-14": (10, 15),
    "15-19": (15, 20),
}


def legacy_fingerprint() -> dict[str, str]:
    """Hash every tracked legacy source file (proof of read-only use)."""
    digests: dict[str, str] = {}
    for path in sorted(LEGACY_ROOT.glob("*.py")):
        digests[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def legacy_tree_inventory() -> set[str]:
    """Every path under the legacy root, so a NEW file is detectable."""
    return {str(p) for p in LEGACY_ROOT.rglob("*") if "__pycache__" not in str(p)}


def load_legacy_ae():
    """Import ``network.AE`` from the legacy repo. Read-only."""
    import types

    if "torchsnooper" not in sys.modules:
        # Imported at network.py:9, never used (all call sites commented).
        stub = types.ModuleType("torchsnooper")
        stub.snoop = lambda *a, **k: lambda f: f  # type: ignore[attr-defined]
        sys.modules["torchsnooper"] = stub
    if str(LEGACY_ROOT) not in sys.path:
        sys.path.append(str(LEGACY_ROOT))
    from network import AE  # type: ignore[import-not-found]

    return AE


def band_files(band: str, data_dir: Path) -> list[Path]:
    low, high = BANDS[band]
    files = []
    for index in range(low, high):
        path = data_dir / f"abra_training_{index:04d}.h5"
        if path.is_file():
            files.append(path)
    return files


def plan(band: str, data_dir: Path, output_root: Path, args) -> dict:
    files = band_files(band, data_dir)
    steps_per_file = MAX_INDEX // (SAMPLE_SIZE * BATCH_SIZE * INPUT_SIZE)
    return {
        "band": band,
        "band_file_range": list(BANDS[band]),
        "files_present": [f.name for f in files],
        "steps_per_file": steps_per_file,
        "configured_training_steps": steps_per_file * len(files),
        "input_size": INPUT_SIZE,
        "train_batch_size": BATCH_SIZE,
        "sample_size": SAMPLE_SIZE,
        "optimizer": f"Adam(lr={LEARNING_RATE})",
        "loss": "nn.SmoothL1Loss()",
        "inference_batch": INFERENCE_BATCH,
        "probe_caps": {
            "warmup_steps": args.warmup_steps,
            "timed_train_steps": args.timed_steps,
            "timed_inference_batches": args.inference_batches,
            "phase_b_wall_seconds": args.phase_b_seconds,
        },
        "output_dir": str(output_root / f"band_{band}"),
        "data_dir": str(data_dir),
        "legacy_symbols_used": ["network.AE"],
        "legacy_scripts_executed": [],
    }


def _load_band_file(path: Path) -> tuple[object, float]:
    """Legacy ``read_loader`` semantics (train.py:52-62), timed."""
    import h5py
    import numpy as np

    started = time.perf_counter()
    with h5py.File(path, "r") as handle:
        alltrain = np.array(handle["timeseries"]["channel0001"]["timeseries"]) + 128
        alltarget = np.array(handle["timeseries"]["channel0002"]["timeseries"]) + 128
    alltrain = alltrain[:MAX_INDEX].reshape(-1, SAMPLE_SIZE, BATCH_SIZE, INPUT_SIZE)
    alltarget = alltarget[:MAX_INDEX].reshape(-1, SAMPLE_SIZE, BATCH_SIZE, INPUT_SIZE)
    random_index = np.random.randint(SAMPLE_SIZE)
    loader = np.concatenate([alltrain[:, random_index], alltarget[:, random_index]], axis=1)
    return loader, time.perf_counter() - started


def run_phase_a(band: str, data_dir: Path, output_root: Path, args) -> dict:
    """Bounded probe on one band. Real model, real data, capped steps."""
    import numpy as np
    import torch
    import torch.nn as nn

    from core.runtime_control.calibration_policy import sample_contention_window
    from core.runtime_control.probe_production import probe_device_vram_gb

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    record = plan(band, data_dir, output_root, args)
    files = band_files(band, data_dir)
    if not files:
        record["error"] = f"no training files present for band {band}"
        return record

    window = sample_contention_window(device_vram_gb=probe_device_vram_gb())
    record["contention"] = window.raw_telemetry()
    if window.classification != "single_candidate_idle":
        record["error"] = f"GPU not idle: {window.classification}"
        return record

    AE = load_legacy_ae()
    setup_started = time.perf_counter()
    model = AE(INPUT_SIZE).to(device)
    criterion = nn.SmoothL1Loss().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    torch.cuda.synchronize() if device.type == "cuda" else None
    record["setup_seconds"] = time.perf_counter() - setup_started
    record["realized_parameter_count"] = sum(p.numel() for p in model.parameters())

    loader, load_seconds = _load_band_file(files[0])
    record["data_indexing_seconds"] = load_seconds
    record["data_indexing_file"] = files[0].name

    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats()

    timings: list[float] = []
    total = args.warmup_steps + args.timed_steps
    for step in range(total):
        batch = loader[step]
        input_seq = torch.from_numpy(batch[:BATCH_SIZE]).float().to(device)
        target_seq = torch.from_numpy(batch[BATCH_SIZE:]).float().to(device)
        if device.type == "cuda":
            torch.cuda.synchronize()
        started = time.perf_counter()
        optimizer.zero_grad()
        loss = criterion(model(input_seq), target_seq)
        loss.backward()
        optimizer.step()
        if device.type == "cuda":
            torch.cuda.synchronize()
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if step >= args.warmup_steps:
            timings.append(elapsed_ms)

    record["train_ms_per_step"] = float(np.median(timings))
    record["train_ms_spread"] = [float(min(timings)), float(max(timings))]

    model.eval()
    inference_timings: list[float] = []
    with torch.no_grad():
        for index in range(args.inference_batches):
            chunk = loader[index][:BATCH_SIZE]
            batch = np.repeat(chunk, INFERENCE_BATCH, axis=0)
            tensor = torch.from_numpy(batch).float().to(device)
            if device.type == "cuda":
                torch.cuda.synchronize()
            started = time.perf_counter()
            model(tensor)
            if device.type == "cuda":
                torch.cuda.synchronize()
            inference_timings.append((time.perf_counter() - started) * 1000.0)
    record["inference_ms_per_batch"] = float(np.median(inference_timings))

    if device.type == "cuda":
        record["peak_vram_allocated_gb"] = torch.cuda.max_memory_allocated() / 2**30
        record["peak_vram_reserved_gb"] = torch.cuda.max_memory_reserved() / 2**30

    steps = record["configured_training_steps"]
    record["projected_training_seconds"] = record["train_ms_per_step"] * steps / 1000.0
    record["projected_data_indexing_seconds"] = load_seconds * len(files)
    record["projected_total_seconds"] = (
        record["projected_training_seconds"]
        + record["projected_data_indexing_seconds"]
        + record["setup_seconds"]
    )
    return record


def run_phase_b(band: str, data_dir: Path, output_root: Path, args) -> dict:
    """Bounded REAL execution: the legacy loop under a wall-clock cap."""
    import numpy as np
    import torch
    import torch.nn as nn

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    record = plan(band, data_dir, output_root, args)
    record["phase"] = "b"
    files = band_files(band, data_dir)
    if not files:
        record["error"] = f"no training files present for band {band}"
        return record

    AE = load_legacy_ae()
    model = AE(INPUT_SIZE).to(device)
    criterion = nn.SmoothL1Loss().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    loader, load_seconds = _load_band_file(files[0])
    record["data_indexing_seconds"] = load_seconds

    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    executed = 0
    np.random.shuffle(loader)
    for batch in loader:
        if time.perf_counter() - started >= args.phase_b_seconds:
            break
        input_seq = torch.from_numpy(batch[:BATCH_SIZE]).float().to(device)
        target_seq = torch.from_numpy(batch[BATCH_SIZE:]).float().to(device)
        optimizer.zero_grad()
        loss = criterion(model(input_seq), target_seq)
        loss.backward()
        optimizer.step()
        executed += 1
    if device.type == "cuda":
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - started
    record["executed_steps"] = executed
    record["executed_seconds"] = elapsed
    record["actual_ms_per_step"] = (elapsed * 1000.0 / executed) if executed else None
    if device.type == "cuda":
        record["peak_vram_allocated_gb"] = torch.cuda.max_memory_allocated() / 2**30
        record["peak_vram_reserved_gb"] = torch.cuda.max_memory_reserved() / 2**30
    return record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--band", choices=sorted(BANDS), required=True)
    parser.add_argument("--phase", choices=["a", "b"], default="a")
    parser.add_argument("--run", action="store_true", help="Execute (GPU). Default: plan only.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--warmup-steps", type=int, default=3)
    parser.add_argument("--timed-steps", type=int, default=20)
    parser.add_argument("--inference-batches", type=int, default=5)
    parser.add_argument("--phase-b-seconds", type=float, default=300.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = args.output_root / f"band_{args.band}"

    if not args.run:
        print(json.dumps(plan(args.band, args.data_dir, args.output_root, args), indent=2))
        return 0

    before_files = legacy_fingerprint()
    before_tree = legacy_tree_inventory()

    output_dir.mkdir(parents=True, exist_ok=True)
    runner = run_phase_a if args.phase == "a" else run_phase_b
    record = runner(args.band, args.data_dir, args.output_root, args)

    after_files = legacy_fingerprint()
    new_paths = legacy_tree_inventory() - before_tree
    record["legacy_repo_unmodified"] = before_files == after_files
    record["legacy_repo_new_paths"] = sorted(new_paths)
    if not record["legacy_repo_unmodified"] or new_paths:
        record["error"] = "LEGACY REPOSITORY CHANGED — this run is invalid"

    target = output_dir / f"phase_{args.phase}_timing.json"
    target.write_text(json.dumps(record, indent=2, default=str))
    print(json.dumps(record, indent=2, default=str))
    print(f"\n  record -> {target}")
    return 1 if record.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
