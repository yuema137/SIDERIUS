# execute_tools/health_checks/sample_dispersion_floor.py
"""
Dispersion-floor check for declared-continuous outputs (FIXTURE-SCOPED).

**This check exists to be a negative control**, and it is deliberately
referenced by NO production YAML. Step 08a makes ``inapplicable`` a real
verdict; the obvious way to get that wrong is to let it become an
EXEMPTION — a task for which the int8 family does not apply quietly
becomes a task nothing checks at all. Roadmap §8.4-C names the control
that refutes it: on the SAME declared-float output where the int8 family
reports ``inapplicable``, a check belonging to the OTHER family must FIRE
and be able to FAIL.

So this check declares ``continuous_float`` facts and is inapplicable
under TIDMAD, while the six TIDMAD checks are inapplicable under a
declared-float task. The axis cuts both ways, which is what makes it an
axis rather than an excuse.

**Scope, deliberately minimal.** The full generic continuous family — a
real view provider, real artifact reads, task-owned thresholds — is 08c.
Here the samples arrive through the check's own config, because 08a has
no view-provider mechanism yet (that is 08b) and inventing half of one to
serve a fixture would be exactly the scope creep the frozen plan forbids.
Its view key is spelled in the plugin-local style
(``step08.fixture_continuous_samples``) precisely to demonstrate in
miniature the parent design's §6.3 claim: the engine never interprets a
view key, so a key nothing in the framework has heard of works fine.

It reads no metric. Parent design §5 and the §13 guardrail forbid a new
check consuming the golden metric scalar, and nothing here goes near
``denoising_score`` or ``file_vector``.
"""

from __future__ import annotations

import math
from typing import Any, ClassVar

from execute_tools.health_checks.schemas import (
    CheckInputDeclaration,
    CheckVerdict,
    FactRequirement,
    HealthCheckContext,
    HealthCheckResult,
)


class SampleDispersionFloorCheck:
    """Flag a declared-continuous output whose samples barely vary."""

    name: ClassVar[str] = "sample_dispersion_floor"

    declaration: ClassVar[CheckInputDeclaration] = CheckInputDeclaration(
        consumes_view="step08.fixture_continuous_samples",
        required_context_inputs=(),
        required_facts=(FactRequirement(axis="encoding_family", equals="continuous_float"),),
        threshold_parameter_names=("min_dispersion",),
    )

    _DEFAULT_MIN_DISPERSION: ClassVar[float] = 0.5

    def run(
        self,
        ctx: HealthCheckContext,
        config: dict[str, Any] | None = None,
    ) -> HealthCheckResult:
        cfg = config or {}
        floor = float(cfg.get("min_dispersion", self._DEFAULT_MIN_DISPERSION))
        raw = cfg.get("samples")
        samples = [float(value) for value in raw] if isinstance(raw, list) else []

        if not samples:
            # Fail closed. A dispersion floor computed over nothing is not
            # evidence of health — it is the absence of evidence, and a
            # blocking check that cannot compute must not report a pass.
            return HealthCheckResult(
                check_name=self.name,
                passed=False,
                reason=f"{self.name}: no samples supplied; dispersion is not computable",
                metrics={"min_dispersion": floor, "n_samples": 0},
                verdict=CheckVerdict.ERROR,
            )

        mean = math.fsum(samples) / len(samples)
        variance = math.fsum((value - mean) ** 2 for value in samples) / len(samples)
        dispersion = math.sqrt(variance)
        passed = dispersion >= floor

        reason = ""
        if not passed:
            reason = (
                f"{self.name}: dispersion {dispersion:.6g} is below the floor "
                f"{floor:g} over {len(samples)} sample(s). The output barely "
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
                "n_samples": len(samples),
            },
            verdict=CheckVerdict.PASSED if passed else CheckVerdict.FAILED,
        )
