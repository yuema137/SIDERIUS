# execute_tools/health_checks/sample_dispersion_floor.py
"""Dispersion-floor check for continuous sample streams (generic family).

Born as Step 08a's §8.4-C negative control — the check proving that a task
where the int8 family is ``inapplicable`` is not thereby EXEMPT from
health. 08a had no view mechanism, so its samples arrived through the
check's own config; Step 08c upgrades it in place to the first real
consumer of the standard ``continuous_samples`` view. The 8.4-C property
survives through the view path: binding the capability IS the semantic
statement that a continuous stream exists, and a roster that names this
check without a provider for it fails closed at binding time.

**Precision ownership (§3.5a).** The PROVIDER hands over the stream in the
artifact's NATIVE floating dtype; THIS CHECK owns the estimator and
computes the population dispersion (ddof=0) under float64 accumulation —
``np.std(samples, dtype=np.float64, ddof=0)``, the NumPy equivalent of the
``math.fsum`` form this check used before the upgrade. No contract claims
concatenation upcasts anything.

Verdict boundary (§3.2a): an absent view or an EMPTY stream is ERROR (the
absence of evidence, never a pass); a stream that was read but carries a
non-finite value is FAILED (an observable deliverable pathology).

It reads no metric. Parent design §5 and the §13 guardrail forbid a check
consuming the golden metric scalar, and nothing here goes near
``denoising_score`` or ``file_vector``.
"""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np

from execute_tools.health_checks._view_provider import HealthView
from execute_tools.health_checks.schemas import (
    CheckInputDeclaration,
    CheckVerdict,
    HealthCheckContext,
    HealthCheckResult,
)
from execute_tools.health_checks.standard_views import (
    CONTINUOUS_SAMPLES,
    ContinuousSamplesPayload,
)


class SampleDispersionFloorCheck:
    """Flag a continuous output whose samples barely vary."""

    name: ClassVar[str] = "sample_dispersion_floor"

    declaration: ClassVar[CheckInputDeclaration] = CheckInputDeclaration(
        consumes_view=CONTINUOUS_SAMPLES,
        requires_view=True,
        required_context_inputs=(),
        # Deliberately NO facts (§2.11 biconditional discipline): the
        # arithmetic never reads ``encoding_family``, and requiring an axis
        # the check does not consume would make it inapplicable over a
        # property it never uses. A task like DAVIS still declares
        # ``encoding_family=continuous_float`` — that declaration's job is
        # to make incompatible int8 checks honestly inapplicable, not to
        # gate this one.
        required_facts=(),
        threshold_parameter_names=("min_dispersion",),
    )

    _DEFAULT_MIN_DISPERSION: ClassVar[float] = 0.5

    def run(
        self,
        ctx: HealthCheckContext,
        config: dict[str, Any] | None = None,
        *,
        view: HealthView | None = None,
    ) -> HealthCheckResult:
        cfg = config or {}
        floor = float(cfg.get("min_dispersion", self._DEFAULT_MIN_DISPERSION))

        def _error(reason: str, metrics: dict[str, Any]) -> HealthCheckResult:
            return HealthCheckResult(
                check_name=self.name,
                passed=False,
                reason=f"{self.name}: {reason}",
                metrics={**metrics, "min_dispersion": floor},
                verdict=CheckVerdict.ERROR,
            )

        if view is None:
            return _error(
                f"requires the {CONTINUOUS_SAMPLES!r} view and none was supplied",
                {},
            )
        if not isinstance(view.payload, ContinuousSamplesPayload):
            return _error(
                f"view payload is {type(view.payload).__name__}, expected "
                f"ContinuousSamplesPayload (provider {view.provider_id!r})",
                {},
            )
        samples = view.payload.samples
        n = int(samples.size)
        if n == 0:
            # Fail closed. A dispersion floor computed over nothing is not
            # evidence of health — it is the absence of evidence, and a
            # blocking check that cannot compute must not report a pass.
            return _error(
                "the sample stream is empty; dispersion is not computable",
                {"n_samples": 0},
            )

        finite = np.isfinite(samples)
        if not bool(finite.all()):
            bad = int(n - int(np.count_nonzero(finite)))
            first_index = int(np.argmin(finite))
            return HealthCheckResult(
                check_name=self.name,
                passed=False,
                reason=(
                    f"{self.name}: {bad} non-finite sample(s) — first at index "
                    f"{first_index} ({samples[first_index]!r}). The deliverable "
                    f"was read and it is invalid."
                ),
                metrics={
                    "n_samples": n,
                    "non_finite_samples": bad,
                    "min_dispersion": floor,
                },
                verdict=CheckVerdict.FAILED,
            )

        # Population statistic (ddof=0) under float64 accumulation — the
        # check-owned estimator (§3.5a), regardless of the stream's native
        # dtype.
        mean = float(np.mean(samples, dtype=np.float64))
        dispersion = float(np.std(samples, dtype=np.float64, ddof=0))
        passed = dispersion >= floor

        reason = ""
        if not passed:
            reason = (
                f"{self.name}: dispersion {dispersion:.6g} is below the floor "
                f"{floor:g} over {n} sample(s). The output barely "
                f"varies — a near-constant deliverable."
            )
        return HealthCheckResult(
            check_name=self.name,
            passed=passed,
            reason=reason,
            metrics={
                "dispersion": dispersion,
                "mean": mean,
                "min_dispersion": floor,
                "n_samples": n,
            },
            verdict=CheckVerdict.PASSED if passed else CheckVerdict.FAILED,
        )
