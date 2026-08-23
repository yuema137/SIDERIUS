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


class PearsonDispersionCheck:
    """Record pearson_dispersion = stdev(per_file_pearsons). Never blocks."""

    name: ClassVar[str] = "pearson_dispersion"

    _DEFAULT_PEEK_SAMPLES: ClassVar[int] = 1_000_000

    declaration: ClassVar[CheckInputDeclaration] = CheckInputDeclaration(
        # The only check that reads BOTH channels: denoised CH1 against
        # target CH2, per file, then reports the dispersion of the per-file
        # correlations. It therefore needs a target source as well as a
        # denoised one, and a file group to disperse across.
        consumes_view="tidmad.target_comparison_peek",
        required_context_inputs=("denoised_source", "target_source"),
        # Step 08b C5: the millivolt scale is now TASK-owned — declared
        # once, with its unit, in the task's health config — so this check
        # REQUIRES the `value_scale_unit` axis and receives the numerical
        # factor as a parameter. Requiring the axis is what makes a task
        # that declares no physical scale yield `inapplicable` here instead
        # of silently applying someone else's millivolts.
        required_facts=(
            FactRequirement(axis="encoding_family", equals="int8_symbol_stream"),
            FactRequirement(axis="file_group_size"),
            FactRequirement(axis="value_scale_unit"),
        ),
        # EMPTY — recording-only, no threshold. See per_file_output_std.
        # Recording-only: NO threshold row, today's honest shape (R-4).
        threshold_parameter_names=(),
        per_file_metric_name="pearson_correlation",
        per_file_metrics_key="pearson_per_file",
        per_file_metric_unit=EvidenceUnit(literal="correlation"),
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

        if ctx.target_path_fn is None:
            # Defensive only: the declaration above names ``target_source``,
            # so ``evaluate_gate`` returns an inapplicable verdict without
            # calling this check. Reached only by a direct caller.
            return HealthCheckResult(
                check_name=self.name,
                passed=True,
                reason=f"{self.name}: not applicable — no target_path_fn in context",
                metrics={"peek_samples_requested": peek_samples},
                verdict=CheckVerdict.INAPPLICABLE,
            )

        files = self._resolve_files(ctx, cfg)
        if not files:
            # Defensive only — see above.
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
                ch1 = peek_int8_at_channel(denoised_path, storage.input_channel_group, peek_samples)
                ch2 = peek_int8_at_channel(target_path, storage.target_channel_group, peek_samples)
            except (OSError, KeyError):
                io_failed_count += 1
                continue

            n = int(min(ch1.shape[0], ch2.shape[0]))
            if n == 0:
                io_failed_count += 1
                continue

            d = ch1[:n].astype(np.float64) * scale
            t = ch2[:n].astype(np.float64) * scale
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
        """File-index set to measure.

        Priority: (1) explicit ``peek_file_indices`` in the check config —
        the run-level monitored-file set (DataScope-aware; see
        docs/design/enable_partial_file_list.md), (2) explicit keys in
        ``ctx.denoised_paths``, (3) fall back to every file the bound
        dataset declares, via ``ctx.denoised_filename_fn``, (4) empty list
        when none is available.

        Tier 3 is "every file". That is DERIVED topology, not a declared
        group: the profile's ``num_files`` already answers it, and adding
        an ``all_files`` declaration would create a second authority for
        something Step 02a already owns. Resolved at CALL time — the
        module-level ``range(20)`` this replaced was evaluated at import,
        before any task could be bound.
        """
        configured = cfg.get("peek_file_indices")
        if configured:
            return sorted({int(i) for i in configured})
        if ctx.denoised_paths:
            return sorted(ctx.denoised_paths.keys())
        if ctx.denoised_filename_fn is not None:
            return list(range(resolve_dataset_profile().partition_count))
        return []
