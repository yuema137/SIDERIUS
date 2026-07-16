# execute_tools/health_checks/spectral_peak_ratio.py
"""
Per-file spectral peak ratio health check (RECORDING-ONLY).

Records PSD(peak) / median(PSD_neighborhood) for the auto-detected
spectral peak of each file's denoised output. Direct spectral analog of
what ``get_snr`` computes for scoring — records the ratio the pipeline
would see without going through the ``noise <= 1e-10`` guard or the
anchor normalisation. Useful for detecting the "phantom scored high"
case without triggering it downstream.

Uses ``find_peak`` from ``execute_tools.scoring_utils`` (same peak-finder
as production scoring), so no injected-frequency metadata is required —
the check sees exactly what the scoring pipeline would see.

RECORDING-ONLY policy (M8 §3.2 Caveat-A fix): passed=True on numeric
completion regardless of the ratio; passed=False only when every file
failed I/O.

See docs/design/collapse_detection_framework_generic.md §4 for the
recording-vs-blocking design pattern.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, Final

import numpy as np

from execute_tools.dataset_config import TIDMAD
from execute_tools.health_checks._peek import peek_int8_at_channel
from execute_tools.health_checks.schemas import HealthCheckContext, HealthCheckResult
from execute_tools.scoring_utils import find_peak

_MV_PER_LSB: float = 40.0 / 128.0
_SIG_HALF_WIDTH: Final[int] = 1  # matches get_snr sig_range
_NOISE_HALF_WIDTH: Final[int] = 50  # matches get_snr noise_range
_DEFAULT_FILE_RANGE: range = range(20)


class SpectralPeakRatioCheck:
    """Record per-file PSD peak-to-neighborhood ratio. Never blocks."""

    name: ClassVar[str] = "spectral_peak_ratio"

    _DEFAULT_PEEK_SAMPLES: ClassVar[int] = 1_000_000

    def run(
        self,
        ctx: HealthCheckContext,
        config: dict[str, Any] | None = None,
    ) -> HealthCheckResult:
        cfg = config or {}
        peek_samples = int(cfg.get("peek_samples", self._DEFAULT_PEEK_SAMPLES))
        sampling_freq = float(TIDMAD.sampling_frequency)

        files = self._resolve_files(ctx)
        if not files:
            return HealthCheckResult(
                check_name=self.name,
                passed=True,
                reason=f"{self.name}: not applicable — no files in context",
                metrics={"peek_samples_requested": peek_samples},
            )

        per_file: dict[int, float] = {}
        io_failed: dict[int, str] = {}
        for i in files:
            denoised_path = ctx.get_denoised_path(i)
            if denoised_path is None:
                io_failed[i] = "missing_path"
                continue
            try:
                ch1 = peek_int8_at_channel(denoised_path, "channel0001", peek_samples)
            except (OSError, KeyError) as exc:
                io_failed[i] = f"{type(exc).__name__}: {exc}"
                continue

            if ch1.shape[0] < 2 * _NOISE_HALF_WIDTH + 1:
                per_file[i] = float("nan")
                continue

            sig = ch1.astype(np.float64) * _MV_PER_LSB
            fft = np.fft.rfft(sig)
            psd = (1.0 / sampling_freq / len(sig)) * np.abs(fft) ** 2

            try:
                peak_idx = find_peak(psd)
            except (IndexError, ValueError):
                per_file[i] = float("nan")
                continue

            lo_sig = max(0, peak_idx - _SIG_HALF_WIDTH)
            hi_sig = min(len(psd), peak_idx + _SIG_HALF_WIDTH + 1)
            lo_win = max(0, peak_idx - _NOISE_HALF_WIDTH)
            hi_win = min(len(psd), peak_idx + _NOISE_HALF_WIDTH + 1)

            signal_win = float(np.sum(psd[lo_sig:hi_sig]))
            noise_win = float(np.sum(psd[lo_win:hi_win]) - signal_win)

            if noise_win <= 1e-10:
                per_file[i] = float("nan")
            else:
                per_file[i] = float(signal_win / noise_win)

        measured = [v for v in per_file.values() if v == v]
        metrics: dict[str, float | int | str] = {
            "n_files_measured": len(measured),
            "n_files_io_failed": len(io_failed),
            "n_files_attempted": len(files),
            "ratio_per_file_json": json.dumps({str(k): v for k, v in per_file.items()}),
            "io_failed_json": json.dumps(io_failed),
            "peek_samples_requested": peek_samples,
        }
        if measured:
            metrics["ratio_mean"] = float(np.mean(measured))
            metrics["ratio_median"] = float(np.median(measured))
            metrics["ratio_min"] = float(min(measured))
            metrics["ratio_max"] = float(max(measured))
        else:
            metrics["ratio_mean"] = float("nan")

        if not per_file and len(io_failed) == len(files):
            return HealthCheckResult(
                check_name=self.name,
                passed=False,
                reason=(
                    f"{self.name}: all {len(files)} files failed I/O; "
                    f"see io_failed_json for per-file errors"
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
        if ctx.denoised_paths:
            return sorted(ctx.denoised_paths.keys())
        if ctx.denoised_filename_fn is not None:
            return list(_DEFAULT_FILE_RANGE)
        return []
