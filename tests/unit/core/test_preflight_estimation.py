"""Arithmetic selection is explicit, pinned and separate from execution policy."""

import json
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from agent.schemas.preflight import StaticPhaseDecision, StaticPreflightEvidence
from core import preflight_estimation as providers
from core.preflight_observations import PhaseEstimate, PhaseObservations, RegisteredStateInventory


def observations():
    return PhaseObservations(
        phase="inference",
        batch_size=3,
        leaf_parameter_bytes=7,
        leaf_output_bytes_sum=9,
        leaf_output_bytes_max=9,
        input_bytes=2,
        output_bytes=9,
        model_state=RegisteredStateInventory(status="unavailable", reason="unsupported layout"),
        training_config={"optimizer": "sgd", "optimizer_type": "adamw"},
    )


def fixed_estimate(observed):
    return PhaseEstimate(
        phase=observed.phase,
        admission_bytes=7,
        diagnostic_bytes=3,
        estimator="synthetic-v1",
        breakdown={"synthetic_bytes": 3},
    )


def profile(tmp_path, estimate=fixed_estimate):
    source = tmp_path / "provider.py"
    source.write_text("# Frozen synthetic estimator\n")
    return providers.PreflightEstimatorProfile(
        "synthetic-v1",
        "1",
        estimate,
        {"provider.py": source},
        frozenset({providers.estimation_assembly_digest()}),
    )


def test_installation_never_changes_native_default(tmp_path, monkeypatch):
    external = profile(tmp_path)
    entry = SimpleNamespace(name=external.name, load=lambda: lambda: external)
    monkeypatch.setattr(providers, "entry_points", lambda **kwargs: [entry])
    assert providers.resolve_preflight_estimator().name == providers.NATIVE_ESTIMATOR
    assert providers.resolve_preflight_estimator(external.name) is external
    with pytest.raises(ValueError, match="found 0"):
        providers.resolve_preflight_estimator("missing")
    monkeypatch.setattr(providers, "entry_points", lambda **kwargs: [entry, entry])
    with pytest.raises(ValueError, match="found 2"):
        providers.resolve_preflight_estimator(external.name)


def test_unavailable_native_inventory_does_not_preempt_external_arithmetic(tmp_path):
    external = profile(tmp_path)
    native = providers.active_preflight_identity()
    with providers.bind_preflight_estimator(external):
        assert providers.estimate_phase(observations()).admission_bytes == 7
        assert providers.active_preflight_identity() == external.identity()
    assert providers.active_preflight_identity() == native
    with pytest.raises(ValueError, match="unsupported layout"):
        providers.estimate_phase(observations())


def test_provider_cannot_mutate_original_training_declaration(tmp_path):
    original = observations()

    def mutate(value):
        assert value.training_config == {"optimizer": "sgd", "optimizer_type": "adamw"}
        value.training_config.clear()
        return fixed_estimate(value)

    with providers.bind_preflight_estimator(profile(tmp_path, mutate)):
        providers.estimate_phase(original)
    assert original.training_config["optimizer"] == "sgd"


@pytest.mark.parametrize("kind", ["wrong_phase", "bad_sum", "negative", "raw_dict"])
def test_provider_result_is_revalidated(tmp_path, kind):
    result = fixed_estimate(observations())
    invalid = {
        "wrong_phase": result.model_copy(update={"phase": "training"}),
        "bad_sum": result.model_copy(update={"diagnostic_bytes": 100}),
        "negative": result.model_copy(update={"admission_bytes": -1}),
        "raw_dict": result.model_dump(),
    }[kind]
    with providers.bind_preflight_estimator(profile(tmp_path, lambda _: invalid)):
        with pytest.raises((ValueError, TypeError)):
            providers.estimate_phase(observations())


def test_changed_source_and_worker_identity_fail_closed(tmp_path):
    external = profile(tmp_path)
    identity = external.identity()
    with providers.bind_preflight_estimator(external):
        (tmp_path / "provider.py").write_text("# Changed during execution\n")
        with pytest.raises(ValueError, match="changed during"):
            providers.estimate_phase(observations())
    with pytest.raises(ValueError, match="changed after"):
        with providers.bind_preflight_estimator(external, expected=identity):
            pytest.fail("changed provider was bound")


