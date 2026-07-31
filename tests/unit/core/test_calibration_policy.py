"""C7 — calibration policy: D3 contention, D4 promotion lifecycle,
uncertainty, applicability/drift, D5 unknown families.

Every operator rule from the C7 decision set has at least one test that
fails if the rule is removed. Pure unit tests: no GPU, no nvidia-smi, no
registry IO (that lives in test_calibration_registry.py)."""

from __future__ import annotations

import pytest

from core.runtime_control.calibration_policy import (
    DEFAULT_DERATING_THROTTLE_MASK,
    DEFAULT_POLICY,
    CalibrationPolicy,
    applicability_for_request,
    bucket_key,
    bucket_uncertainty,
    classify_applicability,
    classify_contention_window,
    classify_model_family,
    consistency_ratio,
    detect_drift,
    downgrade_for_applicability,
    eligibility_problems,
    evaluate_bucket,
    evaluate_promotions,
    is_clean,
    sample_contention_window,
    stack_identity,
    validate_against_verification,
)
from core.runtime_control.estimate_types import make_estimate
from core.runtime_control.probe import ContentionSnapshot
from core.runtime_control.registry_schemas import CalibrationObservation

VRAM = 32.0  # → memory threshold max(1 GiB, 3.2 GB) = 3.2 GB


def _snap(**over) -> ContentionSnapshot:
    base = dict(
        telemetry_available=True,
        foreign_compute_processes=0,
        gpu_utilization_pct=0.0,
        gpu_memory_used_gb=0.2,
        compute_process_pids=(),
        foreign_compute_pids=(),
        excluded_pids=(4242,),
        throttle_reasons_hex=0x0,
    )
    base.update(over)
    return ContentionSnapshot(**base)


def _window(n=5, **over) -> list[ContentionSnapshot]:
    return [_snap(**over) for _ in range(n)]


def _classify(samples, **kw):
    kw.setdefault("device_vram_gb", VRAM)
    return classify_contention_window(samples, **kw)


def _obs(**over) -> CalibrationObservation:
    base = dict(
        operation="training",
        measurement_unit="optimizer_step",
        measured_value_ms=20.0,
        workload={"batch_size": 8, "segment_length": 40_000},
        realized_model={"parameter_count": 156_320},
        model_family="unknown",
        hardware_compatibility_id="sha256:" + "a" * 64,
        execution_environment_id="sha256:" + "b" * 64,
        concurrency_identity="single_candidate_idle",
        software_stack={"torch": "2.7.0"},
        producer_identity="runtime_probe@1.0.0",
        provenance="bounded_live_probe",
        uncertainty_inputs={"spread_ms": [19.0, 21.0]},
        source_run={"run_name": "unit"},
    )
    base.update(over)
    return CalibrationObservation(**base)


# ── D3 ──────────────────────────────────────────────────────────────────────


