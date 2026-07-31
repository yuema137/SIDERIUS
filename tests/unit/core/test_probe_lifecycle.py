"""C9a/C9b — shared evidence assembly and the REQUEST_PROBE lifecycle.

C9a: the estimator must rank every evidence source it is given and never
downgrade a measurement to a prior.

C9b: REQUEST_PROBE must RESOLVE — exactly one probe, persisted, consumed,
re-decided — and must be structurally incapable of looping.
"""

from __future__ import annotations

import pytest

from core.runtime_control.decision_policy import (
    RuntimeBudget,
    RuntimeDecisionPolicy,
    RuntimeMode,
)
from core.runtime_control.estimate_types import (
    RuntimeEstimateRequest,
    make_estimate,
)
from core.runtime_control.estimator import DefaultRuntimeEstimator
from core.runtime_control.probe import ContentionSnapshot, ProbeCaps, ProbeResult
from core.runtime_control.probe_lifecycle import (
    ProbeInfrastructureError,
    ProbeRequest,
    ProbeResolver,
)

FORMAL = RuntimeMode(phase="formal", candidate_stage="post_implementation")
TRIAL = RuntimeMode(phase="trial", candidate_stage="post_implementation")
BUDGET = RuntimeBudget(time_seconds=600.0)

REQUEST = RuntimeEstimateRequest(
    phase="formal",
    operation="training",
    model_identity="candidate_x",
    parameter_count=45_408,
    parameter_count_realized=True,
    batch_size=8,
    segment_length=40_000,
    train_steps=1000,
    inference_batches=100,
)


def _static(_request) -> dict:
    return {
        "estimated_minutes": 5.0,
        "factor": 0.5,
        "verdict": "static",
        "feasible": True,
        "provenance": "static_uncalibrated",
        "advisory_only": True,
    }


def _probe_estimate(seconds: float = 120.0):
    return make_estimate(
        provenance="bounded_live_probe",
        confidence="medium",
        expected_seconds=seconds,
        concurrency_identity="single_candidate_idle",
    )


def _history_estimate(seconds: float = 90.0):
    return make_estimate(
        provenance="historical_observation_prior",
        confidence="low",
        expected_seconds=seconds,
    )


def _verification_estimate(seconds: float = 100.0):
    return make_estimate(
        provenance="real_training_verification",
        confidence="high",
        expected_seconds=seconds,
        verification_passed=True,
        steady_state=True,
        concurrency_identity="single_candidate_idle",
    )


class TestSharedEvidenceAssembly:
    def test_static_only_when_nothing_else_is_configured(self):
        est = DefaultRuntimeEstimator(static_producer=_static)
        result = est.estimate(REQUEST)
        assert result.provenance == "static_uncalibrated"
        assert result.blocking_eligible is False
        assert any("chose static" in w for w in result.warnings)

    def test_probe_beats_history_and_static(self):
        est = DefaultRuntimeEstimator(
            static_producer=_static,
            probe_lookup=lambda _r: _probe_estimate(),
            history_lookup=lambda _r: _history_estimate(),
        )
        result = est.estimate(REQUEST)
        assert result.provenance == "bounded_live_probe"
        assert result.blocking_eligible is True
        assert "history(historical_observation_prior, tier 1)" in result.warnings[-1]

    def test_history_beats_static(self):
        est = DefaultRuntimeEstimator(
            static_producer=_static, history_lookup=lambda _r: _history_estimate()
        )
        assert est.estimate(REQUEST).provenance == "historical_observation_prior"

    def test_caller_measurement_is_never_downgraded_to_static(self):
        """The C8 gap: routing a measured consumer through the estimator
        must not turn its measurement into a prior."""
        est = DefaultRuntimeEstimator(static_producer=_static)
        result = est.estimate(REQUEST, caller_measurement=_verification_estimate())
        assert result.provenance == "real_training_verification"
        assert result.blocking_eligible is True
        assert result.expected_seconds == 100.0

    def test_verification_outranks_a_probe(self):
        est = DefaultRuntimeEstimator(
            static_producer=_static, probe_lookup=lambda _r: _probe_estimate()
        )
        result = est.estimate(REQUEST, caller_measurement=_verification_estimate())
        assert result.provenance == "real_training_verification"

    def test_a_prior_passed_as_caller_measurement_gets_prior_authority(self):
        """Rank is a property of the EVIDENCE, not of the slot it arrives
        in — a consumer cannot promote a prior by passing it here."""
        est = DefaultRuntimeEstimator(
            static_producer=_static, probe_lookup=lambda _r: _probe_estimate()
        )
        result = est.estimate(REQUEST, caller_measurement=_history_estimate())
        assert result.provenance == "bounded_live_probe"  # the probe still wins

    def test_absent_lookups_are_gaps_not_fabrications(self):
        est = DefaultRuntimeEstimator(
            static_producer=_static,
            probe_lookup=lambda _r: None,
            history_lookup=lambda _r: None,
        )
        result = est.estimate(REQUEST)
        assert result.provenance == "static_uncalibrated"
        assert "probe(" not in result.warnings[-1]

    def test_configured_producers_change_the_estimator_identity(self):
        bare = DefaultRuntimeEstimator(static_producer=_static)
        wired = DefaultRuntimeEstimator(static_producer=_static, probe_lookup=lambda _r: None)
        assert bare.identity != wired.identity
        assert wired.identity.startswith("runtime_estimator@")


