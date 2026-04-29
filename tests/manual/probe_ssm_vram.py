"""Phase 6.8 Commit 11 — Gate 2: SSM VRAM stress probe.

Replays the dual_selective_ssm_head model from v6 (segmentation_size=40000,
4 blocks, ssm_state_size=16) through a forward+backward step on synthetic
input, sampling RSS via psutil and CUDA peak via torch every step.

Goal: prove peak GPU < 8 GB and RSS does not balloon to 30 GB+.
If it does, Commit 9's del+gc / no_grad fix has regressed.

Run:
    .venv/bin/python tests/manual/probe_ssm_vram.py
"""
from __future__ import annotations

import gc
import importlib.util
import os
import sys
import time

import psutil
import torch
import torch.nn as nn

PLUGIN_PATH = (
    "/home/klz/Data/SIDEREIS_DATA/exploration_explore_novel_v6_0427/"
    "explore_novel_v6_0427/iteration_002/dual_selective_ssm_head/"
    "plugins/explore_novel_v6_0427/dual_selective_ssm_head.py"
)


def _load_plugin(path: str):
    spec = importlib.util.spec_from_file_location("v6_ssm_plugin", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rss_gb() -> float:
    return psutil.Process(os.getpid()).memory_info().rss / 1024 ** 3


def _gpu_gb(reset: bool = False) -> tuple[float, float]:
    if not torch.cuda.is_available():
        return (0.0, 0.0)
    if reset:
        torch.cuda.reset_peak_memory_stats()
    return (
        torch.cuda.memory_allocated() / 1024 ** 3,
        torch.cuda.max_memory_allocated() / 1024 ** 3,
    )


def main() -> int:
    if not torch.cuda.is_available():
        print("[ABORT] CUDA not available")
        return 1

    print(f"[env] device      = {torch.cuda.get_device_name(0)}")
    print(f"[env] cuda free   = {torch.cuda.mem_get_info()[0] / 1024**3:.2f} GB")
    print(f"[env] rss baseline = {_rss_gb():.2f} GB")
    print(f"[env] plugin       = {os.path.basename(PLUGIN_PATH)}")

    print("\n[step] loading v6 plugin...")
    plugin = _load_plugin(PLUGIN_PATH)
    cfg_cls = plugin.PLUGIN_CONFIG_CLASS
    model_cls = plugin.PLUGIN_MODEL_CLASS if hasattr(plugin, "PLUGIN_MODEL_CLASS") else None
    if model_cls is None:
        for name in dir(plugin):
            obj = getattr(plugin, name)
            if isinstance(obj, type) and issubclass(obj, nn.Module) and obj is not nn.Module:
                model_cls = obj
                break
    assert model_cls is not None, "could not locate model class on plugin"

    cfg = cfg_cls(
        segmentation_size=40000,
        batch_size=1,
        embedding_dim=32,
        input_channels=96,
        hidden_channels=96,
        num_blocks=4,
        ssm_state_size=16,
    )
    print(f"[cfg] {cfg.model_dump()}")

    print("\n[step] instantiating model on CUDA...")
    torch.cuda.empty_cache()
    gc.collect()
    _gpu_gb(reset=True)

    model = model_cls(cfg).to("cuda")
    n_params = sum(p.numel() for p in model.parameters())
    print(f"[model] num_params = {n_params:,}")
    cur, peak = _gpu_gb()
    print(f"[after-instantiate] gpu_alloc={cur:.2f} GB peak={peak:.2f} GB rss={_rss_gb():.2f} GB")

    optim = torch.optim.AdamW(model.parameters(), lr=1e-4)
    crit = nn.CrossEntropyLoss()

    print("\n[step] running 5 forward+backward steps with synthetic input...")
    samples = []
    for step in range(5):
        x = torch.randint(0, 256, (cfg.batch_size, cfg.segmentation_size), dtype=torch.int32, device="cuda")
        y = torch.randint(0, 256, (cfg.batch_size, cfg.segmentation_size), dtype=torch.long, device="cuda")
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        optim.zero_grad()
        out = model(x)
        loss = crit(out, y)
        loss.backward()
        optim.step()
        torch.cuda.synchronize()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        cur, peak = _gpu_gb()
        rss = _rss_gb()
        samples.append((step, elapsed_ms, cur, peak, rss))
        print(
            f"  step {step}: {elapsed_ms:7.1f} ms | "
            f"gpu_alloc={cur:5.2f} GB peak={peak:5.2f} GB | rss={rss:5.2f} GB"
        )

    final_peak_gpu = max(s[3] for s in samples)
    final_peak_rss = max(s[4] for s in samples)

    print("\n=== SUMMARY ===")
    print(f"  num_params      : {n_params:,}")
    print(f"  GPU peak alloc  : {final_peak_gpu:.2f} GB  (target: < 8 GB)")
    print(f"  RSS peak        : {final_peak_rss:.2f} GB  (target: << 30 GB)")
    print(f"  median step ms  : {sorted([s[1] for s in samples])[len(samples)//2]:.1f}")
    print(f"  GATE 2 status   : {'PASS' if final_peak_gpu < 8.0 else 'FAIL'}")

    del model, optim, crit
    torch.cuda.empty_cache()
    gc.collect()
    return 0 if final_peak_gpu < 8.0 else 2


if __name__ == "__main__":
    sys.exit(main())
