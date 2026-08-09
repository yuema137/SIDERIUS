"""V21 PR B3 Stage B — ONE graded admission rule over two grades of evidence.

The frozen S3 semantics, restated so each test can be checked against it:

> `vram_budget_gb` is an ADMISSION THRESHOLD, not a runtime hard cap.
> Admission may enforce it against the strongest available
> candidate-specific PRE-PHASE evidence — a forecast or a bounded measured
> probe. After admission, realized exceedance is recorded and surfaced as
> an operator-visible condition, but exceedance alone does NOT terminate
> the phase, invalidate the scientific result, or alter the score. Peer
> usage is context, never candidate evidence.

Stage A found the admission rule already implemented and inert: nothing
populated `budget.vram_gb`. Stage B arms it at the one site whose estimate
carries a measured peak, and proves the private comparisons agree.

Design doc: ``docs/design/v21_priorities/pr_b_resource_budget_semantics.md``
§0.7 (Stage A) and Commit B3.
"""

from __future__ import annotations

import pytest

from core.runtime_control.decision_policy import (
    RuntimeBudget,
    RuntimeDecisionPolicy,
    RuntimeMode,
)
from core.runtime_control.estimate_types import make_estimate

_GB = 1024
_FORMAL = RuntimeMode(phase="formal", candidate_stage="post_implementation", probe_available=True)


def _measured(peak_gb):
    """A bounded-live-probe estimate — blocking-eligible evidence."""
    return make_estimate(
        provenance="bounded_live_probe",
        confidence="medium",
        expected_seconds=100.0,
        peak_vram_gb=peak_gb,
        concurrency_identity="single_candidate_idle",
        measurement_validity="valid_current_conditions",
        verification_passed=True,
        steady_state=True,
    )


def _projected(peak_gb):
    """A static estimate — advisory-only evidence."""
    return make_estimate(
        provenance="static_uncalibrated",
        confidence="low",
        expected_seconds=100.0,
        peak_vram_gb=peak_gb,
    )


class TestTheGradedAdmissionRule:
    """S3's admission half: the SAME threshold, graded by evidence strength.

    This is the property that dissolves B0's "two consumers disagree"
    finding — a forecast and a measurement are not two policies, they are
    two grades of evidence under one rule.
    """

    @pytest.fixture
    def policy(self):
        return RuntimeDecisionPolicy()

    def test_measured_evidence_above_the_threshold_rejects(self, policy):
        d = policy.decide(
            _measured(20.0), RuntimeBudget(time_seconds=99999.0, vram_gb=12.0), _FORMAL
        )
        assert d.kind == "REJECT"
        assert any("measured peak VRAM" in r for r in d.reasons)

    def test_projected_evidence_above_the_threshold_is_only_advisory(self, policy):
        """A forecast may warn; it may not block.

        Wiring a budget must not hand blocking authority to a static
        prior. That would be S2 smuggled in through the connection.
        """
        d = policy.decide(
            _projected(20.0), RuntimeBudget(time_seconds=99999.0, vram_gb=12.0), _FORMAL
        )
        assert d.kind == "ADVISORY"
        assert any("non-blocking provenance" in r for r in d.reasons)

    def test_evidence_below_the_threshold_allows(self, policy):
        assert (
            policy.decide(
                _measured(8.0), RuntimeBudget(time_seconds=99999.0, vram_gb=12.0), _FORMAL
            ).kind
            == "ALLOW"
        )

    def test_no_threshold_supplied_reproduces_pre_B3_behaviour(self, policy):
        """The exact production state Stage A found: rule correct, never armed.

        Keeping this asserted means the wiring is provably the thing that
        activates the rule, not something that merely coincides with it.
        """
        assert (
            policy.decide(_measured(20.0), RuntimeBudget(time_seconds=99999.0), _FORMAL).kind
            == "ALLOW"
        )

    def test_an_unmeasured_peak_cannot_be_judged(self, policy):
        """No peak, no verdict — not a favourable one."""
        assert (
            policy.decide(
                _measured(None), RuntimeBudget(time_seconds=99999.0, vram_gb=12.0), _FORMAL
            ).kind
            == "ALLOW"
        )

    def test_the_boundary_is_strict_exceedance(self, policy):
        """Equal to the threshold is admitted; the rule is `>`, not `>=`."""
        assert (
            policy.decide(
                _measured(12.0), RuntimeBudget(time_seconds=99999.0, vram_gb=12.0), _FORMAL
            ).kind
            == "ALLOW"
        )


