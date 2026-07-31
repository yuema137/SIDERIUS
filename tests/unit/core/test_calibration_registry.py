"""C5 — calibration registry: schemas, identities, atomic storage,
concurrency, derived applicability, legacy adapter, cross-machine rule.

Covers the operator's §7 validation list from the C5 approval.
Everything runs against tmp roots (portability rule: no dependence on a
developer-local calibration file — the legacy adapter is tested on a
schema-faithful fixture, read-only)."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.runtime_control.calibration_registry import (
    CalibrationRegistry,
    adapt_legacy_k_table,
    default_registry_root,
)
from core.runtime_control.estimate_types import from_legacy_calibration_entry
from core.runtime_control.registry_schemas import (
    CalibrationObservation,
    ExecutionEnvironmentProfile,
    HardwareCompatibilityProfile,
    content_id,
    display_id,
)


def _hw(**over) -> HardwareCompatibilityProfile:
    base = dict(
        accelerator_vendor="NVIDIA",
        accelerator_model="GeForce RTX 5090",
        gpu_count=1,
        vram_gb=31.34,
        compute_capability="12.0",
        driver_version="575.x",
        cuda_version="12.8",
        torch_version="2.7.0",
        dtypes=("float32", "bfloat16"),
    )
    base.update(over)
    return HardwareCompatibilityProfile(**base)


def _env(hw_id: str, install: str, **over) -> ExecutionEnvironmentProfile:
    base = dict(
        hardware_compatibility_id=hw_id,
        installation_id=install,
        storage_class="nvme",
        concurrency_regime="single_candidate_idle",
    )
    base.update(over)
    return ExecutionEnvironmentProfile(**base)


def _obs(hw_id: str, env_id: str, **over) -> CalibrationObservation:
    base = dict(
        operation="training",
        measurement_unit="optimizer_step",
        measured_value_ms=21.4,
        workload={"batch_size": 8, "segment_length": 40_000, "steps": 3125},
        realized_model={"parameter_count": 156_320},
        hardware_compatibility_id=hw_id,
        execution_environment_id=env_id,
        concurrency_identity="single_candidate_idle",
        software_stack={"torch": "2.7.0"},
        producer_identity="runtime_probe@0.0.0+test",
        provenance="bounded_live_probe",
        # C7/D4: producers always write candidates; authority comes from
        # a CalibrationPromotion, never from this field.
        validation_status="unvalidated",
        timestamp_metadata="2026-07-30T12:00:00Z",
    )
    base.update(over)
    return CalibrationObservation(**base)


@pytest.fixture
def registry(tmp_path) -> CalibrationRegistry:
    return CalibrationRegistry(tmp_path / "runtime_calibration")


HW = _hw()
ENV_LOCAL = _env(HW.profile_id, "11111111-1111-1111-1111-111111111111")
ENV_REMOTE = _env(HW.profile_id, "22222222-2222-2222-2222-222222222222")


class TestIdentities:
    def test_full_digest_persisted_and_display_alias(self):
        obs = _obs(HW.profile_id, ENV_LOCAL.profile_id)
        oid = obs.observation_id
        assert oid.startswith("sha256:") and len(oid) == 7 + 64
        assert display_id(oid).startswith("sha256:") and display_id(oid).endswith("…")
        assert len(display_id(oid)) == 7 + 12 + 1

    def test_deterministic_across_equivalent_constructions(self):
        a = _obs(HW.profile_id, ENV_LOCAL.profile_id)
        b = _obs(HW.profile_id, ENV_LOCAL.profile_id)
        assert a.observation_id == b.observation_id

    def test_timestamp_is_metadata_not_content(self):
        a = _obs(HW.profile_id, ENV_LOCAL.profile_id, timestamp_metadata="2026-01-01T00:00:00Z")
        b = _obs(HW.profile_id, ENV_LOCAL.profile_id, timestamp_metadata="2026-12-31T23:59:59Z")
        assert a.observation_id == b.observation_id

    def test_semantic_change_changes_id(self):
        a = _obs(HW.profile_id, ENV_LOCAL.profile_id)
        b = _obs(HW.profile_id, ENV_LOCAL.profile_id, measured_value_ms=22.0)
        assert a.observation_id != b.observation_id

    def test_prior_provenance_cannot_be_stored_as_observation(self):
        """The legacy inference-batch fallback (a prior) can never be
        encoded as a measured observation."""
        with pytest.raises(ValidationError, match="prior"):
            _obs(HW.profile_id, ENV_LOCAL.profile_id, provenance="static_uncalibrated")


class TestStorage:
    def test_roundtrip_and_dedup(self, registry):
        obs = _obs(HW.profile_id, ENV_LOCAL.profile_id)
        oid1 = registry.record_observation(obs)
        oid2 = registry.record_observation(obs)  # identical → dedup
        assert oid1 == oid2
        manifest = registry.load_manifest()
        assert manifest.observation_ids == [oid1]
        loaded = registry.load_observation(oid1)
        assert loaded.measured_value_ms == obs.measured_value_ms

    def test_different_records_do_not_dedup(self, registry):
        registry.record_observation(_obs(HW.profile_id, ENV_LOCAL.profile_id))
        registry.record_observation(
            _obs(
                HW.profile_id,
                ENV_LOCAL.profile_id,
                operation="inference",
                measurement_unit="segment",
            )
        )
        assert len(registry.load_manifest().observation_ids) == 2

    def test_concurrent_writers_do_not_corrupt(self, registry):
        def _write(i: int) -> str:
            return registry.record_observation(
                _obs(HW.profile_id, ENV_LOCAL.profile_id, measured_value_ms=10.0 + i)
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = list(pool.map(_write, range(40)))
        manifest = registry.load_manifest()
        assert sorted(set(ids)) == manifest.observation_ids
        assert len(manifest.observation_ids) == 40
        for oid in manifest.observation_ids:  # every committed record loads + verifies
            registry.load_observation(oid)

    def test_interrupted_write_is_never_discoverable(self, registry):
        stray = registry._obs_dir / ("deadbeef" * 8 + ".json.tmp1234")
        stray.write_text("{ partial garbage")
        manifest, rejected = registry.rebuild_index()
        assert manifest.observation_ids == []
        assert rejected == []  # tmp artifact is not even considered

    def test_index_reconstruction_from_records(self, registry):
        ids = [
            registry.record_observation(
                _obs(HW.profile_id, ENV_LOCAL.profile_id, measured_value_ms=10.0 + i)
            )
            for i in range(5)
        ]
        (registry.root / "registry.json").unlink()
        manifest, rejected = registry.rebuild_index()
        assert manifest.observation_ids == sorted(ids)
        assert rejected == []

    def test_corruption_detected_and_excluded(self, registry):
        oid = registry.record_observation(_obs(HW.profile_id, ENV_LOCAL.profile_id))
        path = registry._obs_dir / f"{oid.split(':')[1]}.json"
        data = json.loads(path.read_text())
        data["measured_value_ms"] = 999.0  # tamper without renaming
        path.write_text(json.dumps(data))
        with pytest.raises(ValueError, match="mismatch"):
            registry.load_observation(oid)
        manifest, rejected = registry.rebuild_index()
        assert manifest.observation_ids == []
        assert len(rejected) == 1 and "mismatch" in rejected[0]

    def test_orphan_record_readopted_by_rebuild(self, registry):
        obs = _obs(HW.profile_id, ENV_LOCAL.profile_id)
        registry._write_record(
            registry._obs_dir, obs.observation_id, obs.model_dump(mode="json")
        )  # record written, index never committed (simulated crash)
        assert registry.load_manifest().observation_ids == []
        manifest, _ = registry.rebuild_index()
        assert manifest.observation_ids == [obs.observation_id]

    def test_env_override_honored(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SIDERIUS_CALIBRATION_DIR", str(tmp_path / "custom"))
        assert default_registry_root() == tmp_path / "custom" / "runtime_calibration"


class TestProfilesAndCrossMachine:
    def test_environment_separation_same_compat(self, registry):
        registry.put_hardware_profile(HW)
        registry.put_environment_profile(ENV_LOCAL)
        registry.put_environment_profile(ENV_REMOTE)
        assert ENV_LOCAL.hardware_compatibility_id == ENV_REMOTE.hardware_compatibility_id
        assert ENV_LOCAL.profile_id != ENV_REMOTE.profile_id
        manifest = registry.load_manifest()
        assert len(manifest.environment_profile_ids) == 2
        assert len(manifest.hardware_profile_ids) == 1

    def test_no_hostname_in_profiles(self):
        import socket

        for payload in (HW.model_dump(mode="json"), ENV_LOCAL.model_dump(mode="json")):
            assert socket.gethostname() not in json.dumps(payload)

    def test_cross_machine_evidence_is_historical_prior_only(self, registry):
        obs = _obs(HW.profile_id, ENV_REMOTE.profile_id)
        est = registry.as_estimate(
            obs, current_environment_id=ENV_LOCAL.profile_id, validation_level="validated"
        )
        assert est.provenance == "historical_observation_prior"
        assert est.blocking_eligible is False
        assert any("cross-machine" in w for w in est.warnings)

    def test_local_validated_evidence_keeps_measured_provenance(self, registry):
        # C7/D4: authority comes from the bucket's PROMOTION level, never
        # from a self-declared status on the immutable observation.
        obs = _obs(HW.profile_id, ENV_LOCAL.profile_id)
        est = registry.as_estimate(
            obs, current_environment_id=ENV_LOCAL.profile_id, validation_level="validated"
        )
        assert est.provenance == "bounded_live_probe"
        assert est.blocking_eligible is True
        assert est.training_seconds is not None and est.inference_seconds is None

    def test_local_unpromoted_bucket_is_demoted(self, registry):
        obs = _obs(HW.profile_id, ENV_LOCAL.profile_id)
        # No promotion recorded → bucket_status() == "unvalidated".
        est = registry.as_estimate(obs, current_environment_id=ENV_LOCAL.profile_id)
        assert est.provenance == "historical_observation_prior"
        assert est.blocking_eligible is False
        assert any("validation level" in w for w in est.warnings)

    def test_provisional_is_not_calibration_authoritative(self, registry):
        obs = _obs(HW.profile_id, ENV_LOCAL.profile_id)
        est = registry.as_estimate(
            obs, current_environment_id=ENV_LOCAL.profile_id, validation_level="provisional"
        )
        assert est.provenance == "historical_observation_prior"
        assert est.blocking_eligible is False


class TestPromotionPersistence:
    """C7/D4: promotions are DERIVED, immutable, content-addressed records
    that never mutate the observations they cite."""

    def _promoted(self, registry, values=(20.0, 21.0, 22.0)):
        from core.runtime_control.calibration_policy import evaluate_promotions

        obs = [_obs(HW.profile_id, ENV_LOCAL.profile_id, measured_value_ms=v) for v in values]
        for o in obs:
            registry.record_observation(o)
        promos = evaluate_promotions(obs, generation=registry.load_manifest().generation)
        return obs, promos

    def test_record_load_and_index(self, registry):
        obs, promos = self._promoted(registry)
        assert len(promos) == 1
        pid = registry.record_promotion(promos[0])
        manifest = registry.load_manifest()
        assert manifest.promotion_ids == [pid]
        assert registry.load_promotion(pid) == promos[0]
        assert (registry.root / "promotions").is_dir()
        # observations on disk are untouched by the promotion
        for o in obs:
            assert registry.load_observation(o.observation_id).validation_status == "unvalidated"

    def test_bucket_status_is_the_authority(self, registry):
        from core.runtime_control.calibration_policy import bucket_key

        obs, promos = self._promoted(registry)
        key = bucket_key(obs[0])
        assert registry.bucket_status(key) == ("unvalidated", None)
        registry.record_promotion(promos[0])
        level, promo = registry.bucket_status(key)
        assert level == "validated" and promo is not None
        assert registry.bucket_status("some|other|bucket") == ("unvalidated", None)

    def test_validated_bucket_restores_measured_authority_end_to_end(self, registry):
        obs, promos = self._promoted(registry)
        registry.record_promotion(promos[0])
        est = registry.as_estimate(obs[0], current_environment_id=ENV_LOCAL.profile_id)
        assert est.provenance == "bounded_live_probe"
        assert est.blocking_eligible is True

    def test_promotion_cannot_cite_unindexed_observations(self, registry):
        from core.runtime_control.calibration_policy import evaluate_promotions

        obs = [_obs(HW.profile_id, ENV_LOCAL.profile_id, measured_value_ms=v) for v in (20.0, 21.0)]
        promo = evaluate_promotions(obs, generation=0)[0]
        with pytest.raises(ValueError, match="absent from the index"):
            registry.record_promotion(promo)

    def test_recording_the_same_promotion_twice_is_idempotent(self, registry):
        _, promos = self._promoted(registry)
        first = registry.record_promotion(promos[0])
        gen = registry.load_manifest().generation
        assert registry.record_promotion(promos[0]) == first
        assert registry.load_manifest().generation == gen

    def test_rebuild_drops_promotions_whose_sources_vanished(self, registry):
        obs, promos = self._promoted(registry)
        registry.record_promotion(promos[0])
        victim = registry.root / "observations" / f"{obs[0].observation_id.split(':')[1]}.json"
        victim.unlink()
        manifest, rejected = registry.rebuild_index()
        assert manifest.promotion_ids == []
        assert any("missing observations" in r for r in rejected)

    def test_tampered_promotion_is_detected(self, registry):
        _, promos = self._promoted(registry)
        pid = registry.record_promotion(promos[0])
        path = registry.root / "promotions" / f"{pid.split(':')[1]}.json"
        payload = json.loads(path.read_text())
        payload["rate_median_ms"] = 1.0
        path.write_text(json.dumps(payload))
        with pytest.raises(ValueError, match="content-hash mismatch"):
            registry.load_promotion(pid)


class TestDerivedApplicability:
    def test_summary_derivation_and_stale_detection(self, registry):
        registry.record_observation(
            _obs(HW.profile_id, ENV_LOCAL.profile_id, realized_model={"parameter_count": 50_000})
        )
        registry.record_observation(
            _obs(
                HW.profile_id,
                ENV_LOCAL.profile_id,
                measured_value_ms=44.0,
                realized_model={"parameter_count": 5_000_000},
            )
        )
        summary = registry.derive_summary(operation="training")
        assert summary.parameter_count_range == (50_000, 5_000_000)
        assert summary.sample_count == 2
        registry.save_summary_cache("training", summary)
        _, stale = registry.load_summary_cache("training")
        assert stale is False
        registry.record_observation(
            _obs(HW.profile_id, ENV_LOCAL.profile_id, measured_value_ms=99.0)
        )
        _, stale = registry.load_summary_cache("training")
        assert stale is True  # generation moved

    def test_summary_rebuildable_deterministically(self, registry):
        registry.record_observation(_obs(HW.profile_id, ENV_LOCAL.profile_id))
        s1 = registry.derive_summary(operation="training")
        s2 = registry.derive_summary(operation="training")
        assert s1 == s2


class TestLegacyAdapter:
    @pytest.fixture
    def legacy_file(self, tmp_path) -> Path:
        table = {
            "gpu_name": "NVIDIA GeForce RTX 5090",
            "k_values": {"punet": 1.05, "*": 1.1},
            "history": [
                {
                    "gpu_name": "NVIDIA GeForce RTX 5090",
                    "model_type": "punet",
                    "seg_size": 40_000,
                    "batch_size": 8,
                    "total_steps": 3125,
                    "warmup_ms_per_step": 3.79,
                    "actual_ms_per_step": 4.11,
                    "ratio": 1.08,
                    "estimated_minutes": 1.2,
                    "actual_minutes": 1.4,
                    "estimate_violated": True,
                    "timestamp": "2026-07-20T16:10:16Z",
                },
                {"model_type": "broken", "actual_ms_per_step": 0},  # unusable → skipped
            ],
        }
        path = tmp_path / "time_calibration_nvidia_geforce_rtx_5090.json"
        path.write_text(json.dumps(table))
        return path

    def test_adapter_reads_without_modifying_source(self, legacy_file, registry):
        before = legacy_file.read_bytes()
        ref, _entries = adapt_legacy_k_table(legacy_file)
        assert legacy_file.read_bytes() == before  # byte-identical: read-only
        assert ref.entry_count == 1 and ref.adapter_version == "1.0.0"
        assert ref.gpu_slug == "nvidia_geforce_rtx_5090"
        assert len(ref.file_sha256) == 64
        registry.reference_legacy_source(ref)
        registry.reference_legacy_source(ref)  # idempotent
        assert len(registry.load_manifest().legacy_sources) == 1

    def test_adapted_entries_stay_legacy_provenance(self, legacy_file):
        _, entries = adapt_legacy_k_table(legacy_file)
        est = from_legacy_calibration_entry(entries[0])
        assert est.provenance == "legacy_calibration_prior"
        assert est.blocking_eligible is False
        assert est.formal_execution_eligible is False


class TestManifestSafety:
    def test_corrupt_index_raises_with_rebuild_hint(self, registry):
        registry.record_observation(_obs(HW.profile_id, ENV_LOCAL.profile_id))
        (registry.root / "registry.json").write_text("{not json")
        with pytest.raises(ValueError, match="rebuild_index"):
            registry.load_manifest()

    def test_generation_increments_only_on_change(self, registry):
        obs = _obs(HW.profile_id, ENV_LOCAL.profile_id)
        registry.record_observation(obs)
        g1 = registry.load_manifest().generation
        registry.record_observation(obs)  # dedup: no change
        assert registry.load_manifest().generation == g1

    def test_content_id_matches_identity_module_semantics(self):
        assert content_id({"a": 1, "b": {"y": 2, "x": 3}}) == content_id(
            {"b": {"x": 3, "y": 2}, "a": 1}
        )