class TestContentionClassification:
    def test_only_self_is_idle(self):
        verdict, reasons = _classify(_window())
        assert verdict == "single_candidate_idle"
        assert "only the current probe process" in reasons[0]

    def test_unregistered_foreign_pid_is_contended(self):
        samples = _window(foreign_compute_processes=1, foreign_compute_pids=(999,))
        verdict, reasons = _classify(samples)
        assert verdict == "foreign_contended"
        assert "999" in reasons[0]

    def test_registered_peer_only_is_pairwise(self):
        samples = _window(foreign_compute_processes=1, foreign_compute_pids=(777,))
        assert _classify(samples, expected_peer_pids=(777,))[0] == "pairwise_expected_peer"

    def test_registered_peer_plus_stranger_is_contended(self):
        samples = _window(foreign_compute_processes=2, foreign_compute_pids=(777, 999))
        verdict, reasons = _classify(samples, expected_peer_pids=(777,))
        assert verdict == "foreign_contended"
        assert "999" in reasons[0] and "777" not in reasons[0]

    def test_peer_is_never_inferred_without_an_explicit_pid(self):
        """A caller that merely *expects* a peer, without registering its
        PID, gets foreign_contended — no name-based inference exists."""
        samples = _window(foreign_compute_processes=1, foreign_compute_pids=(777,))
        assert _classify(samples)[0] == "foreign_contended"

    def test_foreign_count_without_pids_still_counts(self):
        samples = _window(foreign_compute_processes=3, foreign_compute_pids=())
        verdict, reasons = _classify(samples)
        assert verdict == "foreign_contended"
        assert "3 further unidentified" in reasons[0]

    def test_memory_threshold_uses_ten_percent_on_large_device(self):
        assert _classify(_window(gpu_memory_used_gb=3.1))[0] == "single_candidate_idle"
        verdict, reasons = _classify(_window(gpu_memory_used_gb=3.3))
        assert verdict == "foreign_contended"
        assert "3.20 GB" in reasons[0]

    def test_memory_threshold_uses_one_gib_floor_on_small_device(self):
        small = dict(device_vram_gb=4.0)  # 10% = 0.4 GB < 1 GiB floor
        assert _classify(_window(gpu_memory_used_gb=0.9), **small)[0] == "single_candidate_idle"
        assert _classify(_window(gpu_memory_used_gb=1.1), **small)[0] == "foreign_contended"

    def test_sustained_utilization_across_whole_window_is_contended(self):
        assert _classify(_window(gpu_utilization_pct=25.0))[0] == "foreign_contended"

    def test_single_utilization_spike_is_not_sustained(self):
        samples = _window(n=4)
        samples[1] = _snap(gpu_utilization_pct=95.0)
        assert _classify(samples)[0] == "single_candidate_idle"

    def test_telemetry_gap_anywhere_is_unknown(self):
        samples = _window(n=3)
        samples[2] = ContentionSnapshot(telemetry_available=False)
        assert _classify(samples)[0] == "unknown_contention"
        assert _classify([])[0] == "unknown_contention"

    def test_derating_throttle_is_unknown_contention(self):
        assert _classify(_window(throttle_reasons_hex=0x8))[0] == "unknown_contention"

    def test_benign_power_cap_is_not_throttling(self):
        """An idle RTX 5090 reports SwPowerCap (0x4) continuously; treating
        it as throttling would mark every measurement unknown."""
        assert 0x4 & DEFAULT_DERATING_THROTTLE_MASK == 0
        assert _classify(_window(throttle_reasons_hex=0x4))[0] == "single_candidate_idle"

    def test_absent_throttle_field_is_not_evidence_of_throttling(self):
        assert _classify(_window(throttle_reasons_hex=None))[0] == "single_candidate_idle"

    def test_thresholds_are_policy_versioned(self):
        strict = CalibrationPolicy(contention_utilization_pct=5.0)
        assert strict.identity != DEFAULT_POLICY.identity
        assert strict.identity.startswith("calibration_policy@1.0.0+")
        samples = _window(gpu_utilization_pct=10.0)
        assert _classify(samples)[0] == "single_candidate_idle"
        assert _classify(samples, policy=strict)[0] == "foreign_contended"


class TestContentionWindowSampling:
    def test_window_is_bounded_and_multi_sample(self):
        slept: list[float] = []
        window = sample_contention_window(
            device_vram_gb=VRAM,
            capture=lambda *a, **k: _snap(),
            sleep=slept.append,
        )
        assert len(window.samples) == 5  # ceil(10 s / 2 s)
        assert slept == [2.0, 2.0, 2.0, 2.0]  # no trailing sleep
        assert window.classification == "single_candidate_idle"

    def test_all_raw_telemetry_is_recorded(self):
        window = sample_contention_window(
            device_vram_gb=VRAM,
            expected_peer_pids=(777,),
            capture=lambda *a, **k: _snap(foreign_compute_processes=1, foreign_compute_pids=(777,)),
            sleep=lambda _: None,
        )
        payload = window.raw_telemetry()
        assert len(payload["samples"]) == 5
        assert payload["samples"][0]["foreign_compute_pids"] == [777]
        assert payload["samples"][0]["excluded_pids"] == [4242]
        assert payload["expected_peer_pids"] == [777]
        assert payload["policy_identity"] == DEFAULT_POLICY.identity
        assert payload["classification"] == "pairwise_expected_peer"
        assert payload["reasons"]


# ── D5 ──────────────────────────────────────────────────────────────────────


