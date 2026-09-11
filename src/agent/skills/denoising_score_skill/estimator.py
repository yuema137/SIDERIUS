"""
agent/skills/denoising_score_skill/estimator.py

Per-phase VRAM and wall-time estimator for the SCORING phase. Called
by the resource aggregators (K.2.5). Scoring is an *independent +
non-adjustable* phase: a fixed evaluation protocol (PSD + SNR) that
runs on CPU via ``core.sandbox_executor.execute_scoring`` after
training and inference. The planner sees its cost but has no lever to
shrink it — unlike training (directly tunable) or inference (dependent
on training ``model_config``).

Key points:
  * VRAM = 0 by design. ``execute_tools/denoising_score_single.py`` is
    pure NumPy/FFT; no ``torch.cuda`` imports.
  * Wall time:
      ``total_psd_segments × per_psd_segment_seconds / max(num_workers, 1)``
    where ``per_psd_segment_seconds`` is a per-server measurement
    stored in ``core/server_configs/{hostname}.py``. Cross-server
    variance lives in the per-server constant, not in a separate
    scaling factor (deviates from §10.6; see
    ``core/server_configs/__init__.py``).

"Segment" in this phase means PSD segment (10 million samples = 1 s
at 10 MS/s; 200 per validation file), NOT the ML segment the model
processes. The per-PSD work dominated by two 10M-sample rFFTs (raw
CH2 + denoised CH1) is exactly what the measured constant times.

See docs/resource_estimator_implement.md §10.5 + §10.14 Commit 4.
"""

from __future__ import annotations

from typing import Any

from core.server_configs import get_server_config


def estimate_peak_bytes() -> dict[str, Any]:
    """Peak scoring VRAM. Zero by design (CPU-only FFT/SNR)."""
    return {
        "phase": "scoring",
        "total_bytes": 0,
        "breakdown": {},
    }


def estimate_wall_time_seconds(
    sample_set: dict[Any, list[int]],
    *,
    num_workers: int = 8,
    hostname: str | None = None,
) -> dict[str, Any]:
    """Estimate scoring wall-time in seconds.

    Args:
        sample_set: ``{file_index: [psd_segment_indices]}``. Only the
            total PSD-segment count matters here; file indices and
            segment positions do not affect wall-time.
        num_workers: Parallel worker count. ``scoring_utils.score_vector``
            defaults to 8 via ``ProcessPoolExecutor``. Degenerate 0 is
            floored to 1 to avoid divide-by-zero.
        hostname: Override for the current host's server config.
            ``None`` → the current machine.

    Returns:
        ``{"phase": "scoring", "seconds": float, "breakdown": {...}}``.
    """
    cfg = get_server_config(hostname)
    total_psd_segments = sum(len(v) for v in sample_set.values())
    workers = max(num_workers, 1)
    seconds = total_psd_segments * cfg.per_psd_segment_seconds / workers

    return {
        "phase": "scoring",
        "seconds": seconds,
        "breakdown": {
            "total_psd_segments": total_psd_segments,
            "num_workers": workers,
            "per_psd_segment_seconds": cfg.per_psd_segment_seconds,
            "hostname": cfg.hostname,
        },
    }
