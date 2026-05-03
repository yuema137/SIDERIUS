"""
core/server_configs/ligroup.py

Calibration constants for the ``ligroup`` server (lilab primary GPU box).
"""

from core.server_configs._base import ServerConfig


CONFIG: ServerConfig = ServerConfig(
    hostname="ligroup",
    # Recalibrated 2026-04-30 from V7 formal-round end-to-end timings:
    # 4000 PSDs × ~0.275 s/segment effective (8-worker pool) ≈ 1100 s
    # observed across 8 architectures. The 2026-04-18 figure (0.613)
    # was a single-file warm-cache micro-benchmark on
    # abra_validation_0000.h5 and underestimated the per-segment cost
    # of the full validation set by 3.6× (file IO + cross-file variance
    # + worker spawn overhead are not amortized in the micro-benchmark).
    # 2.21 = 0.275 s effective × 8 workers, the per-segment raw cost
    # the estimator divides by num_workers when projecting wall-time.
    per_psd_segment_seconds=2.21,
)
