# execute_tools/health_checks/amplitude_collapse.py
"""
Amplitude-collapse health check (rev-6, distribution-based).

Catches single-bin dominance in the denoised int8 output — the failure
mode where a large fraction of samples share the same int8 class,
indicating the model has effectively "picked one output class". This is
a broader class of degeneracy than pure class-127 collapse: it flags any
peaked distribution regardless of which int8 value dominates.

Mechanism: peek the first available denoised HDF5's ``channel0001``,
compute the histogram of unique int8 values with counts, and check
whether the most common value's count exceeds ``collapse_threshold *
total_samples``. When yes, flag as ``passed=False``.

**Not to be confused with the v7 magnitude-ratio check.** The v7
(2026-04-26) collapse pattern was detected via ``mean(|file_vector|)``
vs. a reference and required a ``reference_file_vector`` in the context.
That predicate was removed entirely in commit-4b of this migration
(along with its back-compat shim ``execute_tools/squid_health_checks.py``,
which had zero non-test callers). The rev-6 ``HealthCheckContext`` also
no longer carries ``reference_file_vector`` (per commit-1 D2), so there
is no way to reconstruct the old semantic. This class operates on the
int8 distribution directly, no reference needed.

Rev-6 note: conforms to the ``HealthCheckSkill`` Protocol (§6). Same
failure-mode taxonomy as ``OutputDiversityCheck``:
    * ``get_denoised_path`` returns None → passed=True with "not
      applicable" reason. The only legitimate silent-pass case.
    * OSError / KeyError on peek → passed=False with the attempted path
      baked into the reason.
    * Peek returns 0 samples → passed=False with "empty peek" reason
      (AMB-4b-EMPTY → A: caller misconfiguration surfaces).
    * Peek succeeds and dominant_fraction > threshold → passed=False.
    * Otherwise → passed=True.

Threshold is strict (``>``, not ``>=``) per design §9.2 — a distribution
sitting exactly at the threshold is not flagged.

See ``docs/design/pluggable_health_checks.md`` §9.2.
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np

from execute_tools.health_checks._peek import choose_peek_file_index, peek_int8_at_path
from execute_tools.health_checks.schemas import HealthCheckContext, HealthCheckResult


class AmplitudeCollapseCheck:
    """Flag denoised outputs with a single dominant int8 class."""

    name: ClassVar[str] = "amplitude_collapse"

    _DEFAULT_COLLAPSE_THRESHOLD: ClassVar[float] = 0.95
    _DEFAULT_PEEK_SAMPLES: ClassVar[int] = 100_000

    def run(
        self,
        ctx: HealthCheckContext,
        config: dict[str, Any] | None = None,
    ) -> HealthCheckResult:
        cfg = config or {}
        threshold = float(cfg.get("collapse_threshold", self._DEFAULT_COLLAPSE_THRESHOLD))
        peek_samples = int(cfg.get("peek_samples", self._DEFAULT_PEEK_SAMPLES))

        file_index = choose_peek_file_index(ctx)
        path = ctx.get_denoised_path(file_index)
        if path is None:
            # AMB-4-3 / rev-6 §6: the only legitimate "not applicable" case.
            return HealthCheckResult(
                check_name=self.name,
                passed=True,
                reason=f"{self.name}: not applicable — no path configured in context",
                metrics={
                    "threshold": threshold,
                    "peek_samples_requested": peek_samples,
                },
            )

        try:
            samples = peek_int8_at_path(path, peek_samples=peek_samples)
        except (OSError, KeyError) as exc:
            # Caller misconfiguration — surface the path.
            err_name = type(exc).__name__
            return HealthCheckResult(
                check_name=self.name,
                passed=False,
                reason=f"{self.name}: peek failed at {path}: {err_name}: {exc}",
                metrics={
                    "peek_error": err_name,
                    "attempted_path": path,
                    "file_index": file_index,
                    "threshold": threshold,
                    "peek_samples_requested": peek_samples,
                },
            )

        actual_peek = int(samples.shape[0])
        if actual_peek == 0:
            # AMB-4b-EMPTY → A: empty peek is caller misconfiguration
            # (peek_samples=0 or truncated dataset). Not a silent-pass case.
            return HealthCheckResult(
                check_name=self.name,
                passed=False,
                reason=(
                    f"{self.name}: peek returned 0 samples "
                    f"(peek_samples_requested={peek_samples}, path={path})"
                ),
                metrics={
                    "peek_samples": 0,
                    "file_index": file_index,
                    "threshold": threshold,
                    "attempted_path": path,
                },
            )

        # np.unique(return_counts=True) sorts values ascending; argmax
        # returns the smallest int8 on a tie (deterministic tie-break).
        values, counts = np.unique(samples, return_counts=True)
        dominant_idx = int(np.argmax(counts))
        dominant_class = int(values[dominant_idx])
        dominant_count = int(counts[dominant_idx])
        dominant_fraction = float(dominant_count / actual_peek)

        metrics: dict[str, float | int | str] = {
            "dominant_class": dominant_class,
            "dominant_fraction": dominant_fraction,
            "peek_samples": actual_peek,
            "file_index": file_index,
            "threshold": threshold,
        }

        # Strict `>` per design §9.2: exactly at threshold does NOT trip.
        if dominant_fraction > threshold:
            return HealthCheckResult(
                check_name=self.name,
                passed=False,
                reason=(
                    f"{self.name}: dominant class {dominant_class} covers "
                    f"{dominant_fraction * 100:.2f}% of {actual_peek} peeked "
                    f"samples of file_index={file_index} "
                    f"(threshold: {threshold * 100:.1f}%)."
                ),
                metrics=metrics,
            )
        return HealthCheckResult(
            check_name=self.name,
            passed=True,
            metrics=metrics,
        )
