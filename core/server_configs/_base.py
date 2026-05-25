"""
core/server_configs/_base.py

Pydantic schema for per-server calibration constants.

One instance per server lives in ``core/server_configs/{hostname}.py``.
Fields are added only when a concrete skill needs them — keep this
schema minimal. ``frozen=True`` prevents accidental mutation of
measured constants at runtime; ``extra="forbid"`` surfaces typos in a
server file as a validation error rather than silent ignorance.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ServerConfig(BaseModel):
    """Per-server calibration constants.

    Attributes:
        hostname: Canonical hostname key. Must match the module
            filename so ``get_server_config`` can resolve it.
        per_psd_segment_seconds: Measured wall-time to score one PSD
            segment (2× 10M-sample rFFT + SNR extraction) on this
            server, single-process sequential. Used by
            ``denoising_score_skill/estimator.py`` to forecast the
            scoring-phase wall-time.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    hostname: str = Field(..., min_length=1)
    per_psd_segment_seconds: float = Field(..., gt=0.0)
