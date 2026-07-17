# execute_tools/health_checks/output_std.py
"""
Output-standard-deviation health check (BLOCKING).

Complements ``OutputDiversityCheck``. A model output can theoretically have
``unique_int8 > threshold`` but still be tightly clustered (e.g. 40 distinct
values all within +/-1 LSB), producing a small std that is another phantom
signature. This check catches that case directly.

Empirical calibration (Pearson feasibility experiment 2026-07-16): FCNet
paper reproduction ~ 7.35 mV; worst-observed non-collapse baseline ~ 0.19
mV. Default ``min_std_mv=1.0`` gives ~5x margin on both sides.

Post-M9 (Strategy C): peeks one or more files (via ``peek_file_indices``
YAML config) and aggregates per-file verdicts using ``aggregation``.
Empty ``peek_file_indices`` falls back to the pre-M9 single-file
``min(denoised_paths)`` semantic. Default aggregation is ``any_pass``.

See ``docs/design/collapse_detection_framework_generic.md`` §4 for the
generic recording-vs-blocking design pattern,
``docs/design/m8_gate_coverage_and_diversity_metrics_execution_plan.md`` §3.3
for the empirical threshold justification, and
``docs/design/m9_multi_file_peek_execution_plan.md`` for the multi-file peek.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

import numpy as np

from execute_tools.health_checks._multi_file_peek import peek_and_aggregate
from execute_tools.health_checks.schemas import HealthCheckContext, HealthCheckResult

_MV_PER_LSB: float = 40.0 / 128.0  # int8 -> mV, matches execute_tools/scoring_utils.py


class OutputStdCheck:
    """Reject denoised outputs whose sample std falls below a mV floor."""

    name: ClassVar[str] = "output_std"

    _DEFAULT_MIN_STD_MV: ClassVar[float] = 1.0
    _DEFAULT_PEEK_SAMPLES: ClassVar[int] = 100_000
    _DEFAULT_PEEK_FILE_INDICES: ClassVar[list[int]] = []  # empty → single-file fallback
    _DEFAULT_AGGREGATION: ClassVar[str] = "any_pass"

    def run(
        self,
        ctx: HealthCheckContext,
        config: dict[str, Any] | None = None,
    ) -> HealthCheckResult:
        cfg = config or {}
        min_std_mv = float(cfg.get("min_std_mv", self._DEFAULT_MIN_STD_MV))
        peek_samples = int(cfg.get("peek_samples", self._DEFAULT_PEEK_SAMPLES))
        peek_file_indices = list(cfg.get("peek_file_indices", self._DEFAULT_PEEK_FILE_INDICES))
        aggregation = cfg.get("aggregation", self._DEFAULT_AGGREGATION)

        outcome = peek_and_aggregate(
            ctx,
            peek_file_indices=peek_file_indices,
            metric_fn=lambda arr: float(np.std(arr.astype(np.float64)) * _MV_PER_LSB),
            predicate=lambda m: m >= min_std_mv,
            aggregation=aggregation,
            peek_samples=peek_samples,
        )

        reason = ""
        if not outcome.passed:
            reason = (
                f"{self.name}: {outcome.reason} "
                f"(threshold: std_mv >= {min_std_mv:g} mV). "
                f"Model output is too tightly clustered to carry a real "
                f"denoising signal."
            )
        elif outcome.reason:
            reason = f"{self.name}: {outcome.reason}"

        return HealthCheckResult(
            check_name=self.name,
            passed=outcome.passed,
            reason=reason,
            metrics={
                "aggregated_passed": outcome.passed,
                "aggregation": outcome.aggregation,
                "n_files_attempted": outcome.n_files_attempted,
                "n_files_io_failed": outcome.n_files_io_failed,
                "per_file": [r.model_dump() for r in outcome.per_file],
                "per_file_json": json.dumps([r.model_dump() for r in outcome.per_file]),
                "threshold_mv": min_std_mv,
                "peek_samples_requested": peek_samples,
            },
        )
