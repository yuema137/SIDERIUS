# execute_tools/health_checks/pearson_dispersion.py
"""
Pearson-dispersion health check (RECORDING-ONLY).

Computes per-file pearson(CH1_denoised, CH2_target) internally, then
exposes ONLY the aggregate dispersion (sample standard deviation, ddof=1)
across the per-file values. Per-file pearson was found to be uninformative
as a per-file discriminator in the 2026-07-16 full-file scan (see
docs/design/paper_and_collapse_reference_baselines.md §6.3): time-domain
pearson is noise-limited on files 0-9 and can even produce sign-inverted
values on high-signal files for a real-learning model. The DISPERSION,
however, discriminates: FCNet gives ~0.048, paper-spec collapse gives
~0.002 — 24× separation.

RECORDING-ONLY policy (M8 §3.2 Caveat-A fix): passed=True on numeric
completion regardless of pearson_dispersion value; passed=False only
when every file failed I/O. The gate's YAML routes CONTINUE on both
branches so ``is_degenerate`` is never set by this check.

See docs/design/collapse_detection_framework_generic.md §4 for the
recording-vs-blocking design pattern.
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np

from execute_tools.health_checks._peek import peek_int8_at_channel
from execute_tools.health_checks.schemas import HealthCheckContext, HealthCheckResult

_MV_PER_LSB: float = 40.0 / 128.0
_DEFAULT_FILE_RANGE: range = range(20)  # TIDMAD NUM_FILES; via _resolve_files


class PearsonDispersionCheck:
    """Record pearson_dispersion = stdev(per_file_pearsons). Never blocks."""

    name: ClassVar[str] = "pearson_dispersion"

    _DEFAULT_PEEK_SAMPLES: ClassVar[int] = 1_000_000

    def run(
        self,
        ctx: HealthCheckContext,
        config: dict[str, Any] | None = None,
    ) -> HealthCheckResult:
        cfg = config or {}
        peek_samples = int(cfg.get("peek_samples", self._DEFAULT_PEEK_SAMPLES))

        if ctx.target_path_fn is None:
            return HealthCheckResult(
                check_name=self.name,
                passed=True,
                reason=f"{self.name}: not applicable — no target_path_fn in context",
                metrics={"peek_samples_requested": peek_samples},
            )

        files = self._resolve_files(ctx)
        if not files:
            return HealthCheckResult(
                check_name=self.name,
                passed=True,
                reason=f"{self.name}: not applicable — no files in context",
                metrics={"peek_samples_requested": peek_samples},
            )

        per_file_values: list[float] = []
        per_file: dict[str, float] = {}
        io_failed_count = 0
        for i in files:
            denoised_path = ctx.get_denoised_path(i)
            target_path = ctx.get_target_path(i)
            if denoised_path is None or target_path is None:
                io_failed_count += 1
                continue
            try:
                ch1 = peek_int8_at_channel(denoised_path, "channel0001", peek_samples)
                ch2 = peek_int8_at_channel(target_path, "channel0002", peek_samples)
            except (OSError, KeyError):
                io_failed_count += 1
                continue

            n = int(min(ch1.shape[0], ch2.shape[0]))
            if n == 0:
                io_failed_count += 1
                continue

            d = ch1[:n].astype(np.float64) * _MV_PER_LSB
            t = ch2[:n].astype(np.float64) * _MV_PER_LSB
            if float(np.std(d)) < 1e-12 or float(np.std(t)) < 1e-12:
                # Constant channel: pearson undefined; skip from dispersion.
                continue
            # ``np.corrcoef(d, t)[0, 1]`` is numerically identical to
            # ``scipy.stats.pearsonr(d, t)[0]`` — used here because
            # scipy's return type widens to ``object`` under pyright's
            # stubs and the two accessors that would recover it
            # (``.statistic``, tuple destructure) are unavailable /
            # untyped in the CI-pinned scipy version.
            r = float(np.corrcoef(d, t)[0, 1])
            if np.isfinite(r):
                per_file_values.append(r)
                per_file[str(i)] = r

        # Aggregate the dispersion (the whole point of this check).
        n_measured = len(per_file_values)
        metrics: dict[str, Any] = {
            "n_files_measured": n_measured,
            "n_files_io_failed": io_failed_count,
            "n_files_attempted": len(files),
            "peek_samples_requested": peek_samples,
            "pearson_per_file": per_file,
            "unit": "dimensionless_correlation",
            "calculation_version": "pearson_dispersion_v1",
        }
        if n_measured >= 2:
            # ddof=1 for the standard "sample stdev" — matches
            # docs/design/paper_and_collapse_reference_baselines.md §4.2.
            metrics["pearson_dispersion"] = float(np.std(per_file_values, ddof=1))
            metrics["pearson_mean"] = float(np.mean(per_file_values))
            metrics["pearson_range"] = float(max(per_file_values) - min(per_file_values))
        elif n_measured == 1:
            # Cannot compute dispersion from a single measurement; report NaN
            # so downstream consumers can distinguish "not measured" from
            # "measured as zero".
            metrics["pearson_dispersion"] = float("nan")
            metrics["pearson_mean"] = float(per_file_values[0])
            metrics["pearson_range"] = 0.0
        else:
            metrics["pearson_dispersion"] = float("nan")
            metrics["pearson_mean"] = float("nan")
            metrics["pearson_range"] = float("nan")

        if n_measured == 0 and io_failed_count == len(files):
            return HealthCheckResult(
                check_name=self.name,
                passed=False,
                reason=(
                    f"{self.name}: all {len(files)} files failed I/O; no per-file pearson computed"
                ),
                metrics=metrics,
            )
        return HealthCheckResult(
            check_name=self.name,
            passed=True,
            metrics=metrics,
        )

    @staticmethod
    def _resolve_files(ctx: HealthCheckContext) -> list[int]:
        """File-index set to measure.

        Priority: (1) explicit keys in ``ctx.denoised_paths``, (2) fall
        back to a fixed 0..19 range via ``ctx.denoised_filename_fn``,
        (3) empty list when neither is available.
        """
        if ctx.denoised_paths:
            return sorted(ctx.denoised_paths.keys())
        if ctx.denoised_filename_fn is not None:
            return list(_DEFAULT_FILE_RANGE)
        return []
