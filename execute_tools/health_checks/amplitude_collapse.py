# execute_tools/health_checks/amplitude_collapse.py
"""
Amplitude-collapse health check (rev-6 → M9 refactor).

Catches single-bin dominance in the denoised int8 output — the failure
mode where a large fraction of samples share the same int8 class,
indicating the model has effectively "picked one output class". This is
a broader class of degeneracy than pure class-127 collapse: it flags any
peaked distribution regardless of which int8 value dominates.

Post-M9 (Strategy C): peeks one or more files (via ``peek_file_indices``
YAML config) and aggregates per-file verdicts using ``aggregation``.
The per-file metric is ``dominant_fraction = max(bincount) / n_samples``;
per-file predicate is ``dominant_fraction < collapse_threshold``.
Empty ``peek_file_indices`` → single-file fallback. Default aggregation
is ``any_pass`` — a real-learning model whose dominant class covers
< 95% on at least one peeked file passes; only a model whose EVERY
peeked file is dominated by a single class fails.

**Not to be confused with the v7 magnitude-ratio check.** The v7
(2026-04-26) collapse pattern was detected via ``mean(|file_vector|)``
vs. a reference and required a ``reference_file_vector`` in the context.
That predicate was removed entirely in commit-4b of the earlier
migration; this class operates on the int8 distribution directly, no
reference needed.

Threshold is strict (``>``, not ``>=``) per design §9.2 — a distribution
sitting exactly at the threshold is not flagged. Equivalent
post-M9 semantics: per-file passes when
``dominant_fraction < threshold`` (strict `<`).

See ``docs/design/pluggable_health_checks.md`` §9.2 and
``docs/design/m9_multi_file_peek_execution_plan.md``.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

import numpy as np

from execute_tools.deliverable_spec import default_deliverable_storage
from execute_tools.health_checks._multi_file_peek import peek_and_aggregate
from execute_tools.health_checks._view_provider import HealthView
from execute_tools.health_checks.schemas import (
    CheckInputDeclaration,
    FactRequirement,
    HealthCheckContext,
    HealthCheckResult,
    classify_verdict,
)


def _dominant_fraction(samples: np.ndarray) -> float:
    """Fraction of samples equal to the most common int8 value."""
    if samples.size == 0:
        # Empty peek — treat as fully dominated so the predicate fails.
        # The old check raised passed=False on empty peek; this preserves
        # the same failure mode when the aggregation short-circuits on
        # a single file.
        return 1.0
    _values, counts = np.unique(samples, return_counts=True)
    return float(int(counts.max()) / int(samples.shape[0]))


class AmplitudeCollapseCheck:
    """Flag denoised outputs with a single dominant int8 class."""

    name: ClassVar[str] = "amplitude_collapse"

    declaration: ClassVar[CheckInputDeclaration] = CheckInputDeclaration(
        # Dominant-symbol fraction over a prefix of the denoised CH1
        # stream. The MECHANISM is family-generic (parent design §4 class
        # B) and 08c lifts it to the categorical family; in 08a it reads
        # TIDMAD's int8 peek and declares exactly that.
        consumes_view="tidmad.int8_prefix_peek",
        required_context_inputs=("denoised_source",),
        required_facts=(FactRequirement(axis="encoding_family", equals="int8_symbol_stream"),),
        threshold_parameter_names=("collapse_threshold",),
    )

    _DEFAULT_COLLAPSE_THRESHOLD: ClassVar[float] = 0.95
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
        threshold = float(cfg.get("collapse_threshold", self._DEFAULT_COLLAPSE_THRESHOLD))
        peek_samples = int(cfg.get("peek_samples", self._DEFAULT_PEEK_SAMPLES))
        peek_file_indices = list(cfg.get("peek_file_indices", self._DEFAULT_PEEK_FILE_INDICES))
        aggregation = cfg.get("aggregation", self._DEFAULT_AGGREGATION)

        # Step 08a C5: the channel identity comes from the Deliverable
        # Contract, which owns it — resolved once per run, not spelled here.
        storage = default_deliverable_storage()

        outcome = peek_and_aggregate(
            ctx,
            peek_file_indices=peek_file_indices,
            metric_fn=_dominant_fraction,
            # Old semantic (design §9.2): "fail when dominant_fraction >
            # threshold" — equality passes. Post-M9 pass predicate is the
            # dual: "pass when dominant_fraction <= threshold".
            predicate=lambda m: m <= threshold,
            aggregation=aggregation,
            peek_samples=peek_samples,
            channel=storage.input_channel_group,
        )

        reason = ""
        if not outcome.passed:
            reason = (
                f"{self.name}: {outcome.reason} "
                f"(threshold: dominant_fraction < {threshold:g}). "
                f"Single-class dominance — the model is producing a "
                f"near-constant output."
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
            "threshold": threshold,
            "peek_samples_requested": peek_samples,
        }
        return HealthCheckResult(
            check_name=self.name,
            passed=outcome.passed,
            reason=reason,
            metrics=metrics,
            verdict=classify_verdict(passed=outcome.passed, reason=reason, metrics=metrics),
        )
