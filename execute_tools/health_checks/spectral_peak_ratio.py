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

from execute_tools.dataset_config import resolve_dataset_profile
from execute_tools.deliverable_spec import default_deliverable_storage
from execute_tools.health_checks._composition import VALUE_SCALE_PARAMETER
from execute_tools.health_checks._peek import peek_int8_at_channel
from execute_tools.health_checks._view_provider import HealthView
from execute_tools.health_checks.schemas import (
    CheckInputDeclaration,
    CheckVerdict,
    EvidenceUnit,
    FactRequirement,
    HealthCheckContext,
    HealthCheckResult,
    classify_verdict,
)
from execute_tools.scoring_utils import find_peak

_SIG_HALF_WIDTH: Final[int] = 1  # matches get_snr sig_range
_NOISE_HALF_WIDTH: Final[int] = 50  # matches get_snr noise_range


def _value_scale(config: dict[str, Any] | None) -> float:
    """The task's numerical value scale, supplied by composition.

    Step 08b C5. This was a module-local ``_MV_PER_LSB = 40.0 / 128.0``
    literal, duplicated across four check modules and declared by nothing —
    so 08a could not require the ``value_scale_unit`` axis without flipping
    these checks to inapplicable. The number now travels with its unit from
    the task's own config, and this check DECLARES the axis, so it is only
    ever invoked when the bound task actually supplies one.

    Raises:
        KeyError: composition did not inject the scale. Deliberately fatal
            rather than defaulted: a silent fallback constant is how one
            task's millivolts get applied to another task's data.
    """
    cfg = config or {}
    if VALUE_SCALE_PARAMETER not in cfg:
        raise KeyError(
            f"{VALUE_SCALE_PARAMETER!r} missing from this check's config. It "
            f"is injected by composition for checks declaring the "
            f"'value_scale_unit' axis; running without it would mean "
            f"guessing a physical scale."
        )
    return float(cfg[VALUE_SCALE_PARAMETER])


class SpectralPeakRatioCheck:
    """Record per-file PSD peak-to-neighborhood ratio. Never blocks."""

    name: ClassVar[str] = "spectral_peak_ratio"

    _DEFAULT_PEEK_SAMPLES: ClassVar[int] = 1_000_000

    declaration: ClassVar[CheckInputDeclaration] = CheckInputDeclaration(
        # Reads ONLY the denoised CH1 stream and computes a PSD; despite
        # being a "comparison-flavoured" recording check it never touches
        # the target channel (verified end-to-end at C4 — the design's
        # expectation that it peeks the target was wrong). It does need a
        # declared sampling frequency, which it reads from the profile to
        # build the PSD axis.
        consumes_view="tidmad.int8_prefix_peek",
        required_context_inputs=("denoised_source",),
        # Step 08b C5: the millivolt scale is now TASK-owned — declared
        # once, with its unit, in the task's health config — so this check
        # REQUIRES the `value_scale_unit` axis and receives the numerical
        # factor as a parameter. Requiring the axis is what makes a task
        # that declares no physical scale yield `inapplicable` here instead
        # of silently applying someone else's millivolts.
        required_facts=(
            FactRequirement(axis="encoding_family", equals="int8_symbol_stream"),
            FactRequirement(axis="sampling_frequency_hz"),
            FactRequirement(axis="value_scale_unit"),
        ),
        # EMPTY — recording-only, no threshold. See per_file_output_std.
        # Recording-only: NO threshold row, today's honest shape (R-4).
        threshold_parameter_names=(),
        per_file_metric_name="spectral_peak_ratio",
        per_file_metrics_key="ratio_per_file",
        per_file_metric_unit=EvidenceUnit(literal="ratio"),
        sampling_method_label="channel0001_prefix_peek",
    )

    def run(
        self,
        ctx: HealthCheckContext,
        config: dict[str, Any] | None = None,
        *,
        view: HealthView | None = None,
    ) -> HealthCheckResult:
        # ``view`` is Protocol conformance only (Step 08b C3). This check
        # declares a capability key but does not REQUIRE a view — it reads
        # its own artifacts — so the runner dispatches it through the
        # unchanged ``run(ctx, config)`` path and it never receives one.
        cfg = config or {}
        scale = _value_scale(config)
        peek_samples = int(cfg.get("peek_samples", self._DEFAULT_PEEK_SAMPLES))
        sampling_freq = float(resolve_dataset_profile().dataset.sampling_frequency)

        files = self._resolve_files(ctx, cfg)
        if not files:
            # Defensive only: ``evaluate_gate`` decides applicability from
            # the declaration above BEFORE calling this check, so this path
            # is reached only by a direct (non-gate) caller.
            return HealthCheckResult(
                check_name=self.name,
                passed=True,
                reason=f"{self.name}: not applicable — no files in context",
                metrics={"peek_samples_requested": peek_samples},
                verdict=CheckVerdict.INAPPLICABLE,
            )

        # Step 08a C5: channel identity from the Deliverable Contract,
        # resolved once per run rather than spelled at the read site.
        storage = default_deliverable_storage()

        per_file: dict[int, float] = {}
        io_failed: dict[int, str] = {}
        for i in files:
            denoised_path = ctx.get_denoised_path(i)
            if denoised_path is None:
                io_failed[i] = "missing_path"
                continue
            try:
                ch1 = peek_int8_at_channel(denoised_path, storage.input_channel_group, peek_samples)
            except (OSError, KeyError) as exc:
                io_failed[i] = f"{type(exc).__name__}: {exc}"
                continue

            if ch1.shape[0] < 2 * _NOISE_HALF_WIDTH + 1:
                per_file[i] = float("nan")
                continue

            sig = ch1.astype(np.float64) * scale
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
        metrics: dict[str, Any] = {
            "n_files_measured": len(measured),
            "n_files_io_failed": len(io_failed),
            "n_files_attempted": len(files),
            "ratio_per_file": {str(k): v for k, v in per_file.items()},
            "io_failed": {str(k): v for k, v in io_failed.items()},
            "ratio_per_file_json": json.dumps({str(k): v for k, v in per_file.items()}),
            "io_failed_json": json.dumps(io_failed),
            "peek_samples_requested": peek_samples,
            "unit": "dimensionless_ratio",
            "calculation_version": "spectral_peak_ratio_v1",
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
                verdict=classify_verdict(passed=False, reason="", metrics=metrics),
            )
        return HealthCheckResult(
            check_name=self.name,
            passed=True,
            metrics=metrics,
            verdict=CheckVerdict.PASSED,
        )

    @staticmethod
    def _resolve_files(ctx: HealthCheckContext, cfg: dict[str, Any]) -> list[int]:
        """Priority: config ``peek_file_indices`` (run-level monitored set,
        DataScope-aware) > ``ctx.denoised_paths`` keys > every file the
        bound dataset declares.

        The last tier is DERIVED topology, not a declared group — the
        profile's ``num_files`` already answers "every file", and it is
        read at CALL time rather than frozen into a module-level
        ``range(20)`` at import. This module already resolves the profile
        for ``sampling_frequency``; the population now comes from the
        same declaration.
        """
        configured = cfg.get("peek_file_indices")
        if configured:
            return sorted({int(i) for i in configured})
        if ctx.denoised_paths:
            return sorted(ctx.denoised_paths.keys())
        if ctx.denoised_filename_fn is not None:
            return list(range(resolve_dataset_profile().dataset.num_files))
        return []
