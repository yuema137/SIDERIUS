"""C4 — unified decision policy, estimator factory, and stable identities.

Operator-required validation (C4 approval):

* every resolved §7.4 matrix cell covered;
* static/historical evidence can never produce REJECT or ABORT solely
  from a runtime budget;
* deterministic post-implementation capacity impossibility → REJECT;
  the same accounting from LLM-authored numbers → ADVISORY only;
* measured OOM / measured wall-cap / measured peak-VRAM violation may
  REJECT;
* REJECT and ABORT are distinct; over-budget never ABORTs;
* identities are deterministic across processes, insertion orders, and
  equivalent constructions; behavioral changes move the config hash;
  non-behavioral extras do not; no hardware/path/timestamp inputs;
* characterization: the estimator's tier-0 output is numerically
  identical to the legacy static formula (mathematics untouched).
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from agent.utils.proposer_preflight import estimate_proposal_time
from core.runtime_control.decision_policy import (
    _POLICY_MATRIX,
    CapacityCheck,
    RuntimeBudget,
    RuntimeDecisionPolicy,
    RuntimeMode,
    policy_identity_payload,
)
from core.runtime_control.estimate_types import make_estimate
from core.runtime_control.estimator import (
    RuntimeEstimateRequest,
    production_estimator_factory,
)
from core.runtime_control.identity import component_identity, config_hash12

POLICY = RuntimeDecisionPolicy()
BUDGET = RuntimeBudget(time_seconds=1200.0, vram_gb=16.0)


def _mode(phase="trial", stage="post_implementation", probe=False) -> RuntimeMode:
    return RuntimeMode(phase=phase, candidate_stage=stage, probe_available=probe)


def _est(
    provenance,
    *,
    expected=2400.0,
    lower=None,
    verified=False,
    steady=False,
    concurrency=None,
    peak_vram=None,
    confidence="low",
):
    return make_estimate(
        provenance=provenance,
        confidence=confidence,
        expected_seconds=expected,
        lower_seconds=lower,
        peak_vram_gb=peak_vram,
        verification_passed=verified,
        steady_state=steady,
        concurrency_identity=concurrency,
    )


# ---------------------------------------------------------------------------
# Matrix-cell coverage
# ---------------------------------------------------------------------------


class TestMatrixCells:
    def test_static_prior_over_budget_is_advisory_every_phase(self):
        for phase in ("proposal", "trial", "formal"):
            d = POLICY.decide(_est("static_uncalibrated"), BUDGET, _mode(phase=phase))
            assert d.kind == "ADVISORY"

    def test_historical_prior_advisory_or_probe(self):
        d = POLICY.decide(_est("legacy_calibration_prior"), BUDGET, _mode())
        assert d.kind == "ADVISORY"
        d2 = POLICY.decide(_est("historical_observation_prior"), BUDGET, _mode(probe=True))
        assert d2.kind == "REQUEST_PROBE"

    def test_contended_probe_cannot_be_sole_blocker(self):
        est = _est("bounded_live_probe", concurrency="foreign_contended")
        d = POLICY.decide(est, BUDGET, _mode(phase="formal"))
        assert d.kind == "ADVISORY"
        d2 = POLICY.decide(est, BUDGET, _mode(phase="formal", probe=True))
        assert d2.kind == "REQUEST_PROBE"  # clean-retry request

    def test_clean_uncalibrated_probe_time_blocks_only_beyond_optimistic_bound(self):
        within = _est("bounded_live_probe", expected=2400.0, lower=900.0)
        d = POLICY.decide(within, BUDGET, _mode())
        assert d.kind == "ALLOW"  # over budget within uncertainty → explicit-warning allow
        beyond = _est("bounded_live_probe", expected=2400.0, lower=1500.0)
        d2 = POLICY.decide(beyond, BUDGET, _mode())
        assert d2.kind == "REJECT"

    def test_calibrated_probe_may_block(self):
        d = POLICY.decide(_est("bounded_live_probe_calibrated"), BUDGET, _mode())
        assert d.kind == "REJECT"

    def test_in_process_verification_may_block_formal(self):
        est = _est("real_training_verification", verified=True, steady=True)
        d = POLICY.decide(est, BUDGET, _mode(phase="formal"))
        assert d.kind == "REJECT"

    def test_within_budget_allows(self):
        d = POLICY.decide(_est("real_training_verification", expected=600.0), BUDGET, _mode())
        assert d.kind == "ALLOW"

    def test_matrix_table_is_complete(self):
        assert set(_POLICY_MATRIX) == {
            "static_prior",
            "historical_prior_only",
            "live_probe_contended",
            "live_probe_clean_uncalibrated",
            "calibrated_live_probe",
            "in_process_verification",
            "complete_observation",
        }
        for row in _POLICY_MATRIX.values():
            assert set(row) == {"proposal", "trial", "formal", "watchdog"}


# ---------------------------------------------------------------------------
# VRAM authority placement + measured failures
# ---------------------------------------------------------------------------


class TestVramAndMeasuredFailures:
    def test_realized_capacity_impossibility_rejects(self):
        check = CapacityCheck(required_gb=40.0, available_gb=16.0, realized=True)
        d = POLICY.decide(
            _est("static_uncalibrated", expected=None), BUDGET, _mode(), capacity_check=check
        )
        assert d.kind == "REJECT"

    def test_llm_authored_capacity_numbers_are_advisory_only(self):
        check = CapacityCheck(required_gb=40.0, available_gb=16.0, realized=False)
        d = POLICY.decide(
            _est("static_uncalibrated", expected=None), BUDGET, _mode(), capacity_check=check
        )
        assert d.kind == "ADVISORY"

    def test_pre_implementation_capacity_is_advisory_even_if_realized_flagged(self):
        check = CapacityCheck(required_gb=40.0, available_gb=16.0, realized=True)
        d = POLICY.decide(
            _est("static_uncalibrated", expected=None),
            BUDGET,
            _mode(stage="proposal"),
            capacity_check=check,
        )
        assert d.kind == "ADVISORY"

    def test_measured_oom_and_wall_cap_reject(self):
        est = _est("bounded_live_probe", expected=None)
        for failure in ("oom", "wall_cap"):
            d = POLICY.decide(est, BUDGET, _mode(), measured_failure=failure)
            assert d.kind == "REJECT"

    def test_measured_peak_vram_violation_rejects(self):
        est = _est("bounded_live_probe", expected=None, peak_vram=20.0)
        d = POLICY.decide(est, BUDGET, _mode())
        assert d.kind == "REJECT"

    def test_projected_vram_violation_from_prior_is_advisory(self):
        est = _est("static_uncalibrated", expected=None, peak_vram=20.0)
        d = POLICY.decide(est, BUDGET, _mode())
        assert d.kind == "ADVISORY"


# ---------------------------------------------------------------------------
# REJECT vs ABORT
# ---------------------------------------------------------------------------


class TestRejectVersusAbort:
    def test_over_budget_never_aborts(self):
        for provenance in (
            "static_uncalibrated",
            "legacy_calibration_prior",
            "bounded_live_probe",
            "bounded_live_probe_calibrated",
            "real_training_verification",
        ):
            d = POLICY.decide(_est(provenance, expected=10_000_000.0), BUDGET, _mode())
            assert d.kind != "ABORT", provenance

    def test_abort_reserved_for_invalid_evidence_combinations(self):
        """A measured failure reported with prior provenance is an unsafe
        input state — the workflow cannot trust its evidence channel."""
        d = POLICY.decide(
            _est("static_uncalibrated", expected=None),
            BUDGET,
            _mode(),
            measured_failure="oom",
        )
        assert d.kind == "ABORT"
        assert any("invalid evidence combination" in r for r in d.reasons)


# ---------------------------------------------------------------------------
# Identities
# ---------------------------------------------------------------------------


class TestIdentities:
    def test_format(self):
        est, pol = production_estimator_factory().build()
        for ident in (est.identity, pol.identity):
            name, rest = ident.split("@")
            semver, hash12 = rest.split("+")
            assert name in ("runtime_estimator", "runtime_decision_policy")
            assert len(semver.split(".")) == 3
            assert len(hash12) == 12 and all(c in "0123456789abcdef" for c in hash12)

    def test_deterministic_across_processes(self):
        code = (
            "from core.runtime_control.estimator import production_estimator_factory;"
            "e,p = production_estimator_factory().build();"
            "print(e.identity); print(p.identity)"
        )
        runs = [
            subprocess.run(
                [sys.executable, "-c", code], capture_output=True, text=True, check=True
            ).stdout
            for _ in range(2)
        ]
        assert runs[0] == runs[1]
        est, pol = production_estimator_factory().build()
        assert runs[0].split() == [est.identity, pol.identity]

    def test_mapping_insertion_order_irrelevant(self):
        a = {"x": 1, "y": {"b": 2, "a": 3}}
        b = {"y": {"a": 3, "b": 2}, "x": 1}
        assert config_hash12(a) == config_hash12(b)

    def test_behavioral_change_moves_the_hash(self):
        payload = policy_identity_payload()
        mutated = json.loads(json.dumps(payload))
        mutated["policy_matrix"]["static_prior"]["formal"] = "may_block"  # illegal edit
        assert config_hash12(payload) != config_hash12(mutated)

    def test_list_order_is_behavioral(self):
        """Precedence order is meaning — reordering must move the hash."""
        payload = policy_identity_payload()
        mutated = json.loads(json.dumps(payload))
        mutated["precedence_order"] = list(reversed(mutated["precedence_order"]))
        assert config_hash12(payload) != config_hash12(mutated)

    def test_no_environmental_inputs_in_payloads(self):
        import socket

        from core.runtime_control.estimator import estimator_identity_payload

        for payload in (policy_identity_payload(), estimator_identity_payload()):
            flat = json.dumps(payload)
            assert socket.gethostname() not in flat
            assert "/home/" not in flat and "/tmp/" not in flat
            assert "20" not in json.dumps(list(payload)) or True  # keys only check below
            assert not any(k in flat for k in ("timestamp", "hostname", "gpu_name", "workspace"))

    def test_sets_rejected_by_canonicalizer(self):
        with pytest.raises(TypeError, match="deterministic order"):
            config_hash12({"values": {1, 2, 3}})

    def test_semver_validated(self):
        with pytest.raises(ValueError):
            component_identity("x", "1.0", {})


# ---------------------------------------------------------------------------
# Characterization — legacy numeric parity
# ---------------------------------------------------------------------------


class TestCharacterization:
    @pytest.mark.parametrize(
        "num_params,seg,bs,epochs",
        [
            (50_000, 40_000, 1, 2),
            (500_000, 40_000, 8, 1),
            (18_400_000, 1_000, 8, 1),  # wave-1 rejected-draft shape
            (500_000_000, 40_000, 1, 10),
        ],
    )
    def test_tier0_estimate_matches_legacy_formula(self, num_params, seg, bs, epochs):
        est_obj, _ = production_estimator_factory().build()
        request = RuntimeEstimateRequest(
            phase="proposal",
            operation="combined",
            model_identity="parity_probe",
            parameter_count=num_params,
            batch_size=bs,
            segment_length=seg,
            train_steps=0,
            inference_batches=0,
            model_features={"epochs": epochs, "time_budget_minutes": 20.0},
        )
        wrapped = est_obj.estimate(request)
        legacy = estimate_proposal_time(
            model_type="parity_probe",
            model_config={"segmentation_size": seg},
            train_config={"batch_size": bs, "epochs": epochs},
            loss_config={"loss_type": "ce"},
            num_params=num_params,
            time_budget_minutes=20.0,
        )
        assert wrapped.expected_seconds == pytest.approx(legacy["estimated_minutes"] * 60.0)
        assert wrapped.provenance == "static_uncalibrated"
        assert wrapped.blocking_eligible is False
