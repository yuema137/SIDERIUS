from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from agent.schemas.task_config import ForwardContract
from execute_tools.dataset_config import DatasetProfile
from execute_tools.evaluation_metric import MetricSpec, PresenceScoreabilityContract
from execute_tools.health_checks._composition import HealthBindingState
from workflows.data_analysis_composition import compose_workflow_data_analysis
from workflows.task_composition import compute_semantic_fingerprint


class _AnalysisCapableTask:
    def materialize_analysis_view(self, request):  # pragma: no cover - composition only
        raise NotImplementedError

    def export_analysis_materialization(self, content_ref, destination):  # pragma: no cover
        raise NotImplementedError

    def derive_historical_inference_input_asset(self, request):  # pragma: no cover
        raise NotImplementedError


def _write_config(tmp_path, *, indent: int = 2):
    config = {
        "scientific_goal": "Characterize authorized synthetic observations.",
        "input_description": "Scalar numeric measurements.",
        "available_assets": [
            {
                "asset_id": "validation-values",
                "asset_type": "dataset",
                "description": "Authorized validation measurements.",
                "location": {
                    "kind": "workspace_artifact",
                    "artifact_ref": {
                        "logical_ref": "inputs/validation-values.bin",
                        "sha256": "3" * 64,
                        "media_type": "application/octet-stream",
                    },
                },
                "provenance": {"producer": "synthetic-task"},
                "authorized_scope": {
                    "kind": "artifact_intrinsic",
                    "split_id": "validation",
                    "description": "Validation observations.",
                },
                "split_id": "validation",
            }
        ],
        "declared_scope": {"raw_input_asset_ids": ["validation-values"]},
        "access_policy": {
            "policy_id": "synthetic-analysis-policy",
            "policy_version": 1,
            "purpose": "Scientific characterization.",
            "split_rules": [{"split_id": "validation", "data_visible": True}],
        },
        "resource_envelope": {
            "wall_time_budget_s": 30,
            "per_skill_timeout_s": 10,
            "preferred_device": "cpu",
        },
        "builtin_skill_packs": ["core-analysis"],
    }
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps(config, indent=indent), encoding="utf-8")
    return path


def _compose(tmp_path, config_path, *, task_data_path=None):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text('{"synthetic":true}', encoding="utf-8")
    metric = SimpleNamespace(
        spec=SimpleNamespace(
            id="synthetic_error",
            direction="lower",
            aggregation="mean",
        )
    )
    return compose_workflow_data_analysis(
        {"enabled": True, "config": config_path.name},
        manifest_path=str(tmp_path / "task.yaml"),
        task_data_path=task_data_path or _AnalysisCapableTask(),
        task_data_path_id="synthetic-task-data",
        task_description="A generic synthetic regression task.",
        forward_contract=ForwardContract(),
        metric=metric,
        dataset_profile_ref="profile.json",
        dataset_profile_path=str(profile_path),
    )


def test_disabled_analysis_has_no_resolved_binding_or_manifest_reads(tmp_path) -> None:
    assert (
        compose_workflow_data_analysis(
            {"enabled": False},
            manifest_path=str(tmp_path / "task.yaml"),
            task_data_path=object(),
            task_data_path_id="unused",
            task_description="unused",
            forward_contract=ForwardContract(),
            metric=object(),
            dataset_profile_ref="unused",
            dataset_profile_path=str(tmp_path / "missing-profile.json"),
        )
        is None
    )


def test_enabled_analysis_resolves_caller_policy_without_importing_task_semantics(tmp_path) -> None:
    config_path = _write_config(tmp_path)
    binding = _compose(tmp_path, config_path)

    assert binding is not None
    assert binding.task_context.task_id == "synthetic-task-data"
    assert binding.task_context.metric_identity == ("synthetic_error", "lower")
    assert binding.available_assets[0].asset_id == "validation-values"
    assert binding.allowed_skill_packs[0].pack_id == "core-analysis"
    assert binding.allowed_skill_packs[0].manifest_ref.media_type == "application/json"


def test_task_declared_scope_identity_reaches_workflow_binding(tmp_path) -> None:
    path = _write_config(tmp_path)
    raw = json.loads(path.read_text())
    binding = _compose(tmp_path, path)
    assert binding is not None
    assert binding.declared_scope.raw_input_asset_ids == ("validation-values",)
    assert binding.canonical_identity()["declared_scope"]["raw_input_asset_ids"] == [
        "validation-values"
    ]
    raw["declared_scope"]["raw_input_asset_ids"] = ["unknown"]
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="declared raw input"):
        _compose(tmp_path, path)


