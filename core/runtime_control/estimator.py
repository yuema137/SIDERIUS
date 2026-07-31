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
from functools import lru_cache
from typing import Any, Protocol

from core.runtime_control.decision_policy import RuntimeDecisionPolicy
from core.runtime_control.estimate_types import (
    RuntimeEstimate,
    RuntimeEstimateRequest,
    evidence_rank,
    from_proposer_preflight,
)
from core.runtime_control.identity import component_identity

_ESTIMATOR_SEMVER = "1.0.0"

#: A static-prior producer prices a request WITHOUT executing anything.
#: Contract: returns the C1 advisory verdict dict shape
#: ({estimated_minutes, factor, verdict, feasible, provenance,
#: advisory_only}); the estimator wraps it via the canonical adapter.
StaticPriorProducer = Callable[[RuntimeEstimateRequest], dict[str, Any]]


#: A lookup producer prices a request from EXISTING evidence (a probe
#: record, the calibration registry, historical observations). Returns
#: None when it holds nothing applicable — absence is a gap, never a
#: fabricated estimate.
EvidenceLookup = Callable[[RuntimeEstimateRequest], RuntimeEstimate | None]


class RuntimeEstimator(Protocol):
    identity: str

    def estimate(
        self,
        request: RuntimeEstimateRequest,
        *,
        caller_measurement: RuntimeEstimate | None = ...,
    ) -> RuntimeEstimate: ...


class DefaultRuntimeEstimator:
    """§8.4-ordered assembly over every configured evidence source (C9a).

    Resolution order — the HIGHEST-RANKED available evidence wins, and
    measurement-backed evidence is NEVER downgraded to a prior:

      1. caller-supplied in-process measurement (TimeEval's warmup, RT2's
         verification — the caller already ran the workload);
      2. bounded live probe observation (C6/C9b);
      3. validated local calibration / historical prior (C5/C7 registry);
      4. static prior producer (tier 0) — always available, last.

    Ranking uses `evidence_rank` on the canonical provenance vocabulary,
    so the order is a property of the EVIDENCE, not of the call site: a
    consumer cannot promote a prior by passing it in a stronger slot,
    and cannot demote a measurement by passing it in a weaker one.

    The returned estimate's authority remains entirely type-derived.
    """

    def __init__(
        self,
        *,
        static_producer: StaticPriorProducer,
        probe_lookup: EvidenceLookup | None = None,
        history_lookup: EvidenceLookup | None = None,
        identity_payload_extra: dict[str, Any] | None = None,
    ) -> None:
        self._static_producer = static_producer
        self._probe_lookup = probe_lookup
        self._history_lookup = history_lookup
        payload = estimator_identity_payload(
            probe_lookup=probe_lookup is not None,
            history_lookup=history_lookup is not None,
        )
        if identity_payload_extra:
            payload = {**payload, "extra": identity_payload_extra}
        self.identity = component_identity("runtime_estimator", _ESTIMATOR_SEMVER, payload)

    def estimate(
        self,
        request: RuntimeEstimateRequest,
        *,
        caller_measurement: RuntimeEstimate | None = None,
    ) -> RuntimeEstimate:
        """Assemble the best available evidence for ``request``.

        ``caller_measurement`` is evidence the caller measured itself. It
        is ranked, not trusted: a caller that passes a static estimate
        here gets static authority, because eligibility is derived from
        provenance.
        """
        candidates: list[tuple[str, RuntimeEstimate]] = []
        if caller_measurement is not None:
            candidates.append(("caller_measurement", caller_measurement))
        for name, lookup in (
            ("probe", self._probe_lookup),
            ("history", self._history_lookup),
        ):
            if lookup is None:
                continue
            found = lookup(request)
            if found is not None:
                candidates.append((name, found))
        candidates.append(("static", from_proposer_preflight(self._static_producer(request))))

        # Deterministic: highest evidence tier wins; ties broken by the
        # source order above (earlier = closer to this workload).
        _, (best_name, best) = max(
            enumerate(candidates),
            key=lambda item: (evidence_rank(item[1][1].provenance), -item[0]),
        )
        considered = ", ".join(
            f"{name}({estimate.provenance}, tier {evidence_rank(estimate.provenance)})"
            for name, estimate in candidates
        )
        note = f"assembled by {self.identity}: chose {best_name}; considered {considered}"
        return best.model_copy(update={"warnings": (*best.warnings, note)})


def estimator_identity_payload(
    *, probe_lookup: bool = False, history_lookup: bool = False
) -> dict[str, Any]:
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
        "resolution_order": [
            "caller_measurement",
            "bounded_live_probe",
            "historical_prior",
            "static_prior",
        ],
        "configured_producers": [
            *(["probe_lookup"] if probe_lookup else []),
            *(["history_lookup"] if history_lookup else []),
            "static_prior",
        ],
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

    def __init__(
        self,
        *,
        static_producer: StaticPriorProducer,
        probe_lookup: EvidenceLookup | None = None,
        history_lookup: EvidenceLookup | None = None,
    ) -> None:
        self._static_producer = static_producer
        self._probe_lookup = probe_lookup
        self._history_lookup = history_lookup

    def build(self) -> tuple[DefaultRuntimeEstimator, RuntimeDecisionPolicy]:
        return (
            DefaultRuntimeEstimator(
                static_producer=self._static_producer,
                probe_lookup=self._probe_lookup,
                history_lookup=self._history_lookup,
            ),
            RuntimeDecisionPolicy(),
        )


@lru_cache(maxsize=1)
def shared_runtime_components() -> tuple[DefaultRuntimeEstimator, RuntimeDecisionPolicy]:
    """The ONE estimator + policy pair for this process (C8g).

    §7.1 requires every runtime consumer to resolve the same factory, so
    that a decision made in the proposer and a decision made at the
    pre-flight gate are demonstrably the same subsystem — same estimator
    identity, same policy identity, same vocabulary. Consumers call this
    instead of constructing their own ``RuntimeDecisionPolicy()``.

    Cached per process: both objects are stateless and identity-stable,
    so sharing them costs nothing and makes divergence impossible rather
    than merely unlikely.

    KNOWN LIMITATION (C8 closure audit, 2026-07-30): the estimator object
    itself currently resolves only the tier-0 static producer, so
    consumers that already hold BETTER evidence — TimeEval's warmup
    measurement, RT2's in-process verification, a C6 probe record —
    assemble their estimate through the canonical adapters in
    ``estimate_types`` rather than by calling ``estimator.estimate()``.
    Routing them through the estimator would today DOWNGRADE measured
    evidence to a static prior. Making the estimator accept
    caller-supplied measured evidence and resolve §8.4 precedence over
    {probe record, registry history, caller measurement, static} is the
    remaining half of "one subsystem" and is tracked as C9 scope.
    """
    return production_estimator_factory().build()


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
