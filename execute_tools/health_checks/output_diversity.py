# execute_tools/health_checks/output_diversity.py
"""
Output-diversity health check.

Catches class-127 mode collapse — the failure mode that produces score
5.5762667 via the 2^17 floating-point artifact. See
``docs/design/pluggable_health_checks.md`` §11 for the discovery
narrative and §9.1 for the check spec.

Mechanism: peek the first available denoised HDF5's ``channel0001``,
count unique int8 values in a bounded sample. When the count is at or
below the configured threshold, the model has collapsed to a
near-constant output — the resulting SNR values are FP-cancellation
artifacts, not meaningful signal.

Why peek the first file only. Class-127 collapse is a whole-model
behavior — if the model collapses on one file it collapses on all. One
100k-sample peek is ~1 ms on typical hardware and catches the case
before scoring wastes time on 200 segments × 20 files of FFT work.

Rev-6 note: conforms to the ``HealthCheckSkill`` Protocol (§6). No
``is_applicable`` — the "not applicable" scenario (no path configured
in the context) is reported inline as ``passed=True`` with a reason.
Peek I/O errors (OSError, KeyError) are treated as caller
misconfiguration and reported as ``passed=False`` with the attempted
path in the reason.
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np

from execute_tools.health_checks._peek import choose_peek_file_index, peek_int8_at_path
from execute_tools.health_checks.schemas import HealthCheckContext, HealthCheckResult


class OutputDiversityCheck:
    """Reject denoised outputs with too few unique int8 values."""

    name: ClassVar[str] = "output_diversity"

    _DEFAULT_MIN_UNIQUE: ClassVar[int] = 5
    _DEFAULT_PEEK_SAMPLES: ClassVar[int] = 100_000

    def run(
        self,
        ctx: HealthCheckContext,
        config: dict[str, Any] | None = None,
    ) -> HealthCheckResult:
        cfg = config or {}
        min_unique = int(cfg.get("min_unique_int8_values", self._DEFAULT_MIN_UNIQUE))
        peek_samples = int(cfg.get("peek_samples", self._DEFAULT_PEEK_SAMPLES))

        file_index = choose_peek_file_index(ctx)
        path = ctx.get_denoised_path(file_index)
        if path is None:
            # AMB-4-3 / rev-6 §6: the only legitimate "not applicable" case.
            # The context has neither denoised_paths nor denoised_filename_fn,
            # so no peek is possible — pass without judgement.
            return HealthCheckResult(
                check_name=self.name,
                passed=True,
                reason=f"{self.name}: not applicable — no path configured in context",
                metrics={
                    "threshold": min_unique,
                    "peek_samples_requested": peek_samples,
                },
            )

        try:
            samples = peek_int8_at_path(path, peek_samples=peek_samples)
        except (OSError, KeyError) as exc:
            # Caller misconfiguration: wrong path, corrupted file, or
            # unexpected HDF5 structure. Do NOT silent-pass — surface the
            # path so the operator can trace what went wrong.
            err_name = type(exc).__name__
            return HealthCheckResult(
                check_name=self.name,
                passed=False,
                reason=(f"{self.name}: peek failed at {path}: {err_name}: {exc}"),
                metrics={
                    "peek_error": err_name,
                    "attempted_path": path,
                    "file_index": file_index,
                    "threshold": min_unique,
                    "peek_samples_requested": peek_samples,
                },
            )

        unique = int(np.unique(samples).size)
        actual_peek = int(samples.shape[0])
        metrics: dict[str, float | int | str] = {
            "unique_count": unique,
            "peek_samples": actual_peek,
            "file_index": file_index,
            "threshold": min_unique,
        }
        if unique <= min_unique:
            return HealthCheckResult(
                check_name=self.name,
                passed=False,
                reason=(
                    f"{self.name}: only {unique} unique int8 values in first "
                    f"{actual_peek} samples of file_index={file_index} "
                    f"(threshold: {min_unique}). Class-127 collapse artifact — "
                    f"score would be 5.5762667 via 2^17 FP ratio."
                ),
                metrics=metrics,
            )
        return HealthCheckResult(
            check_name=self.name,
            passed=True,
            metrics=metrics,
        )
