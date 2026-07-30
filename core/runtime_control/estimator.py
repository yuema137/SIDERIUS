"""Unified runtime estimator + per-run factory (C4).

One estimate-assembly path for every runtime consumer (C8 rewires them;
until then this module is additive). The estimator owns NO policy — it
produces `RuntimeEstimate` evidence; `RuntimeDecisionPolicy` decides.

Layering (C4 implementation record): nothing in ``core/`` imports
``agent.*`` at module level (the existing direction is agent→core).
Producers are DEPENDENCY-INJECTED as callables; the production wiring
helper (`production_estimator_factory`) imports the legacy producers
lazily inside the function body, keeping the module graph acyclic.

C4 producers: the legacy static formulas as typed tier-0 prior
producers (mathematics untouched — characterization-tested for numeric
parity). Historical/probe producers arrive in C6/C7 through the same
injection seams.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from core.runtime_control.decision_policy import RuntimeDecisionPolicy
from core.runtime_control.estimate_types import (
    RuntimeEstimate,
    RuntimeEstimateRequest,
    from_proposer_preflight,
)
from core.runtime_control.identity import component_identity

_ESTIMATOR_SEMVER = "1.0.0"

#: A static-prior producer prices a request WITHOUT executing anything.
#: Contract: returns the C1 advisory verdict dict shape
#: ({estimated_minutes, factor, verdict, feasible, provenance,
#: advisory_only}); the estimator wraps it via the canonical adapter.
StaticPriorProducer = Callable[[RuntimeEstimateRequest], dict[str, Any]]


class RuntimeEstimator(Protocol):
    identity: str

    def estimate(self, request: RuntimeEstimateRequest) -> RuntimeEstimate: ...


class DefaultRuntimeEstimator:
    """§8.4-ordered assembly over the configured producers.

    C4 resolution order (highest available evidence wins):
      1. (C6+) bounded live probe — not configured yet;
      2. (C7+) historical/similarity priors — not configured yet;
      3. static prior producer (tier 0) — always available.

    The returned estimate's authority is entirely type-derived: a
    static-produced estimate can never be blocking-eligible regardless
    of what a consumer does with it.
    """

    def __init__(
        self,
        *,
        static_producer: StaticPriorProducer,
        identity_payload_extra: dict[str, Any] | None = None,
    ) -> None:
        self._static_producer = static_producer
        payload = estimator_identity_payload()
        if identity_payload_extra:
            payload = {**payload, "extra": identity_payload_extra}
        self.identity = component_identity("runtime_estimator", _ESTIMATOR_SEMVER, payload)

    def estimate(self, request: RuntimeEstimateRequest) -> RuntimeEstimate:
        verdict = self._static_producer(request)
        return from_proposer_preflight(verdict)


def estimator_identity_payload() -> dict[str, Any]:
    """Behavioral payload: resolution order + the legacy static-formula
    constants that shape tier-0 estimates (policy-relevant defaults —
    a change to the formula constants changes the identity). Lazy
    imports keep core→agent out of the module graph."""
    from agent.skills.training_skill.estimator import (
        _MIN_MS_PER_STEP,
        _STATIC_MS_PER_FLOP,
        SAFETY_MULTIPLIER,
    )
    from core.inference_defaults import _DEFAULT_INFERENCE_BATCH

    return {
        "resolution_order": ["bounded_live_probe", "historical_prior", "static_prior"],
        "configured_producers": ["static_prior"],
        "static_formula_constants": {
            "static_ms_per_flop": _STATIC_MS_PER_FLOP,
            "min_ms_per_step": _MIN_MS_PER_STEP,
            "safety_multiplier": SAFETY_MULTIPLIER,
            "fallback_inference_batch": _DEFAULT_INFERENCE_BATCH,
        },
    }


class RuntimeEstimatorFactory:
    """One estimator + one policy per run (§7.1: created through a shared
    factory and passed to all runtime consumers at C8)."""

    def __init__(self, *, static_producer: StaticPriorProducer) -> None:
        self._static_producer = static_producer

    def build(self) -> tuple[DefaultRuntimeEstimator, RuntimeDecisionPolicy]:
        return (
            DefaultRuntimeEstimator(static_producer=self._static_producer),
            RuntimeDecisionPolicy(),
        )


def production_estimator_factory() -> RuntimeEstimatorFactory:
    """Production wiring: the legacy static pre-flight formula as the
    tier-0 producer (mathematics untouched — the SAME function the C1
    advisory path calls)."""

    def _static(request: RuntimeEstimateRequest) -> dict[str, Any]:
        from agent.utils.proposer_preflight import (
            estimate_proposal_time,
        )

        return estimate_proposal_time(
            model_type=request.model_identity or request.model_family or "unknown",
            model_config={"segmentation_size": request.segment_length},
            train_config={
                "batch_size": request.batch_size,
                "epochs": int(request.model_features.get("epochs", 1)),
            },
            loss_config={"loss_type": str(request.model_features.get("loss_type", "ce"))},
            num_params=request.parameter_count or 1,
            time_budget_minutes=float(request.model_features.get("time_budget_minutes", 20.0)),
        )

    return RuntimeEstimatorFactory(static_producer=_static)