class TestUnknownFamily:
    def test_declared_metadata_wins(self):
        assert classify_model_family(declared_family="punet") == "punet"

    def test_deterministic_structural_feature(self):
        assert (
            classify_model_family(structural_features={"dominant_block_type": "conv1d"})
            == "feature:conv1d"
        )

    def test_uncertain_stays_unknown(self):
        assert classify_model_family() == "unknown"
        assert classify_model_family(declared_family="  ", structural_features={}) == "unknown"

    def test_unknown_family_never_inherits_known_family_calibration(self):
        known = [_obs(model_family="punet", measured_value_ms=v) for v in (20.0, 21.0)]
        unknown = _obs(model_family="unknown", measured_value_ms=20.5)
        promos = evaluate_promotions([*known, unknown], generation=1)
        assert [p.level for p in promos] == ["provisional"]
        assert "punet" in promos[0].bucket_key
        assert promos[0].n_observations == 2  # the unknown candidate is NOT folded in

    def test_unknown_family_probes_and_promotes_on_its_own_evidence(self):
        obs = [_obs(model_family="unknown", measured_value_ms=v) for v in (20.0, 21.0, 22.0)]
        promos = evaluate_promotions(obs, generation=1)
        assert [p.level for p in promos] == ["validated"]
        assert promos[0].bucket_key.endswith(f"unknown|{stack_identity({'torch': '2.7.0'})}")


# ── D4 ──────────────────────────────────────────────────────────────────────


class TestPromotionLifecycle:
    def test_one_observation_stays_candidate_only(self):
        assert evaluate_promotions([_obs()], generation=1) == []

    def test_two_consistent_observations_are_provisional(self):
        promo = evaluate_bucket(
            [_obs(measured_value_ms=20.0), _obs(measured_value_ms=21.0)], generation=3
        )
        assert promo is not None
        assert promo.level == "provisional"
        assert promo.n_observations == 2
        assert promo.rate_min_ms == 20.0 and promo.rate_max_ms == 21.0
        assert promo.rate_median_ms == 20.5
        assert promo.validation_route == "consistency"
        assert promo.derived_from_generation == 3
        assert promo.policy_identity == DEFAULT_POLICY.identity

    def test_three_consistent_observations_are_validated(self):
        obs = [_obs(measured_value_ms=v) for v in (20.0, 21.0, 22.0)]
        promo = evaluate_bucket(obs, generation=1)
        assert promo is not None and promo.level == "validated"
        assert promo.consistency_ratio == pytest.approx(1.1)

    def test_ratio_above_limit_blocks_promotion(self):
        obs = [_obs(measured_value_ms=v) for v in (20.0, 21.0, 40.0)]
        assert consistency_ratio([20.0, 21.0, 40.0]) == 2.0
        assert evaluate_bucket(obs, generation=1) is None

    def test_boundary_ratio_exactly_at_limit_promotes(self):
        obs = [_obs(measured_value_ms=v) for v in (20.0, 30.0)]
        promo = evaluate_bucket(obs, generation=1)
        assert promo is not None and promo.consistency_ratio == 1.5

    def test_promotion_is_deterministic(self):
        obs = [_obs(measured_value_ms=v) for v in (20.0, 21.0, 22.0)]
        a = evaluate_promotions(obs, generation=7)
        b = evaluate_promotions(list(reversed(obs)), generation=7)
        assert [p.promotion_id for p in a] == [p.promotion_id for p in b]

    def test_observations_are_never_mutated(self):
        obs = [_obs(measured_value_ms=v) for v in (20.0, 21.0, 22.0)]
        before = [o.observation_id for o in obs]
        promo = evaluate_bucket(obs, generation=1)
        assert [o.observation_id for o in obs] == before
        assert all(o.validation_status == "unvalidated" for o in obs)
        assert promo is not None
        assert set(promo.source_observation_ids) == set(before)

    def test_mixed_buckets_are_a_programming_error(self):
        with pytest.raises(ValueError, match="mixed buckets"):
            evaluate_bucket([_obs(), _obs(operation="inference")], generation=1)

    def test_dirty_observations_are_rejected_by_evaluate_bucket(self):
        dirty = _obs(concurrency_identity="foreign_contended")
        with pytest.raises(ValueError, match="pre-screened clean"):
            evaluate_bucket([dirty, dirty], generation=1)