# ── C9b ─────────────────────────────────────────────────────────────────────

CAPS = ProbeCaps()
IDLE = ContentionSnapshot(telemetry_available=True, foreign_compute_processes=0)


def _result(status: str, **over) -> ProbeResult:
    from core.runtime_control.probe import RealizedModelProperties

    base = dict(
        status=status,
        model_identity="candidate_x",
        realized=RealizedModelProperties(
            parameter_count=45_408,
            trainable_parameter_count=45_408,
            parameter_memory_gb=0.001,
            dtype="float32",
        ),
        setup_seconds=1.0,
        train_ms_per_step=20.0,
        train_ms_spread=(19.0, 21.0),
        inference_ms_per_batch=40.0,
        inference_ms_spread=(39.0, 41.0),
        concurrency_identity="single_candidate_idle",
        contention=IDLE,
        caps=CAPS,
        wall_seconds=12.0,
    )
    base.update(over)
    return ProbeResult(**base)


def _resolver(run_probe, persist=None) -> ProbeResolver:
    return ProbeResolver(policy=RuntimeDecisionPolicy(), run_probe=run_probe, persist=persist)


PROBE_REQUEST = ProbeRequest(model_identity="candidate_x", train_steps=1000, inference_batches=100)


class TestRequestProbeResolution:
    def test_clean_probe_within_budget_allows(self):
        calls = []
        resolver = _resolver(lambda req: (calls.append(req), _result("ok"))[1])
        resolution = resolver.resolve(PROBE_REQUEST, budget=BUDGET, mode=FORMAL)
        # 1 s setup + 1000 × 20 ms + 100 × 40 ms = 25 s, inside 600 s
        assert resolution.decision.kind == "ALLOW"
        assert resolution.probe_ran is True
        assert resolution.estimate is not None
        assert resolution.estimate.provenance == "bounded_live_probe"
        assert len(calls) == 1

    def test_clean_probe_over_budget_rejects_on_the_optimistic_bound(self):
        # The spread must be consistent with the rate: the estimate model
        # enforces lower <= expected <= upper, so a fixture that raises the
        # median without moving the spread is invalid input, not a case.
        resolver = _resolver(
            lambda _r: _result("ok", train_ms_per_step=5000.0, train_ms_spread=(4900.0, 5100.0))
        )
        resolution = resolver.resolve(
            PROBE_REQUEST, budget=RuntimeBudget(time_seconds=10.0), mode=FORMAL
        )
        assert resolution.decision.kind == "REJECT"

    def test_measured_oom_rejects_the_candidate(self):
        resolver = _resolver(lambda _r: _result("oom", error="CUDA OOM", peak_vram_gb=31.0))
        resolution = resolver.resolve(PROBE_REQUEST, budget=BUDGET, mode=FORMAL)
        assert resolution.decision.kind == "REJECT"
        assert resolution.probe_status == "oom"
        assert any("measured oom" in r for r in resolution.decision.reasons)

    def test_measured_wall_cap_rejects_the_candidate(self):
        resolver = _resolver(lambda _r: _result("wall_cap", error="cap hit"))
        assert resolver.resolve(PROBE_REQUEST, budget=BUDGET, mode=FORMAL).decision.kind == (
            "REJECT"
        )

    def test_load_failure_is_an_abort_not_a_candidate_verdict(self):
        resolver = _resolver(lambda _r: _result("load_failure", error="plugin import failed"))
        resolution = resolver.resolve(PROBE_REQUEST, budget=BUDGET, mode=FORMAL)
        assert resolution.decision.kind == "ABORT"
        assert "did not produce evidence" in resolution.decision.reasons[0]

    def test_infrastructure_error_is_an_abort(self):
        def _boom(_r):
            raise ProbeInfrastructureError("no CUDA device visible")

        resolution = _resolver(_boom).resolve(PROBE_REQUEST, budget=BUDGET, mode=FORMAL)
        assert resolution.decision.kind == "ABORT"
        assert "could not be attempted" in resolution.decision.reasons[0]
        assert resolution.probe_ran is False

    def test_unexpected_error_is_also_an_abort_never_a_static_fallback(self):
        def _boom(_r):
            raise KeyError("model_type")

        resolution = _resolver(_boom).resolve(PROBE_REQUEST, budget=BUDGET, mode=FORMAL)
        assert resolution.decision.kind == "ABORT"
        assert resolution.decision.evidence_provenance != "static_uncalibrated"

    def test_persistence_failure_aborts_rather_than_deciding_unrecorded(self):
        def _bad_persist(_result, _request):
            raise OSError("registry read-only")

        resolver = _resolver(lambda _r: _result("ok"), persist=_bad_persist)
        resolution = resolver.resolve(PROBE_REQUEST, budget=BUDGET, mode=FORMAL)
        assert resolution.decision.kind == "ABORT"
        assert "could not be persisted" in resolution.decision.reasons[0]

    def test_observations_are_persisted_and_reported(self):
        resolver = _resolver(
            lambda _r: _result("ok"), persist=lambda _res, _req: ("sha256:aa", "sha256:bb")
        )
        resolution = resolver.resolve(PROBE_REQUEST, budget=BUDGET, mode=FORMAL)
        assert resolution.observation_ids == ("sha256:aa", "sha256:bb")
        assert resolution.decision.kind == "ALLOW"


