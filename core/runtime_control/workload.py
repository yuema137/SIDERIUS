"""
core/runtime_control/workload.py

Generic resolved-workload object consumed by the runtime-control
framework (RT2-A).

Design: docs/design/runtime_estimation_and_watchdog.md §1.2. Workload
RESOLUTION is task-specific and lives colocated with the production
engines (`execute_tools/workload_resolvers.py` for TIDMAD); the
framework consumes these resolved objects and never duplicates
task-specific formulas. The `detail` dict preserves the full derivation
(files, samples, per-file counts, …) so every prediction is
independently reproducible from its observation record.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.runtime_control.phases import RuntimePhase


class ResolvedPhaseWorkload(BaseModel):
    """Exact workload of one runtime phase, in that phase's natural unit.

    The unit must mirror the actual production implementation
    (training: optimizer steps; inference: batches; scoring: PSD
    segments for TIDMAD). ``unit_count × measured_unit_time`` is the
    phase's compute term.
    """

    model_config = ConfigDict(frozen=True)

    phase: RuntimePhase
    unit: str = Field(min_length=1, description='e.g. "optimizer_step", "inference_batch"')
    unit_count: int = Field(ge=0)
    detail: dict[str, Any] = Field(
        default_factory=dict,
        description="Full derivation record (files, per-file counts, portions…).",
    )