class TestEligibilityScreen:
    def test_contended_and_unknown_are_never_calibration_eligible(self):
        for identity in ("foreign_contended", "unknown_contention"):
            problems = eligibility_problems(_obs(concurrency_identity=identity))
            assert any("not clean" in p for p in problems)

    def test_missing_workload_metadata_blocks(self):
        assert not is_clean(_obs(workload={}))

    def test_failure_evidence_never_updates_throughput_calibration(self):
        failed = _obs(source_run={"run_name": "x", "outcome": "oom"})
        assert not is_clean(failed)
        assert evaluate_promotions([failed, failed, _obs()], generation=1) == []

    def test_priors_can_never_be_stored_as_observations(self):
        with pytest.raises(ValueError, match="provenance"):
            _obs(provenance="static_uncalibrated")


class TestBucketSeparation:
    @pytest.mark.parametrize(
        "override",
        [
            {"operation": "inference", "measurement_unit": "inference_batch"},
            {"operation": "setup", "measurement_unit": "setup_call"},
            {"operation": "io", "measurement_unit": "file_read"},
            {"concurrency_identity": "pairwise_expected_peer"},
            {"model_family": "punet"},
            {"hardware_compatibility_id": "sha256:" + "c" * 64},
            {"execution_environment_id": "sha256:" + "d" * 64},
            {"software_stack": {"torch": "2.8.0"}},
        ],
    )
    def test_each_dimension_separates_buckets(self, override):
        assert bucket_key(_obs()) != bucket_key(_obs(**override))

    def test_idle_bucket_is_never_polluted_by_pairwise_writes(self):
        idle = [_obs(measured_value_ms=v) for v in (20.0, 21.0)]
        pairwise = [
            _obs(concurrency_identity="pairwise_expected_peer", measured_value_ms=v)
            for v in (38.0, 39.0)
        ]
        promos = {p.bucket_key: p for p in evaluate_promotions(idle + pairwise, generation=1)}
        assert len(promos) == 2
        idle_promo = promos[bucket_key(idle[0])]
        assert idle_promo.rate_max_ms == 21.0
        assert set(idle_promo.source_observation_ids) == {o.observation_id for o in idle}

    def test_cross_machine_evidence_forms_its_own_bucket(self):
        local = [_obs(measured_value_ms=v) for v in (20.0, 21.0)]
        remote = _obs(execution_environment_id="sha256:" + "e" * 64, measured_value_ms=20.5)
        promos = evaluate_promotions([*local, remote], generation=1)
        assert len(promos) == 1 and promos[0].n_observations == 2


class TestVerificationAgreementRoute:
    def _verification(self, **over) -> CalibrationObservation:
        base = dict(provenance="real_training_verification", producer_identity="tuner@1")
        base.update(over)
        return _obs(**base)

    def test_comparable_units_validate_the_probe(self):
        promo = validate_against_verification(
            _obs(measured_value_ms=20.0),
            self._verification(measured_value_ms=22.0),
            generation=2,
        )
        assert promo is not None
        assert promo.level == "validated"
        assert promo.validation_route == "verification_agreement"
        assert promo.n_observations == 2

    def test_incomparable_units_do_not_validate(self):
        assert (
            validate_against_verification(
                _obs(),
                self._verification(operation="inference", measurement_unit="inference_batch"),
                generation=1,
            )
            is None
        )

    def test_disagreement_does_not_validate(self):
        assert (
            validate_against_verification(
                _obs(measured_value_ms=20.0),
                self._verification(measured_value_ms=60.0),
                generation=1,
            )
            is None
        )

    def test_non_verification_provenance_is_a_programming_error(self):
        with pytest.raises(ValueError, match="route B requires"):
            validate_against_verification(_obs(), _obs(), generation=1)

    def test_contended_verification_is_rejected(self):
        with pytest.raises(ValueError, match="not clean"):
            validate_against_verification(
                _obs(),
                self._verification(concurrency_identity="foreign_contended"),
                generation=1,
            )


# ── drift + uncertainty ─────────────────────────────────────────────────────


