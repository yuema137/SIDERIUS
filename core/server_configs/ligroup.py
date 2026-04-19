"""
core/server_configs/ligroup.py

Calibration constants for the ``ligroup`` server (lilab primary GPU box).
"""

from core.server_configs._base import ServerConfig


CONFIG: ServerConfig = ServerConfig(
    hostname="ligroup",
    # Measured 2026-04-18 on ligroup, single-process sequential.
    # N=100 PSD segments of /home/klz/Data/TIDMAD/abra_validation_0000.h5
    # via execute_tools.scoring_utils.process_segment (2× get_one_sec_psd
    # + 2× get_snr per segment). Warm-cache mean = 612.9 ms, stdev =
    # 1.34 ms, p95 = 614.9 ms (cold mean 638.9 ms). See Phase K.2.5
    # commit 4 in docs/resource_estimator_implement.md for the
    # measurement protocol.
    per_psd_segment_seconds=0.613,
)