def test_assembly_changes_native_identity_and_rejects_unqualified_external(tmp_path, monkeypatch):
    external = profile(tmp_path)
    original = providers.active_preflight_identity()
    monkeypatch.setattr(providers, "estimation_assembly_digest", lambda: "a" * 64)
    assert providers.active_preflight_identity() != original
    with pytest.raises(ValueError, match="not qualified"):
        external.identity()


def test_scope_unwinds_on_failure(tmp_path):
    native = providers.active_preflight_identity()
    with pytest.raises(RuntimeError):
        with providers.bind_preflight_estimator(profile(tmp_path)):
            raise RuntimeError("provider consumer failed")
    assert providers.active_preflight_identity() == native


def test_rule_only_change_is_pinned_and_rejected_at_worker_binding(tmp_path):
    """#689: unchanged source files cannot hide a changed workload rule."""
    original = profile(tmp_path)
    guarded = replace(original, workload_rule=providers.BatchSegmentationLimit(limit=800_000))
    different = replace(guarded, workload_rule=providers.BatchSegmentationLimit(limit=900_000))
    assert len({p.identity().content_sha256 for p in (original, guarded, different)}) == 3
    with pytest.raises(ValueError, match="changed after"):
        with providers.bind_preflight_estimator(different, expected=guarded.identity()):
            pytest.fail("worker accepted a different rule with unchanged provider sources")
    with providers.bind_preflight_estimator(guarded):
        object.__setattr__(guarded, "workload_rule", different.workload_rule)
        with pytest.raises(ValueError, match="changed during"):
            providers.active_workload_rule()


def test_rule_is_revalidated_at_profile_boundary(tmp_path):
    """Trusted providers can bypass Pydantic construction; binding must not."""
    invalid = providers.BatchSegmentationLimit.model_construct(limit=-1)
    with pytest.raises(ValueError):
        replace(profile(tmp_path), workload_rule=invalid)


def test_composition_pins_explicit_and_native_identity(tmp_path, monkeypatch):
    from workflows import task_composition as composition

    root = Path(__file__).resolve().parents[3]
    task = tmp_path / "task"
    shutil.copytree(root / "tests/fixtures/step10_p1/fourth_task", task)
    manifest = task / "composition.yaml"
    native = composition.compose_run_task_bindings(str(manifest))
    external = profile(tmp_path)
    declaration = yaml.safe_load(manifest.read_text())
    declaration["preflight_estimator"] = external.name
    manifest.write_text(yaml.safe_dump(declaration))
    monkeypatch.setattr(composition, "resolve_preflight_estimator", lambda _: external)
    bound = composition.compose_run_task_bindings(str(manifest))
    assert bound.semantic_fingerprint != native.semantic_fingerprint
    guarded = replace(external, workload_rule=providers.BatchSegmentationLimit(limit=800_000))
    monkeypatch.setattr(composition, "resolve_preflight_estimator", lambda _: guarded)
    guarded_bound = composition.compose_run_task_bindings(str(manifest))
    assert guarded_bound.semantic_fingerprint != bound.semantic_fingerprint
    monkeypatch.setattr(composition, "resolve_preflight_estimator", lambda _: external)
    with composition.bind_run_task_composition(bound, physical_data_root=str(tmp_path)):
        composition.verify_composition_is_bound(bound)
        assert providers.active_preflight_identity() == external.identity()
    (tmp_path / "provider.py").write_text("# new implementation\n")
    with pytest.raises(ValueError, match="changed after"):
        with composition.bind_run_task_composition(bound, physical_data_root=str(tmp_path)):
            pytest.fail("composition source drift was accepted")


def test_archived_evidence_is_readable_but_new_evidence_requires_identity():
    phase = StaticPhaseDecision(
        phase="inference",
        batch_size=3,
        vram_cap_bytes=10,
        vram_estimate_bytes=7,
        estimator="inference_leaf_sum_v1",
    )
    old = StaticPreflightEvidence(phases=(phase,))
    assert StaticPreflightEvidence.model_validate_json(old.model_dump_json()) == old
    with pytest.raises(ValueError, match="requires a pinned"):
        StaticPreflightEvidence(version="static-preflight-v2", phases=(phase,))
    current = StaticPreflightEvidence(
        version="static-preflight-v2",
        phases=(phase,),
        estimator_identity=providers.active_preflight_identity(),
    )
    assert json.loads(current.model_dump_json())["estimator_identity"]["assembly_sha256"]
