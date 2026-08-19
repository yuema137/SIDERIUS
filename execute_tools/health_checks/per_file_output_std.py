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
from execute_tools.health_checks._peek import peek_int8_at_channel
from execute_tools.health_checks.schemas import (
    CheckInputDeclaration,
    CheckVerdict,
    FactRequirement,
    HealthCheckContext,
    HealthCheckResult,
    classify_verdict,
)

_MV_PER_LSB: float = 40.0 / 128.0


class PerFileOutputStdCheck:
    """Record per-file output-std distribution. Never blocks."""

    name: ClassVar[str] = "per_file_output_std"

    declaration: ClassVar[CheckInputDeclaration] = CheckInputDeclaration(
        # Per-FILE dispersion diagnostics: it needs the denoised stream, an
        # int8 alphabet, and a task whose deliverable is split across a
        # file group at all — a single-artifact task has no per-file
        # structure for this to describe. The mV conversion is check-local
        # (see output_std) and is deliberately not a declared fact.
        consumes_view="tidmad.int8_prefix_peek",
        required_context_inputs=("denoised_source",),
        required_facts=(
            FactRequirement(axis="encoding_family", equals="int8_symbol_stream"),
            FactRequirement(axis="file_group_size"),
        ),
        # EMPTY, and deliberately so: this check is recording-only. It
        # applies no threshold — it passes on numeric completion and
        # fails only when every file failed I/O. `peek_samples` is a
        # config parameter it reads, not a threshold, and declaring it
        # here would hand 08b a mis-classified ownership migration.
        threshold_parameter_names=(),
    )

    _DEFAULT_PEEK_SAMPLES: ClassVar[int] = 100_000

    def run(
        self,
        ctx: HealthCheckContext,
        config: dict[str, Any] | None = None,
    ) -> HealthCheckResult:
        cfg = config or {}
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

            per_file[i] = float(np.std(ch1.astype(np.float64)) * _MV_PER_LSB)

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
            return list(range(resolve_dataset_profile().dataset.num_files))
        return []