class TestThresholdParityAcrossTheThreeRules:
    """§5.3 — the private comparisons must agree with the shared one.

    Stage B found they did not. `IsolatedProbeSpec.effective_cap_gb`
    returned the operator budget *instead of* the defensive cap rather
    than the lower of the two, so in the PHYSICAL VETO regime the worker's
    ceiling sat above the parent's:

        physical 25 GB, operator budget 40 GB, measured peak 30 GB
          parent gate  cap=min(25,40)=25 -> violation
          probe worker cap=40            -> allowed

    Reported before it was corrected (design doc §B3.B.1), and corrected
    toward the parent's meaning because an operator budget may only lower
    the 80% safety ceiling, never raise it.
    """

    @staticmethod
    def _wrapper_cap_gb(physical_gb, budget_gb):
        """Mirrors `evaluate_vram_skill/wrapper.py:529-532`."""
        cap = int(physical_gb * 1024**3)
        if budget_gb is not None:
            cap = min(cap, int(budget_gb * 1024**3))
        return cap / 1024**3

    @staticmethod
    def _probe_spec(physical_gb, budget_gb):
        from agent.skills.evaluate_vram_skill.isolated_probe import (
            HardwareSnapshot,
            IsolatedProbeSpec,
        )

        snap = HardwareSnapshot(
            usable_cap_bytes=int(physical_gb * 1024**3),
            usable_cap_gb=physical_gb,
            total_memory_bytes=int(physical_gb / 0.8 * 1024**3),
            total_memory_gb=physical_gb / 0.8,
            device_name="parity",
            device_available=True,
            hardware_fingerprint="fp",
        )
        return IsolatedProbeSpec.model_construct(vram_budget_gb=budget_gb, hardware=snap)

    @pytest.mark.parametrize(
        ("physical", "budget", "peak"),
        [
            (25.0, 12.0, 20.0),
            (25.0, 12.0, 8.0),
            (25.0, None, 20.0),
            (25.0, None, 30.0),
            (25.0, 40.0, 30.0),  # PHYSICAL VETO — the cell that diverged
            (25.0, 40.0, 20.0),
            (25.0, 25.0, 25.0),
        ],
    )
    def test_the_parent_gate_and_the_probe_worker_agree(self, physical, budget, peak):
        wrapper_cap = self._wrapper_cap_gb(physical, budget)
        probe_cap = self._probe_spec(physical, budget).effective_cap_gb()
        assert probe_cap is not None
        assert (peak > wrapper_cap) == (peak > probe_cap), (
            f"physical={physical} budget={budget} peak={peak}: parent cap "
            f"{wrapper_cap} vs worker cap {probe_cap}"
        )

    def test_the_veto_regime_takes_the_lower_bound_and_names_it(self):
        spec = self._probe_spec(25.0, 40.0)
        assert spec.effective_cap_gb() == 25.0
        assert spec.effective_limit_source() == "physical_veto_defensive_cap"

    def test_the_ordinary_regime_still_reports_the_operator_budget(self):
        spec = self._probe_spec(25.0, 12.0)
        assert spec.effective_cap_gb() == 12.0
        assert spec.effective_limit_source() == "operator_vram_budget"

    def test_a_worker_with_no_snapshot_keeps_the_operator_budget(self):
        """The correction must not turn a missing snapshot into no cap."""
        from agent.skills.evaluate_vram_skill.isolated_probe import IsolatedProbeSpec

        spec = IsolatedProbeSpec.model_construct(vram_budget_gb=40.0, hardware=None)
        assert spec.effective_cap_gb() == 40.0
        assert spec.effective_limit_source() == "operator_vram_budget"


