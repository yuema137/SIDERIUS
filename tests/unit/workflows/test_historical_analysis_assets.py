"""The workflow may expose only exact prior-model and task-derived assets."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from agent.schemas.data_analysis.access import AnalysisAccessPolicy, SplitAccessRule
from agent.schemas.data_analysis.common import CertifiedArtifactRef, canonical_json_bytes
from agent.schemas.data_analysis.report import (
    AnalysisResourceSummary,
    DataAnalysisReport,
    DataAnalysisReportProvenance,
    QuestionOutcome,
)
from agent.schemas.data_analysis.source_scope import DeclaredAnalysisScope
from agent.schemas.data_analysis.trained_model import TrainedModelArtifactRef
from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningOutput
from agent.schemas.interpretation import InterpretationOutput
from execute_tools.historical_model_inference import LocalPytorchHistoricalModelInferenceCapability
from execute_tools.trained_model_artifact import read_certified_artifact
from ml_models.plugin_binding import ResolvedModelPlugin, RunModelPluginBinding
from tests.unit.agent.data_analysis.test_historical_model_inference import _derivation_fixture
from tests.unit.nodes.test_data_analysis_agent import _input
from workflows.data_analysis_composition import ResolvedWorkflowDataAnalysis
from workflows.data_analysis_stage import run_optional_data_analysis
from workflows.historical_analysis_assets import (
    HistoricalTuningSource,
    derive_historical_analysis_assets,
    pair_prior_tuning_sources,
)
from workflows.historical_inference_bindings import (
    RunBoundHistoricalArtifactExporter,
    RunBoundHistoricalModelPluginResolver,
)


class _TaskDeriver:
    def __init__(self, derived) -> None:
        self.derived = derived
        self.seen_request = None

    def derive_historical_inference_input_asset(self, request):
        self.seen_request = request
        return self.derived

    def materialize_analysis_view(self, _request):  # pragma: no cover - not executed here
        raise AssertionError("derivation must not materialize data")

    def export_analysis_materialization(self, _ref, _destination):  # pragma: no cover
        raise AssertionError("derivation must not export data")


def _setup(tmp_path: Path):
    request, derived = _derivation_fixture()
    model = request.model_artifact
    artifact_payload = canonical_json_bytes(model)
    artifact_ref = CertifiedArtifactRef(
        logical_ref="trained_model_artifacts/model.json",
        sha256=hashlib.sha256(artifact_payload).hexdigest(),
        media_type="application/json",
        byte_size=len(artifact_payload),
    )
    model_ref = TrainedModelArtifactRef(
        artifact_ref=artifact_ref,
        model_artifact_id=model.model_artifact_id,
        executable_model_identity_sha256=model.executable_model_identity_sha256,
    )
    artifact_path = tmp_path / artifact_ref.logical_ref
    artifact_path.parent.mkdir()
    artifact_path.write_bytes(artifact_payload)
    (tmp_path / model.model_config_ref.logical_ref).write_text(
        request.model_config_json, encoding="utf-8"
    )
    profile_path = tmp_path / "dataset_profile.json"
    profile_path.write_text(request.dataset_profile_json, encoding="utf-8")
    record = ExperimentRecord(
        exp_id="experiment-1",
        status="success",
        model_type="synthetic_historical",
        timestamp="2026-09-16 00:00:00",
        params={},
        trained_model_artifact_ref=model_ref,
    )
    output = HyperparamTuningOutput(
        run_name="synthetic-run",
        model_type="synthetic_historical",
        file_index=0,
        status="completed",
        completed_rounds=1,
        total_attempts=1,
        all_records=[record],
        started_at="2026-09-16 00:00:00",
        finished_at="2026-09-16 00:00:01",
    )
    template = _input(tmp_path)
    deriver = _TaskDeriver(derived)
    binding = ResolvedWorkflowDataAnalysis(
        task_context=template.task_context,
        available_assets=(request.base_asset,),
        declared_scope=DeclaredAnalysisScope(raw_input_asset_ids=(request.base_asset.asset_id,)),
        access_policy=template.access_policy,
        resource_envelope=template.resource_envelope,
        allowed_skill_packs=template.allowed_skill_packs,
        task_analysis_capability=deriver,
        report_schema_version=1,
        config_content_sha256="7" * 64,
        config_path=str(tmp_path / "analysis.yaml"),
        historical_inference_base_asset_id=request.base_asset.asset_id,
        dataset_profile_path=str(profile_path),
    )
    source = HistoricalTuningSource(output=output, artifact_root=tmp_path)
    return request, binding, source, deriver


def test_only_certified_prior_record_exposes_candidate_input_and_model(tmp_path: Path) -> None:
    request, binding, source, deriver = _setup(tmp_path)

    result = derive_historical_analysis_assets(
        binding,
        sources=(source,),
        task_composition_fingerprint="3" * 64,
        run_name="synthetic-run",
        workspace_root=tmp_path,
    )

    assert [asset.asset_id for asset in result.binding.available_assets] == [
        request.base_asset.asset_id,
        "candidate-validation-features",
        f"historical-model-{request.model_artifact.model_artifact_id}",
    ]
    assert result.binding.declared_scope.raw_input_asset_ids == (
        request.base_asset.asset_id,
        "candidate-validation-features",
    )
    assert result.binding.declared_scope.historical_model_asset_ids == (
        f"historical-model-{request.model_artifact.model_artifact_id}",
    )
    assert deriver.seen_request.model_config_json == request.model_config_json
    assert (
        result.artifact_roots_by_sha256[request.model_artifact.model_config_ref.sha256] == tmp_path
    )


def test_historical_source_refusal_precedes_asset_visibility(tmp_path: Path) -> None:
    _request, binding, source, deriver = _setup(tmp_path)
    with pytest.raises(ValueError, match="another task composition"):
        derive_historical_analysis_assets(
            binding,
            sources=(source,),
            task_composition_fingerprint="4" * 64,
            run_name="synthetic-run",
            workspace_root=tmp_path,
        )
    assert deriver.seen_request is None

    artifact_path = (
        tmp_path / source.output.all_records[0].trained_model_artifact_ref.artifact_ref.logical_ref
    )
    artifact_path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="digest mismatch"):
        derive_historical_analysis_assets(
            binding,
            sources=(source,),
            task_composition_fingerprint="3" * 64,
            run_name="synthetic-run",
            workspace_root=tmp_path,
        )
    assert deriver.seen_request is None


def test_latest_artifact_bearing_output_survives_a_later_failed_candidate(tmp_path: Path) -> None:
    """Failure in a later iteration does not erase the last certified model."""

    request, binding, source, _deriver = _setup(tmp_path)
    failed_output = source.output.model_copy(
        update={"all_records": [], "status": "failed", "run_name": "later-failed-run"}
    )
    result = derive_historical_analysis_assets(
        binding,
        sources=(source, HistoricalTuningSource(output=failed_output, artifact_root=tmp_path)),
        task_composition_fingerprint="3" * 64,
        run_name="synthetic-run",
        workspace_root=tmp_path,
    )
    assert result.binding.available_assets[-1].asset_id == (
        f"historical-model-{request.model_artifact.model_artifact_id}"
    )


def test_other_run_history_is_not_exposed_as_analysis_source(tmp_path: Path) -> None:
    _request, binding, source, _deriver = _setup(tmp_path)
    result = derive_historical_analysis_assets(
        binding,
        sources=(source,),
        task_composition_fingerprint="3" * 64,
        run_name="different-run",
        workspace_root=tmp_path,
    )
    assert result.binding.available_assets == binding.available_assets
    assert result.binding.declared_scope.historical_model_asset_ids == ()


def test_all_completed_same_run_models_are_visible_in_order(tmp_path: Path) -> None:
    request, binding, first_source, _deriver = _setup(tmp_path)
    second_artifact = request.model_artifact.model_copy(
        update={
            "model_artifact_id": "model-second",
            "training_run": request.model_artifact.training_run.model_copy(
                update={"experiment_id": "experiment-2", "iteration_id": "iteration-2"}
            ),
        }
    )
    payload = canonical_json_bytes(second_artifact)
    second_ref = CertifiedArtifactRef(
        logical_ref="trained_model_artifacts/second.json",
        sha256=hashlib.sha256(payload).hexdigest(),
        media_type="application/json",
        byte_size=len(payload),
    )
    (tmp_path / second_ref.logical_ref).write_bytes(payload)
    second_record = ExperimentRecord(
        exp_id="experiment-2",
        status="success",
        model_type="synthetic_historical",
        timestamp="2026-09-16 00:01:00",
        params={},
        trained_model_artifact_ref=TrainedModelArtifactRef(
            artifact_ref=second_ref,
            model_artifact_id="model-second",
            executable_model_identity_sha256=second_artifact.executable_model_identity_sha256,
        ),
    )
    second_source = HistoricalTuningSource(
        output=first_source.output.model_copy(update={"all_records": [second_record]}),
        artifact_root=tmp_path,
    )
    result = derive_historical_analysis_assets(
        binding,
        sources=(first_source, second_source),
        task_composition_fingerprint="3" * 64,
        run_name="synthetic-run",
        workspace_root=tmp_path,
    )
    assert result.binding.declared_scope.historical_model_asset_ids == (
        f"historical-model-{request.model_artifact.model_artifact_id}",
        "historical-model-model-second",
    )


def test_same_named_run_outside_workspace_is_refused(tmp_path: Path) -> None:
    _request, binding, source, _deriver = _setup(tmp_path)
    with pytest.raises(ValueError, match="outside the current workspace"):
        derive_historical_analysis_assets(
            binding,
            sources=(source,),
            task_composition_fingerprint="3" * 64,
            run_name="synthetic-run",
            workspace_root=tmp_path / "another-workspace",
        )


def test_legacy_directory_is_not_artifact_authority(tmp_path: Path) -> None:
    _request, _binding, source, _deriver = _setup(tmp_path)
    with pytest.raises(ValueError, match="explicit prior run-output paths"):
        pair_prior_tuning_sources([source.output], None)
    paired = pair_prior_tuning_sources(
        [source.output], [str(tmp_path / "run_output_synthetic-run.json")]
    )
    assert paired[0].artifact_root == tmp_path


def test_certified_prior_artifact_ref_refuses_path_escape_and_symlinks(tmp_path: Path) -> None:
    request, _binding, _source, _deriver = _setup(tmp_path)
    ref = request.model_artifact.model_config_ref
    assert read_certified_artifact(tmp_path, ref) == request.model_config_json.encode("utf-8")
    for logical in ("../outside.json", str(tmp_path / ref.logical_ref)):
        with pytest.raises(ValueError, match="workspace-relative"):
            read_certified_artifact(tmp_path, ref.model_copy(update={"logical_ref": logical}))
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        read_certified_artifact(
            tmp_path,
            ref.model_copy(update={"logical_ref": f"alias/{ref.logical_ref}"}),
        )


def test_historical_exporter_and_plugin_resolver_use_only_run_bound_sources(tmp_path: Path) -> None:
    request, _binding, _source, _deriver = _setup(tmp_path)
    model = request.model_artifact
    plugin = tmp_path / model.model_plugin_identity.member
    plugin.write_text("approved implementation", encoding="utf-8")
    plugin_sha = hashlib.sha256(plugin.read_bytes()).hexdigest()
    identity = model.model_plugin_identity.model_copy(update={"content_sha256": plugin_sha})
    declared = RunModelPluginBinding(
        roots=(str(tmp_path),),
        required_model_types=(identity.model_type,),
        plugins=(
            ResolvedModelPlugin(
                configured_ref=identity.configured_ref,
                member=identity.member,
                model_type=identity.model_type,
                content_sha256=identity.content_sha256,
                absolute_path=str(plugin),
            ),
        ),
    )
    resolver = RunBoundHistoricalModelPluginResolver(
        declared_plugins=declared,
        generated_plugin_dir=tmp_path / "generated",
    )
    assert resolver.resolve_model_plugin(identity) == plugin
    with pytest.raises(ValueError, match="not in the run-approved"):
        resolver.resolve_model_plugin(identity.model_copy(update={"configured_ref": "unapproved"}))
    plugin.write_text("tampered implementation", encoding="utf-8")
    with pytest.raises(ValueError, match="content identity changed"):
        resolver.resolve_model_plugin(identity)

    exporter = RunBoundHistoricalArtifactExporter({model.model_config_ref.sha256: tmp_path})
    destination = tmp_path / "exported-config.json"
    exporter.export_artifact(model.model_config_ref, destination)
    assert destination.read_text(encoding="utf-8") == request.model_config_json
    with pytest.raises(ValueError, match="not declared"):
        exporter.export_artifact(model.checkpoint.ref, tmp_path / "unapproved.pt")
    (tmp_path / model.model_config_ref.logical_ref).write_text("tampered", encoding="utf-8")
    refused_destination = tmp_path / "refused-config.json"
    with pytest.raises(ValueError, match="digest mismatch"):
        exporter.export_artifact(model.model_config_ref, refused_destination)
    assert not refused_destination.exists()


def test_production_analysis_stage_receives_prior_model_assets_and_inference_capability(
    tmp_path: Path, monkeypatch
) -> None:
    """The typed workflow edge, not Data Analysis internals, owns historical assets."""

    _request, binding, source, _deriver = _setup(tmp_path)
    template = _input(tmp_path)
    policy = AnalysisAccessPolicy(
        policy_id="synthetic-model-aware",
        policy_version=1,
        purpose="Bounded validation inference",
        allow_model_inference=True,
        split_rules=(
            SplitAccessRule(
                split_id="validation",
                data_visible=True,
                predictions_visible=True,
            ),
        ),
    )
    binding = replace(binding, access_policy=policy)
    interpretation = InterpretationOutput(
        model_types=[],
        model_descriptions={},
        total_experiments=0,
        cold_start=False,
        analysis_brief=template.analysis_brief,
        key_findings=[],
        bottlenecks=[],
        take_home_message="A certified prior model exists.",
    )
    seen = {}

    class CapturingAgent:
        def __init__(self, **kwargs):
            seen["inference_capability"] = kwargs["historical_model_inference_capability"]

        def run(self, analysis_input):
            seen["assets"] = analysis_input.available_assets
            report = DataAnalysisReport(
                report_id="historical-edge-test",
                analysis_attempt_id="attempt-1",
                input_digest="0" * 64,
                plan_ref=CertifiedArtifactRef(
                    logical_ref="plan.json",
                    sha256="1" * 64,
                    media_type="application/json",
                ),
                analysis_scope=(binding.available_assets[0].authorized_scope,),
                executive_summary="No analysis executed in this edge-reachability test.",
                question_outcomes=(
                    QuestionOutcome(
                        question_id="q-test",
                        status="unresolved",
                        summary="Inference execution belongs to the agent's separate test.",
                    ),
                ),
                assets_inspected=(),
                findings=(),
                skill_result_summaries=(),
                skill_result_refs=(),
                resource_usage=AnalysisResourceSummary(
                    attempted_invocations=0,
                    completed_invocations=0,
                    total_wall_time_s=0,
                ),
                provenance=DataAnalysisReportProvenance(
                    input_digest="0" * 64,
                    access_policy_digest="2" * 64,
                    plan_digest="1" * 64,
                    discovery_snapshot_digest="3" * 64,
                    skill_result_set_digest="4" * 64,
                    generated_at="2026-09-16T00:00:00Z",
                ),
            )
            assert analysis_input.storage.local is not None
            path = (
                Path(analysis_input.storage.local.workspace)
                / "data_analysis"
                / analysis_input.storage.local.run_name
                / analysis_input.request_id
                / "report.json"
            )
            path.parent.mkdir(parents=True)
            path.write_bytes(canonical_json_bytes(report))
            return report

    monkeypatch.setattr("workflows.data_analysis_stage.DataAnalysisAgent", CapturingAgent)
    output = run_optional_data_analysis(
        interpretation,
        binding=binding,
        iteration=2,
        run_name="synthetic-run",
        storage=template.storage.model_copy(
            update={
                "local": template.storage.local.model_copy(update={"run_name": "synthetic-run"})
            }
        ),
        human_advice=None,
        llm_kwargs={},
        bridge_factory=None,
        historical_sources=(source,),
        task_composition_fingerprint="3" * 64,
        chain_workspace=str(tmp_path),
    )
    assert output is not None
    assert (
        output.report_ref.sha256
        == hashlib.sha256((tmp_path / output.report_ref.logical_ref).read_bytes()).hexdigest()
    )
    assert len(seen["assets"]) == 3
    assert isinstance(seen["inference_capability"], LocalPytorchHistoricalModelInferenceCapability)