class TestDriftAndUncertainty:
    def test_inconsistent_bucket_is_reported_not_averaged(self):
        obs = [_obs(measured_value_ms=v) for v in (20.0, 45.0)]
        report = detect_drift(obs)
        assert report.inconsistent_buckets[bucket_key(obs[0])] == 2.25
        assert evaluate_promotions(obs, generation=1) == []

    def test_stack_change_starts_a_fresh_bucket_and_is_reported(self):
        old = [_obs(measured_value_ms=v) for v in (20.0, 21.0)]
        new = [_obs(software_stack={"torch": "2.8.0"}, measured_value_ms=v) for v in (30.0, 31.0)]
        report = detect_drift(old + new, current_software_stack={"torch": "2.8.0"})
        assert len(report.stack_drift) == 1
        assert len(next(iter(report.stack_drift.values()))) == 2
        assert report.stale_buckets == [bucket_key(old[0])]
        promos = evaluate_promotions(old + new, generation=1)
        assert len(promos) == 2  # never merged across stacks

    def test_uncertainty_reports_measured_spread_only(self):
        obs = [
            _obs(measured_value_ms=20.0, uncertainty_inputs={"spread_ms": [19.0, 21.0]}),
            _obs(measured_value_ms=24.0, uncertainty_inputs={"spread_ms": [22.0, 30.0]}),
        ]
        u = bucket_uncertainty(obs)
        assert u.n_observations == 2
        assert u.rate_median_ms == 22.0
        assert u.max_min_ratio == 1.2
        assert u.within_observation_spread_ms == (22.0, 30.0)

    def test_uncertainty_without_recorded_spread_invents_nothing(self):
        obs = [_obs(measured_value_ms=v, uncertainty_inputs={}) for v in (20.0, 21.0)]
        assert bucket_uncertainty(obs).within_observation_spread_ms is None

    def test_uncertainty_requires_one_bucket(self):
        with pytest.raises(ValueError, match="mixed buckets"):
            bucket_uncertainty([_obs(), _obs(model_family="punet")])
        with pytest.raises(ValueError, match="requires observations"):
            bucket_uncertainty([])


# ── applicability ───────────────────────────────────────────────────────────


class TestApplicability:
    def test_inside_the_measured_range_is_interpolation(self):
        assert (
            classify_applicability(requested=5e5, observed_min=1e5, observed_max=1e6)
            == "interpolation"
        )

    def test_outside_is_unsupported_never_bounded(self):
        assert (
            classify_applicability(requested=2e6, observed_min=1e5, observed_max=1e6)
            == "unsupported_extrapolation"
        )

    def test_absent_evidence_is_not_supporting_evidence(self):
        label, reasons = applicability_for_request(
            requested={"parameter_count": 5e5, "batch_size": 8},
            observed_ranges={"parameter_count": (1e5, 1e6)},
        )
        assert label == "not_applicable"
        assert any("no measured evidence" in r for r in reasons)

    def test_weakest_dimension_wins(self):
        label, _ = applicability_for_request(
            requested={"parameter_count": 5e5, "batch_size": 64},
            observed_ranges={"parameter_count": (1e5, 1e6), "batch_size": (4, 16)},
        )
        assert label == "unsupported_extrapolation"

    def test_large_model_against_small_history_loses_blocking_authority(self):
        """Acceptance (b): an 18.4M-parameter request priced from
        small-model history is labelled unsupported and demoted."""
        label, reasons = applicability_for_request(
            requested={"parameter_count": 18_400_000},
            observed_ranges={"parameter_count": (45_408, 156_320)},
        )
        assert label == "unsupported_extrapolation"
        measured = make_estimate(
            provenance="bounded_live_probe",
            confidence="high",
            expected_seconds=120.0,
            concurrency_identity="single_candidate_idle",
        )
        assert measured.blocking_eligible is True
        downgraded = downgrade_for_applicability(measured, label, reasons=reasons)
        assert downgraded.applicability == "unsupported_extrapolation"
        assert downgraded.provenance == "historical_observation_prior"
        assert downgraded.blocking_eligible is False
        assert downgraded.advisory_eligible is True
        assert downgraded.expected_seconds == 120.0  # numbers survive
        assert any("18400000" in w or "1.84e+07" in w for w in downgraded.warnings)

    def test_interpolation_keeps_measured_authority(self):
        measured = make_estimate(
            provenance="bounded_live_probe",
            confidence="high",
            expected_seconds=120.0,
            concurrency_identity="single_candidate_idle",
        )
        kept = downgrade_for_applicability(measured, "interpolation")
        assert kept.provenance == "bounded_live_probe"
        assert kept.blocking_eligible is True
        assert kept.applicability == "interpolation"