class TestTheThresholdReachesTheProductionBudget:
    """§5.1 reachability — the wiring, not just the rule.

    Added after mutations Q1/Q2/Q3 all SURVIVED. Every earlier test in
    this module asserted the *policy* and the *parity*; none drove the
    tuner site that supplies the budget, so deleting the wiring entirely
    changed nothing visible. That is the §0.1 defect reproduced inside my
    own test suite: a correct rule that nobody calls.

    These capture the `RuntimeBudget` the production helper actually
    builds.
    """

    @staticmethod
    def _drive(monkeypatch, resource_limit_gb):
        """Run the production helper far enough to build the budget."""
        import nodes.ml_hyperparameter_tune_agent as tuner
        from core.runtime_control import probe_wiring

        captured: dict = {}

        class _Capability:
            available = True
            unavailability_reason = None

        monkeypatch.setattr(
            probe_wiring, "probe_runner_availability", lambda _c: (True, "test-forced")
        )
        monkeypatch.setattr(
            probe_wiring, "build_production_probe_runner", lambda **kw: lambda r: None
        )
        monkeypatch.setattr(probe_wiring, "build_registry_persist", lambda **kw: lambda *a: ())
        monkeypatch.setattr(
            probe_wiring, "probe_capability", lambda **kw: _Capability(), raising=False
        )

        def _capture(*, request, budget, mode, run_probe, persist, **kw):
            captured["budget"] = budget
            captured["mode"] = mode

            class _Res:
                class decision:
                    kind = "ALLOW"
                    reasons = ()
                    evidence_provenance = "bounded_live_probe"

                probe_ran = True
                probe_status = "ok"
                observation_ids = ()
                estimate = None

            return _Res()

        monkeypatch.setattr(probe_wiring, "resolve_request_probe", _capture)

        time_check = {"breakdown": {"runtime_decision": "REQUEST_PROBE"}}
        tuner._resolve_time_check_probe_request(
            time_check,
            model_type="punet",
            active_params={
                "model_config": {"segmentation_size": 40000},
                "train_config": {"batch_size": 1, "epochs": 1},
                "loss_config": {"loss_type": "focal"},
            },
            time_budget_minutes=60.0,
            is_trial=False,
            data_dir=None,
            run_name="b3_reach",
            exp_id="e1",
            vram_threshold_gb=resource_limit_gb,
        )
        return captured

    def test_the_effective_threshold_reaches_the_budget(self, monkeypatch):
        captured = self._drive(monkeypatch, 12.0)
        assert "budget" in captured, "the production helper never built a RuntimeBudget"
        assert captured["budget"].vram_gb == 12.0, (
            "the admission threshold did not reach RuntimeBudget.vram_gb — the S3 "
            "rule is armed by this value and by nothing else"
        )

    def test_no_threshold_leaves_the_budget_unarmed(self, monkeypatch):
        """Absence must stay absence, not become 0.0 or a default."""
        assert self._drive(monkeypatch, None)["budget"].vram_gb is None

    def test_a_nonpositive_threshold_is_treated_as_unset(self, monkeypatch):
        """`vram_gb` is declared `gt=0`; 0 must not raise, and must not arm."""
        assert self._drive(monkeypatch, 0.0)["budget"].vram_gb is None

    def test_the_time_budget_is_still_supplied(self, monkeypatch):
        """B3 must not disturb the dimension that already worked."""
        assert self._drive(monkeypatch, 12.0)["budget"].time_seconds == pytest.approx(3600.0)

    def test_the_production_call_site_passes_the_EFFECTIVE_threshold(self):
        """The one thing `_drive` cannot cover: which value `run()` chooses.

        Added after mutations Q2 and Q3 survived. `_drive` supplies
        `vram_threshold_gb` itself, so it proves the helper uses whatever
        it is given — not that the orchestrator gives it the right thing.
        The call site lives inside the 2,400-line `run()` and cannot be
        driven in isolation, so this is asserted on source, as B1b's clamp
        guard is.

        Two distinct regressions are covered:
          Q2 the call site stops passing a threshold at all;
          Q3 it passes the RAW operator budget instead of the effective
             one, which differs exactly in the PHYSICAL VETO regime.
        """
        import inspect

        import nodes.ml_hyperparameter_tune_agent as tuner

        src = inspect.getsource(tuner)
        assert 'vram_threshold_gb=(resource_check or {}).get("limit_gb")' in src, (
            "the probe call site no longer passes the effective admission "
            "threshold; the S3 rule is armed by this and nothing else"
        )
        assert 'vram_threshold_gb=(resource_check or {}).get("vram_budget_gb")' not in src, (
            "the call site passes the RAW operator budget. That is not the "
            "effective threshold: under PHYSICAL VETO the operator budget "
            "exceeds the card and min(physical, budget) is what admission uses"
        )
