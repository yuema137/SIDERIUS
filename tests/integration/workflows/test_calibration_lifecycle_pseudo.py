"""C7 pseudo integration — the probe → registry → promotion → next-estimate
loop, driven by injected fake executors (no GPU, no LLM, no nvidia-smi).

Proves the lifecycle end to end: a bounded probe produces immutable
candidate observations; candidates alone carry no calibration authority;
enough mutually consistent clean evidence promotes the bucket; only then
does a stored observation price a later request as measured evidence —
and only inside the range it actually measured."""

from __future__ import annotations

import pytest

from core.runtime_control.calibration_policy import (
    applicability_for_request,
    bucket_key,
    downgrade_for_applicability,
    evaluate_promotions,
)
from core.runtime_control.calibration_registry import CalibrationRegistry
from core.runtime_control.probe import (
    ContentionSnapshot,
    ProbeCaps,
    ProbeExecutors,
    RealizedModelProperties,
    probe_observations,
    run_bounded_probe,
)
from core.runtime_control.registry_schemas import (
    ExecutionEnvironmentProfile,
    HardwareCompatibilityProfile,
)

CAPS = ProbeCaps(n_warmup_steps=1, n_timed_train_steps=3, n_timed_inference_batches=3)
REALIZED = RealizedModelProperties(
    parameter_count=45_408,
    trainable_parameter_count=45_408,
    parameter_memory_gb=0.001,
    dtype="float32",
)
IDLE = ContentionSnapshot(
    telemetry_available=True,
    foreign_compute_processes=0,
    gpu_utilization_pct=1.0,
    gpu_memory_used_gb=0.1,
)
BUSY = ContentionSnapshot(
    telemetry_available=True,
    foreign_compute_processes=1,
    foreign_compute_pids=(31337,),
    gpu_utilization_pct=88.0,
    gpu_memory_used_gb=12.0,
)


def _executors(train_ms: float, infer_ms: float) -> ProbeExecutors:
    return ProbeExecutors(
        setup=lambda: REALIZED,
        train_step=lambda: train_ms,
        inference_batch=lambda: infer_ms,
        peak_vram_gb=lambda: 1.5,
    )


@pytest.fixture
def env(tmp_path):
    registry = CalibrationRegistry(tmp_path / "runtime_calibration")
    hw = HardwareCompatibilityProfile(
        accelerator_vendor="NVIDIA",
        accelerator_model="pseudo-gpu",
        gpu_count=1,
        vram_gb=32.0,
        torch_version="2.7.0",
    )
    hw_id = registry.put_hardware_profile(hw)
    env_id = registry.put_environment_profile(
        ExecutionEnvironmentProfile(
            hardware_compatibility_id=hw_id,
            installation_id=registry.installation_id(),
            concurrency_regime="single_candidate_idle",
        )
    )
    return registry, hw_id, env_id


def _window(snapshot):
    """C8e: the probe consumes a bounded D3 window; drive the REAL
    classifier with a deterministic sample (no nvidia-smi, no sleeping)."""
    from core.runtime_control.calibration_policy import sample_contention_window

    def _sampler(**kwargs):
        return sample_contention_window(
            device_vram_gb=kwargs.get("device_vram_gb", 32.0),
            expected_peer_pids=kwargs.get("expected_peer_pids", ()),
            capture=lambda *a, **k: snapshot,
            sleep=lambda _s: None,
        )

    return _sampler


def _probe_and_record(env, *, train_ms, contention=IDLE, family="unknown"):
    registry, hw_id, env_id = env
    result = run_bounded_probe(
        model_identity="pseudo_candidate",
        executors=_executors(train_ms, train_ms * 2),
        caps=CAPS,
        device_vram_gb=32.0,
        contention_window=_window(contention),
    )
    assert result.status == "ok"
    records = probe_observations(
        result,
        hardware_compatibility_id=hw_id,
        execution_environment_id=env_id,
        workload={"batch_size": 8, "segment_length": 40_000},
        software_stack={"torch": "2.7.0"},
        source_run={"run_name": "pseudo"},
        model_family=family,
    )
    for record in records:
        registry.record_observation(record)
    return records


class TestCalibrationLifecyclePseudo:
    def test_candidate_evidence_alone_has_no_calibration_authority(self, env):
        registry, _, env_id = env
        (training, _inference) = _probe_and_record(env, train_ms=20.0)
        assert training.validation_status == "unvalidated"
        assert evaluate_promotions(registry.iter_observations(), generation=0) == []
        est = registry.as_estimate(training, current_environment_id=env_id)
        assert est.provenance == "historical_observation_prior"
        assert est.blocking_eligible is False

    def test_three_consistent_probes_promote_and_restore_authority(self, env):
        registry, _, env_id = env
        for ms in (20.0, 21.0, 22.0):
            training, _ = _probe_and_record(env, train_ms=ms)
        promotions = evaluate_promotions(
            registry.iter_observations(), generation=registry.load_manifest().generation
        )
        # training and inference promote as SEPARATE buckets (§16.6)
        assert {p.level for p in promotions} == {"validated"}
        assert len(promotions) == 2
        for promo in promotions:
            registry.record_promotion(promo)

        level, promo = registry.bucket_status(bucket_key(training))
        assert level == "validated" and promo is not None
        est = registry.as_estimate(training, current_environment_id=env_id)
        assert est.provenance == "bounded_live_probe"
        assert est.blocking_eligible is True

    def test_contended_probes_never_promote(self, env):
        registry, _, _ = env
        for ms in (30.0, 31.0, 32.0):
            _probe_and_record(env, train_ms=ms, contention=BUSY)
        assert list(registry.iter_observations())  # persisted as candidates…
        assert evaluate_promotions(registry.iter_observations(), generation=1) == []

    def test_validated_history_cannot_price_an_out_of_range_candidate(self, env):
        registry, _, env_id = env
        for ms in (20.0, 21.0, 22.0):
            training, _ = _probe_and_record(env, train_ms=ms)
        for promo in evaluate_promotions(registry.iter_observations(), generation=0):
            registry.record_promotion(promo)
        est = registry.as_estimate(training, current_environment_id=env_id)
        assert est.blocking_eligible is True

        summary = registry.derive_summary(operation="training")
        assert summary.parameter_count_range == (45_408, 45_408)
        label, reasons = applicability_for_request(
            requested={"parameter_count": 18_400_000},
            observed_ranges={"parameter_count": summary.parameter_count_range},
        )
        assert label == "unsupported_extrapolation"
        downgraded = downgrade_for_applicability(est, label, reasons=reasons)
        assert downgraded.blocking_eligible is False
        assert downgraded.advisory_eligible is True
