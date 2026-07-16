# execute_tools/health_checks/output_diversity.py
"""
Output-diversity health check (BLOCKING).

Catches class-127 mode collapse — the failure mode that produces score
5.5762667 via the 2^17 floating-point artifact. See
``docs/design/pluggable_health_checks.md`` §11 for the discovery
narrative and §9.1 for the check spec.

Post-M9 (Strategy C): peeks one or more files (via
``peek_file_indices`` YAML config) and aggregates the per-file
verdicts using ``aggregation`` (see
``docs/design/m9_multi_file_peek_execution_plan.md``). Empty
``peek_file_indices`` falls back to the pre-M9 single-file
``min(denoised_paths)`` semantic. Default aggregation is ``any_pass``.

Mechanism: peek CH1 of each configured file, count unique int8 values
in a bounded sample per file, mark the file as failed when the count
is ≤ the configured threshold, then aggregate.

Rev-6 note: conforms to the ``HealthCheckSkill`` Protocol (§6). The
"not applicable" scenario (no path configured in the context) is
reported inline as ``passed=True`` with a reason. Peek I/O errors
(``OSError``, ``KeyError``) are treated as caller misconfiguration and
surfaced in the ``per_file_json`` breakdown; whether they force a
``passed=False`` gate verdict depends on the aggregation mode.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

import numpy as np

from execute_tools.health_checks._multi_file_peek import peek_and_aggregate
from execute_tools.health_checks.schemas import HealthCheckContext, HealthCheckResult


class OutputDiversityCheck:
    """Reject denoised outputs with too few unique int8 values."""

    name: ClassVar[str] = "output_diversity"

    _DEFAULT_MIN_UNIQUE: ClassVar[int] = (
        5  # class-default backward compat; production YAML overrides to 25 (M8)
    )
    _DEFAULT_PEEK_SAMPLES: ClassVar[int] = 100_000
    _DEFAULT_PEEK_FILE_INDICES: ClassVar[list[int]] = []  # empty → single-file fallback
    _DEFAULT_AGGREGATION: ClassVar[str] = "any_pass"

    def run(
        self,
        ctx: HealthCheckContext,
        config: dict[str, Any] | None = None,
    ) -> HealthCheckResult:
        cfg = config or {}
        min_unique = int(cfg.get("min_unique_int8_values", self._DEFAULT_MIN_UNIQUE))
        peek_samples = int(cfg.get("peek_samples", self._DEFAULT_PEEK_SAMPLES))
        peek_file_indices = list(cfg.get("peek_file_indices", self._DEFAULT_PEEK_FILE_INDICES))
        aggregation = cfg.get("aggregation", self._DEFAULT_AGGREGATION)

        outcome = peek_and_aggregate(
            ctx,
            peek_file_indices=peek_file_indices,
            metric_fn=lambda arr: int(np.unique(arr).size),
            predicate=lambda m: m > min_unique,
            aggregation=aggregation,
            peek_samples=peek_samples,
        )

        reason = ""
        if not outcome.passed:
            reason = (
                f"{self.name}: {outcome.reason} "
                f"(threshold: unique_int8 > {min_unique}). "
                f"Class-127 collapse artifact — score would be 5.5762667 "
                f"via 2^17 FP ratio."
            )
        elif outcome.reason:  # "not applicable" pass carries a reason
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
                "per_file_json": json.dumps([r.model_dump() for r in outcome.per_file]),
                "threshold": min_unique,
                "peek_samples_requested": peek_samples,
            },
        )