class TestExactlyOnceAndNoLoop:
    def test_the_probe_runs_exactly_once_per_attempt(self):
        calls = []
        resolver = _resolver(lambda req: (calls.append(req), _result("ok"))[1])
        resolver.resolve(PROBE_REQUEST, budget=BUDGET, mode=FORMAL)
        second = resolver.resolve(PROBE_REQUEST, budget=BUDGET, mode=FORMAL)
        assert len(calls) == 1  # not re-run
        assert second.decision.kind == "ABORT"
        assert "already completed" in second.decision.reasons[0]

    def test_a_failed_probe_is_not_retried(self):
        calls = []

        def _boom(req):
            calls.append(req)
            raise ProbeInfrastructureError("gone")

        resolver = _resolver(_boom)
        assert resolver.resolve(PROBE_REQUEST, budget=BUDGET, mode=FORMAL).decision.kind == (
            "ABORT"
        )
        assert resolver.probe_completed is True
        assert resolver.resolve(PROBE_REQUEST, budget=BUDGET, mode=FORMAL).decision.kind == (
            "ABORT"
        )
        assert len(calls) == 1

    def test_a_policy_that_still_requests_a_probe_is_an_invariant_failure(self):
        """If the re-decision ever returned REQUEST_PROBE again, the system
        would spin. It is caught and converted to ABORT instead."""

        class _StuckPolicy(RuntimeDecisionPolicy):
            def decide(self, *a, **k):  # type: ignore[override]
                from core.runtime_control.decision_policy import RuntimeDecision

                return RuntimeDecision(
                    kind="REQUEST_PROBE",
                    reasons=("stuck",),
                    evidence_provenance="bounded_live_probe",
                    evidence_rank=2,
                )

        resolver = ProbeResolver(policy=_StuckPolicy(), run_probe=lambda _r: _result("ok"))
        resolution = resolver.resolve(PROBE_REQUEST, budget=BUDGET, mode=FORMAL)
        assert resolution.decision.kind == "ABORT"
        assert "not consumed" in resolution.decision.reasons[0]

    def test_resolution_never_returns_request_probe(self):
        """The whole contract in one assertion, over every probe outcome."""
        for status in ("ok", "oom", "wall_cap", "load_failure"):
            resolver = _resolver(lambda _r, s=status: _result(s, error="e"))
            kind = resolver.resolve(PROBE_REQUEST, budget=BUDGET, mode=FORMAL).decision.kind
            assert kind in ("ALLOW", "REJECT", "ABORT"), (status, kind)


class TestTrialModeUnaffected:
    def test_trial_probe_resolution_uses_the_same_rules(self):
        resolver = _resolver(lambda _r: _result("ok"))
        assert resolver.resolve(PROBE_REQUEST, budget=BUDGET, mode=TRIAL).decision.kind == ("ALLOW")


@pytest.mark.parametrize("mode", [FORMAL, TRIAL])
def test_no_static_fallback_anywhere_in_the_lifecycle(mode):
    """No path through the resolver may answer with a static prior."""

    def _boom(_r):
        raise ProbeInfrastructureError("channel down")

    resolution = _resolver(_boom).resolve(PROBE_REQUEST, budget=BUDGET, mode=mode)
    assert resolution.decision.kind == "ABORT"
    assert resolution.estimate is None
