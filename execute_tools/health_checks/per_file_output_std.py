# execute_tools/health_checks/per_file_output_std.py
"""
Per-file output-std health check (RECORDING-ONLY).

Complements ``OutputStdCheck`` (blocking, single-file peek) with per-file
granularity for diagnosis. Records ``std_mv`` for every file the context
knows about; never blocks. Useful for detecting the rare "collapse on
half the files, healthy on the other half" pattern that a single-file
peek would miss.

RECORDING-ONLY policy (M8 §3.2 Caveat-A fix): passed=True on numeric
completion regardless of measured std distribution; passed=False only
when every file failed I/O.

See docs/design/collapse_detection_framework_generic.md §4 for the
recording-vs-blocking design pattern.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

import numpy as np

from execute_tools.dataset_config import resolve_dataset_profile
from execute_tools.deliverable_spec import default_deliverable_storage
from execute_tools.health_checks._composition import (
    VALUE_SCALE_PARAMETER,
    VALUE_SCALE_UNIT_PARAMETER,
)
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


class PerFileOutputStdCheck:
    """Record per-file output-std distribution. Never blocks."""

    name: ClassVar[str] = "per_file_output_std"

    _DEFAULT_PEEK_SAMPLES: ClassVar[int] = 100_000

    declaration: ClassVar[CheckInputDeclaration] = CheckInputDeclaration(
        # Per-FILE dispersion diagnostics: it needs the denoised stream, an
        # int8 alphabet, and a task whose deliverable is split across a
        # file group at all — a single-artifact task has no per-file
        # structure for this to describe.
        # Step 08b C5: the millivolt scale is now TASK-owned — declared
        # once, with its unit, in the task's health config — so this check
        # REQUIRES the `value_scale_unit` axis and receives the numerical
        # factor as a parameter. Requiring the axis is what makes a task
        # that declares no physical scale yield `inapplicable` here instead
        # of silently applying someone else's millivolts.
        consumes_view="tidmad.int8_prefix_peek",
        required_context_inputs=("denoised_source",),
        required_facts=(
            FactRequirement(axis="encoding_family", equals="int8_symbol_stream"),
            FactRequirement(axis="file_group_size"),
            FactRequirement(axis="value_scale_unit"),
        ),
        # EMPTY, and deliberately so: this check is recording-only. It
        # applies no threshold — it passes on numeric completion and
        # fails only when every file failed I/O. `peek_samples` is a
        # config parameter it reads, not a threshold, and declaring it
        # here would hand 08b a mis-classified ownership migration.
        # Recording-only: NO threshold row, today's honest shape (R-4).
        threshold_parameter_names=(),
        per_file_metric_name="output_std_mv",
        per_file_metrics_key="std_mv_per_file",
        per_file_metric_unit=EvidenceUnit(config_key=VALUE_SCALE_UNIT_PARAMETER),
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

            per_file[i] = float(np.std(ch1.astype(np.float64)) * scale)

        measured = list(per_file.values())
        metrics: dict[str, Any] = {
            "n_files_measured": len(measured),
            "n_files_io_failed": len(io_failed),
            "n_files_attempted": len(files),
            "std_mv_per_file": {str(k): v for k, v in per_file.items()},
            "io_failed": {str(k): v for k, v in io_failed.items()},
            "std_mv_per_file_json": json.dumps({str(k): v for k, v in per_file.items()}),
            "io_failed_json": json.dumps(io_failed),
            "peek_samples_requested": peek_samples,
            "unit": "mV",
            "calculation_version": "per_file_output_std_v1",
        }
        if measured:
            metrics["std_mv_mean"] = float(np.mean(measured))
            metrics["std_mv_median"] = float(np.median(measured))
            metrics["std_mv_min"] = float(min(measured))
            metrics["std_mv_max"] = float(max(measured))
        else:
            metrics["std_mv_mean"] = float("nan")

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
        ``range(20)`` at import.
        """
        configured = cfg.get("peek_file_indices")
        if configured:
            return sorted({int(i) for i in configured})
        if ctx.denoised_paths:
            return sorted(ctx.denoised_paths.keys())
        if ctx.denoised_filename_fn is not None:
            return list(range(resolve_dataset_profile().partition_count))
        return []