def test_analysis_identity_uses_semantics_not_config_formatting_or_host_path(tmp_path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first = _compose(first_dir, _write_config(first_dir, indent=2))
    second = _compose(second_dir, _write_config(second_dir, indent=4))

    assert first is not None and second is not None
    assert first.config_content_sha256 != second.config_content_sha256
    assert first.config_path != second.config_path
    assert first.canonical_identity() == second.canonical_identity()
    assert (
        hashlib.sha256(json.dumps(first.canonical_identity(), sort_keys=True).encode()).hexdigest()
        == hashlib.sha256(
            json.dumps(second.canonical_identity(), sort_keys=True).encode()
        ).hexdigest()
    )


def test_enabling_analysis_changes_composition_identity_once(tmp_path) -> None:
    binding = _compose(tmp_path, _write_config(tmp_path))
    assert binding is not None
    common = {
        "task_data_path_id": "synthetic-task-data",
        "dataset_profile": DatasetProfile(
            dataset_id="synthetic",
            partition_count=1,
            anchor_selection_files=[0],
            health_peek_files=[0],
            topology={},
        ),
        "metric_declaration": MetricSpec(
            id="synthetic_error",
            direction="lower",
            aggregation="mean",
            scoreability=PresenceScoreabilityContract(),
        ).model_dump(mode="json"),
        "task_health_binding": HealthBindingState.EXPLICIT_NONE,
        "task_health_content": None,
        "interpretation_blocks": None,
        "task_description": "A generic synthetic regression task.",
        "forward_contract": ForwardContract(),
        "plugins": (),
    }

    disabled = compute_semantic_fingerprint(**common)
    enabled = compute_semantic_fingerprint(**common, data_analysis=binding)

    assert disabled != enabled


def test_generated_skill_promotion_is_explicit_workflow_policy(tmp_path) -> None:
    config_path = _write_config(tmp_path)
    default_binding = _compose(tmp_path, config_path)
    assert default_binding is not None
    assert default_binding.allow_generated_skill_promotion is False
    assert "allow_generated_skill_promotion" not in default_binding.canonical_identity()

    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["allow_generated_skill_promotion"] = True
    config_path.write_text(json.dumps(config), encoding="utf-8")
    promoted_binding = _compose(tmp_path, config_path)
    assert promoted_binding is not None
    assert promoted_binding.allow_generated_skill_promotion is True
    assert promoted_binding.canonical_identity()["allow_generated_skill_promotion"] is True
    assert promoted_binding.canonical_identity() != default_binding.canonical_identity()


def test_generated_skill_promotion_refuses_non_boolean_config(tmp_path) -> None:
    config_path = _write_config(tmp_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["allow_generated_skill_promotion"] = "true"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="allow_generated_skill_promotion"):
        _compose(tmp_path, config_path)


def test_historical_inference_base_is_explicit_workflow_policy(tmp_path) -> None:
    """An enabled inference policy still cannot choose an input asset by convention."""

    config_path = _write_config(tmp_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["historical_inference_base_asset_id"] = "validation-values"
    config["access_policy"]["allow_model_inference"] = True
    config["access_policy"]["split_rules"][0]["predictions_visible"] = True
    config_path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="task-owned data"):
        _compose(tmp_path, config_path)

    profile_payload = b'{"synthetic":true}'
    config["available_assets"][0]["location"] = {
        "kind": "task_data",
        "task_data_path_id": "synthetic-task-data",
        "dataset_profile_sha256": hashlib.sha256(profile_payload).hexdigest(),
        "logical_role": "validation_features",
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    resolved = _compose(tmp_path, config_path)
    assert resolved is not None
    assert resolved.historical_inference_base_asset_id == "validation-values"
    assert resolved.canonical_identity()["historical_inference_base_asset_id"] == (
        "validation-values"
    )

    class NoHistoricalDerivation:
        materialize_analysis_view = _AnalysisCapableTask.materialize_analysis_view
        export_analysis_materialization = _AnalysisCapableTask.export_analysis_materialization

    with pytest.raises(ValueError, match="TaskHistoricalInferenceInputCapability"):
        _compose(tmp_path, config_path, task_data_path=NoHistoricalDerivation())

    config["access_policy"]["allow_model_inference"] = False
    config_path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="requires model inference policy"):
        _compose(tmp_path, config_path)


def test_recovery_policy_reaches_binding_and_changes_identity(tmp_path):
    """Fails if a policy is parsed but lost before run identity is built."""
    path = _write_config(tmp_path)
    native = _compose(tmp_path, path)
    config = json.loads(path.read_text())
    config["recovery_policy"] = {
        "schema_version": 1,
        "generated_program_retries": 0,
        "plan_retries": 2,
    }
    path.write_text(json.dumps(config))
    explicit = _compose(tmp_path, path)
    assert explicit.recovery_policy.generated_program_retries == 0
    assert explicit.recovery_policy.plan_retries == 2
    assert explicit.canonical_identity()["recovery_policy"] == config["recovery_policy"]
    assert native.canonical_identity() != explicit.canonical_identity()
