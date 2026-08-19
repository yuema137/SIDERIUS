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

from execute_tools.deliverable_spec import default_deliverable_storage
from execute_tools.health_checks._composition import VALUE_SCALE_PARAMETER
from execute_tools.health_checks._multi_file_peek import peek_and_aggregate
from execute_tools.health_checks._view_provider import HealthView
from execute_tools.health_checks.schemas import (
    CheckInputDeclaration,
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


class OutputStdCheck:
    """Reject denoised outputs whose sample std falls below a mV floor."""

    name: ClassVar[str] = "output_std"

    declaration: ClassVar[CheckInputDeclaration] = CheckInputDeclaration(
        # Dispersion floor over a prefix of the denoised CH1 stream.
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
            FactRequirement(axis="value_scale_unit"),
        ),
        threshold_parameter_names=("min_std_mv",),
    )

    _DEFAULT_MIN_STD_MV: ClassVar[float] = 1.0
    _DEFAULT_PEEK_SAMPLES: ClassVar[int] = 100_000
    _DEFAULT_PEEK_FILE_INDICES: ClassVar[list[int]] = []  # empty → single-file fallback
    _DEFAULT_AGGREGATION: ClassVar[str] = "any_pass"

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
        min_std_mv = float(cfg.get("min_std_mv", self._DEFAULT_MIN_STD_MV))
        peek_samples = int(cfg.get("peek_samples", self._DEFAULT_PEEK_SAMPLES))
        peek_file_indices = list(cfg.get("peek_file_indices", self._DEFAULT_PEEK_FILE_INDICES))
        aggregation = cfg.get("aggregation", self._DEFAULT_AGGREGATION)

        # Step 08a C5: the channel identity comes from the Deliverable
        # Contract, which owns it — resolved once per run, not spelled here.
        storage = default_deliverable_storage()

        outcome = peek_and_aggregate(
            ctx,
            peek_file_indices=peek_file_indices,
            metric_fn=lambda arr: float(np.std(arr.astype(np.float64)) * scale),
            predicate=lambda m: m >= min_std_mv,
            aggregation=aggregation,
            peek_samples=peek_samples,
            channel=storage.input_channel_group,
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

        metrics = {
            "aggregated_passed": outcome.passed,
            "aggregation": outcome.aggregation,
            "n_files_attempted": outcome.n_files_attempted,
            "n_files_io_failed": outcome.n_files_io_failed,
            "per_file": [r.model_dump() for r in outcome.per_file],
            "per_file_json": json.dumps([r.model_dump() for r in outcome.per_file]),
            "threshold_mv": min_std_mv,
            "peek_samples_requested": peek_samples,
        }
        return HealthCheckResult(
            check_name=self.name,
            passed=outcome.passed,
            reason=reason,
            metrics=metrics,
            verdict=classify_verdict(passed=outcome.passed, reason=reason, metrics=metrics),
        )
