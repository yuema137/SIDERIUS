"""Training artifact reachability and strict target isolation for analysis.

Defect caught: the historical-inference schemas and worker can all pass while
normal training records only an opaque ``.pth`` path.  This test starts the
real training subprocess, consumes its certified reconstruction sidecar through
the production record helper, persists the typed artifact ref, performs bounded
target-isolated historical inference, and grounds a report in the resulting
prediction artifact. The current raw-input/model-only analysis source policy
must refuse target-dependent planning even when ordinary evaluation may use
the target independently.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from agent.data_analysis.discovery import discover_skills
from agent.data_analysis.plan_validation import AnalysisPlanResolutionError
from agent.schemas.data_analysis.assets import (
    AnalysisAsset,
    ArtifactIntrinsicScope,
    AssetProvenance,
    MaterializedAnalysisView,
    TaskDataAssetLocation,
    TrainedModelArtifactLocation,
)
from agent.schemas.data_analysis.common import CertifiedArtifactRef, canonical_sha256
from agent.schemas.data_analysis.context import DataAnalysisInput
from agent.schemas.data_analysis.resources import CertifiedSelectionIdentity
from agent.schemas.data_analysis.trained_model import TrainedModelArtifact
from agent.schemas.hyperparam_tuning import ExperimentRecord
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from core.sandbox_executor import TidmadSandbox
from core.training_execution_bindings import TrainingExecutionBindings
from execute_tools.historical_model_inference import (
    ApprovedModelPluginResolver,
    HistoricalModelArtifactExporter,
    LocalPytorchHistoricalModelInferenceCapability,
)
from execute_tools.task_data_path import ScopeBuildRequest, resolve_task_scope_capability
from execute_tools.trained_model_artifact import copy_certified_artifact
from ml_models.loss_models_sandbox import register_loss_in_memory
from ml_models.plugin_loader import register_model_in_memory
from nodes.data_analysis_agent import DataAnalysisAgent
from nodes.ml_hyperparameter_tune_agent.checkpoint_retention import (
    CheckpointRetentionError,
    CompletedTrainingAttempt,
    finalize_attempt_checkpoint,
    finalize_run_checkpoints,
)
from nodes.ml_hyperparameter_tune_agent.contracts import TrainingOutcome
from nodes.ml_hyperparameter_tune_agent.records import _trained_model_artifact_ref
from workflows.task_composition import (
    bind_run_task_composition,
    build_task_composition_ref,
    compose_run_task_bindings,
)


class _WorkspaceExporter(HistoricalModelArtifactExporter):
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace

    def export_artifact(self, ref: CertifiedArtifactRef, destination: Path) -> None:
        copy_certified_artifact(self.workspace, ref, destination)


class _ExactPluginResolver(ApprovedModelPluginResolver):
    def __init__(self, plugin: Path) -> None:
        self.plugin = plugin

    def resolve_model_plugin(self, identity) -> Path:
        assert hashlib.sha256(self.plugin.read_bytes()).hexdigest() == identity.content_sha256
        return self.plugin


class _SyntheticRegressionAnalysisCapability:
    """Task-owned feature/target materializer; it never exposes both together."""

    def __init__(self, *, example_ids: np.ndarray, features: np.ndarray, targets: np.ndarray):
        self.example_ids = example_ids
        self.features = features
        self.targets = targets
        self.payloads: dict[str, bytes] = {}

    def materialize_analysis_view(self, authorized) -> MaterializedAnalysisView:
        request = authorized.request
        buffer = io.BytesIO()
        if request.asset.asset_id == "validation-features":
            arrays = {"information__data": self.features}
        elif request.asset.asset_id == "validation-targets":
            arrays = {"information__target": self.targets}
        else:  # The model output is owned by HistoricalModelInferenceCapability.
            raise AssertionError(f"unexpected ordinary materialization: {request.asset.asset_id}")
        np.savez(buffer, example_ids=self.example_ids, **arrays)
        payload = buffer.getvalue()
        digest = hashlib.sha256(payload).hexdigest()
        logical_ref = f"opaque://model-reachability/{request.binding_id}/{digest}"
        self.payloads[logical_ref] = payload
        selection = CertifiedSelectionIdentity(
            selection_id="validation-all-rows",
            selection_sha256=hashlib.sha256(b"\n".join(self.example_ids.tolist())).hexdigest(),
            sampling_policy_sha256=canonical_sha256(request.sampling_policy),
            sampling_mode=request.sampling_policy.mode,
            sampling_strategy=request.sampling_policy.strategy,
            sampling_seed=request.sampling_policy.seed,
            population_unit="examples",
            total_available=len(self.example_ids),
            selected_count=len(self.example_ids),
        )
        return MaterializedAnalysisView(
            materialization_id=f"materialized-{request.binding_id}",
            invocation_id=request.invocation_id,
            binding_id=request.binding_id,
            slot_id=request.slot_id,
            asset_id=request.asset.asset_id,
            split_id=request.split_id,
            content_ref=CertifiedArtifactRef(
                logical_ref=logical_ref,
                sha256=digest,
                media_type="application/x-npz",
                byte_size=len(payload),
            ),
            format_id=request.requested_format_id,
            population_unit="examples",
            total_available=len(self.example_ids),
            materialized_count=len(self.example_ids),
            certified_information=request.requested_information,
            selection_identity=selection,
            task_data_path_id="synthetic_masked_regression",
            source_digests=(digest,),
            authorization_receipt=authorized.authorization_receipt,
        )

    def export_analysis_materialization(self, content_ref, destination: Path) -> None:
        destination.write_bytes(self.payloads[content_ref.logical_ref])


class _ModelDiagnosticBridge:
    def __init__(self, *, analysis_input: DataAnalysisInput, **_kwargs) -> None:
        self.inp = analysis_input
        self.discovery_snapshot_digest = discover_skills(
            analysis_input.allowed_skill_packs
        ).snapshot_digest

    def generate(self, _system, user, *, label):
        if label == "data_analysis.skill_selection":
            assert "prediction_target_distribution" in user
            return {
                "skill_ids": ["prediction_target_distribution"],
                "rationale": "Use the generic prediction/target diagnostic.",
            }
        if label == "data_analysis.plan":
            return {
                "plan_id": "model-diagnostic-plan",
                "input_digest": canonical_sha256(self.inp),
                "access_policy_digest": canonical_sha256(self.inp.access_policy),
                "discovery_snapshot_digest": self.discovery_snapshot_digest,
                "questions": ["q-model"],
                "invocations": [
                    {
                        "invocation_id": "prediction-diagnostic",
                        "skill_id": "prediction_target_distribution",
                        "question_ids": ["q-model"],
                        "bindings": [
                            {
                                "binding_id": "historical-predictions",
                                "slot_id": "predictions",
                                "asset_id": "trained-model",
                                "operation": "infer",
                                "requested_format_id": "siderius.numeric-array.v1",
                                "requested_information": [{"information_class": "prediction"}],
                                "inference_inputs": [
                                    {
                                        "binding_id": "inference-features",
                                        "asset_id": "validation-features",
                                        "requested_format_id": "siderius.numeric-array.v1",
                                        "requested_information": [{"information_class": "data"}],
                                    }
                                ],
                                "inference_configuration": {
                                    "batch_size": 8,
                                    "device": "cpu",
                                },
                            },
                            {
                                "binding_id": "validation-targets",
                                "slot_id": "targets",
                                "asset_id": "validation-targets",
                                "operation": "materialize",
                                "requested_format_id": "siderius.numeric-array.v1",
                                "requested_information": [{"information_class": "target"}],
                            },
                        ],
                        "sampling_plan": {
                            "split_id": "validation",
                            "requested_scope": self.inp.available_assets[
                                0
                            ].authorized_scope.model_dump(mode="json"),
                            "policy": {
                                "mode": "full_if_feasible",
                                "strategy": "uniform",
                                "seed": 31,
                            },
                        },
                        "arguments": {},
                        "expected_time_cost": "cheap",
                        "expected_memory_cost": "low",
                        "priority": 5,
                    }
                ],
                "stop_policy": {"max_invocations": 1, "minimum_remaining_time_s": 0.05},
                "rationale": "Infer on explicit features, then compare predictions and targets.",
            }
        if label == "data_analysis.synthesis":
            results = json.loads(
                user.split("Certified bounded SkillResults:\n", 1)[1].split(
                    "\n\nAuthoritative output JSON schema:", 1
                )[0]
            )
            result = results[0]
            assert result["status"] == "completed"
            bias = next(
                item for item in result["quantitative_results"] if item["result_key"] == "bias"
            )
            return {
                "executive_summary": "Historical predictions were compared with authorized targets.",
                "findings": [
                    {
                        "finding_id": "finding-prediction-bias",
                        "result_id": result["result_id"],
                        "statement": f"Mean prediction minus target was {bias['value']}.",
                        "quantitative_result_ids": ["bias"],
                        "confidence_level": "high",
                        "confidence_rationale": "The result uses certified aligned predictions.",
                        "modeling_relevance": "The observed bias characterizes this historical model.",
                    }
                ],
                "question_outcomes": [
                    {
                        "question_id": "q-model",
                        "status": "addressed",
                        "summary": "Certified predictions and targets were compared.",
                        "finding_ids": ["finding-prediction-bias"],
                    }
                ],
                "modeling_relevance": ["Use the measured bias as downstream evidence."],
            }
        raise AssertionError(label)


@pytest.mark.allow_real_subprocess
def test_two_real_training_iterations_retire_originals_and_keep_records(tmp_path: Path) -> None:
    """Iteration two can train after iteration one's Trial and failed originals retire."""

    checkout = Path(__file__).resolve().parents[4]
    manifest = checkout / "configs/task_composition/synthetic_masked_regression.yaml"
    model_plugin = checkout / "examples/synthetic_masked_regression/plugins/masked_reference_mlp.py"
    loss_plugin = checkout / "examples/synthetic_masked_regression/plugins/masked_mse_loss.py"
    register_model_in_memory(str(model_plugin))
    register_loss_in_memory(str(loss_plugin))
    composition = compose_run_task_bindings(str(manifest))
    composition_ref = build_task_composition_ref(composition)
    assert composition_ref is not None
    task = composition.task_data_path
    bundle = sys.modules[type(task).__module__].materialize_run_bundle(tmp_path / "synthetic-data")
    scope_capability = resolve_task_scope_capability(task)
    scope_request = ScopeBuildRequest(
        round_kind="trial", selection_strategy="snapshot", portion=1.0
    )
    scopes = SimpleNamespace(
        training=scope_capability.build_training_scope(scope_request),
        evaluation=scope_capability.build_eval_scope(scope_request),
    )
    certified_blobs: list[Path] = []

    for iteration in (1, 2):
        workspace = tmp_path / f"iter_{iteration:03d}"
        run_name = f"iter_{iteration:03d}"
        with bind_run_task_composition(composition, physical_data_root=bundle["data_dir"]):
            sandbox = TidmadSandbox(
                workspace=str(workspace), run_name=run_name, file_index=0, progress_bar=False
            )
            trained = sandbox.execute_training(
                "trial",
                run_name,
                "masked_reference_mlp",
                {"model_type": "masked_reference_mlp", "segmentation_size": 3, "hidden_dim": 8},
                {
                    "lr": 1e-3,
                    "epochs": 1,
                    "batch_size": 48,
                    "optimizer_type": "adam",
                    "device": "cpu",
                },
                {"loss_type": "custom", "loss_name": "synthetic_masked_mse"},
                train_base_seed=17 + iteration,
                execution_bindings=TrainingExecutionBindings(task_scopes=scopes),
            )
            assert trained["status"] == "success"
            ref = _trained_model_artifact_ref(
                SimpleNamespace(
                    run_model_io=composition.forward_contract.model_io,
                    agent_input=SimpleNamespace(
                        task_composition_ref=composition_ref,
                        candidate_id=f"candidate-{iteration}",
                    ),
                    run_task_data_path=task,
                    run_forward_contract=composition.forward_contract,
                    workspace=str(workspace),
                    run_name=run_name,
                    run_profile=composition.dataset_profile,
                ),
                SimpleNamespace(exp_id="trial"),
                TrainingOutcome(train_status=trained),
            )
            assert ref is not None
            sandbox.save_record(
                ExperimentRecord(
                    exp_id="trial",
                    status="success",
                    model_type="masked_reference_mlp",
                    timestamp="2026-09-17T00:00:00+00:00",
                    file_index=0,
                    params={"model_config": {"model_type": "masked_reference_mlp"}},
                    trained_model_artifact_ref=ref,
                ).model_dump(mode="json")
            )
            sandbox.save_record(
                ExperimentRecord(
                    exp_id="failed",
                    status="error_training",
                    model_type="masked_reference_mlp",
                    timestamp="2026-09-17T00:00:00+00:00",
                    file_index=0,
                    params={},
                ).model_dump(mode="json")
            )

        original = Path(trained["trained_model_candidate"]["checkpoint_path"])
        failed_original = (
            Path(sandbox.dirs["models"]) / "model_masked_reference_mlp_failed_agent.pth"
        )
        failed_original.write_bytes(b"interrupted training checkpoint")
        certified_blob = (
            workspace
            / "trained_model_artifacts"
            / "blobs"
            / f"{trained['trained_model_candidate']['checkpoint_sha256']}.pt"
        )
        assert original.is_file() and failed_original.is_file() and certified_blob.is_file()
        assert len(sandbox.get_summary()) == 2
        attempts = [
            CompletedTrainingAttempt(
                workspace=str(workspace),
                run_name=run_name,
                exp_id=exp_id,
                model_type="masked_reference_mlp",
                is_trial=True,
                scored=exp_id == "trial",
                certified_ref=ref.model_dump(mode="json") if exp_id == "trial" else None,
            )
            for exp_id in ("trial", "failed")
        ]
        receipts = finalize_run_checkpoints(
            attempts,
            retain_training_checkpoints=False,
            recorded_exp_ids={record["exp_id"] for record in sandbox.get_summary()},
        )
        assert [receipt.status for receipt in receipts] == ["retired", "retired"]
        assert not original.exists() and not failed_original.exists()
        assert certified_blob.is_file() and len(sandbox.get_summary()) == 2
        certified_blobs.append(certified_blob)

    assert all(blob.is_file() for blob in certified_blobs)


@pytest.mark.allow_real_subprocess
def test_new_training_record_refuses_target_dependent_analysis(tmp_path: Path) -> None:
    """A completed model never turns separately scored truth into an analysis source."""

    checkout = Path(__file__).resolve().parents[4]
    manifest = checkout / "configs/task_composition/synthetic_masked_regression.yaml"
    model_plugin = checkout / "examples/synthetic_masked_regression/plugins/masked_reference_mlp.py"
    loss_plugin = checkout / "examples/synthetic_masked_regression/plugins/masked_mse_loss.py"
    register_model_in_memory(str(model_plugin))
    register_loss_in_memory(str(loss_plugin))
    composition = compose_run_task_bindings(str(manifest))
    composition_ref = build_task_composition_ref(composition)
    assert composition_ref is not None
    task = composition.task_data_path
    task_module = sys.modules[type(task).__module__]
    bundle = task_module.materialize_run_bundle(tmp_path / "synthetic-data")
    scope_capability = resolve_task_scope_capability(task)
    scope_request = ScopeBuildRequest(
        round_kind="formal", selection_strategy="snapshot", portion=1.0
    )
    scopes = SimpleNamespace(
        training=scope_capability.build_training_scope(scope_request),
        evaluation=scope_capability.build_eval_scope(scope_request),
    )

    with bind_run_task_composition(composition, physical_data_root=bundle["data_dir"]):
        sandbox = TidmadSandbox(
            workspace=str(tmp_path), run_name="reachability", file_index=0, progress_bar=False
        )
        trained = sandbox.execute_training(
            "tiny",
            "reachability",
            "masked_reference_mlp",
            {"model_type": "masked_reference_mlp", "segmentation_size": 3, "hidden_dim": 8},
            {
                "lr": 1e-3,
                "epochs": 1,
                "batch_size": 48,
                "optimizer_type": "adam",
                "device": "cpu",
            },
            {"loss_type": "custom", "loss_name": "synthetic_masked_mse"},
            train_base_seed=17,
            execution_bindings=TrainingExecutionBindings(task_scopes=scopes),
        )
        assert trained["status"] == "success"
        assert trained["trained_model_candidate"] is not None
        ref = _trained_model_artifact_ref(
            SimpleNamespace(
                run_model_io=composition.forward_contract.model_io,
                agent_input=SimpleNamespace(
                    task_composition_ref=composition_ref, candidate_id="candidate-tiny"
                ),
                run_task_data_path=task,
                run_forward_contract=composition.forward_contract,
                workspace=str(tmp_path),
                run_name="reachability",
                run_profile=composition.dataset_profile,
            ),
            SimpleNamespace(exp_id="tiny"),
            TrainingOutcome(train_status=trained),
        )
        assert ref is not None
        record = ExperimentRecord(
            exp_id="tiny",
            status="success",
            model_type="masked_reference_mlp",
            timestamp="2026-09-15T00:00:00+00:00",
            file_index=0,
            params={"model_config": {"model_type": "masked_reference_mlp"}},
            trained_model_artifact_ref=ref,
        )
        sandbox.save_record(record.model_dump(mode="json"))
        restored = ExperimentRecord.model_validate(sandbox.get_summary()[0])
        assert restored.trained_model_artifact_ref == ref

    original = Path(trained["trained_model_candidate"]["checkpoint_path"])
    certified_blob = (
        tmp_path
        / "trained_model_artifacts"
        / "blobs"
        / (trained["trained_model_candidate"]["checkpoint_sha256"] + ".pt")
    )
    certified_bytes = certified_blob.read_bytes()
    certified_blob.write_bytes(b"corrupt")
    with pytest.raises(CheckpointRetentionError, match="artifact file differs"):
        finalize_attempt_checkpoint(
            workspace=str(tmp_path),
            models_dir=sandbox.dirs["models"],
            run_name="reachability",
            exp_id="tiny",
            model_type="masked_reference_mlp",
            is_trial=False,
            retain_training_checkpoints=False,
            scored=True,
            certified_ref=ref.model_dump(mode="json"),
        )
    assert original.is_file()
    assert (
        '"status":"failed"'
        in (tmp_path / "training_checkpoint_retention_receipts.jsonl").read_text()
    )
    certified_blob.write_bytes(certified_bytes)
    receipt = finalize_attempt_checkpoint(
        workspace=str(tmp_path),
        models_dir=sandbox.dirs["models"],
        run_name="reachability",
        exp_id="tiny",
        model_type="masked_reference_mlp",
        is_trial=False,
        retain_training_checkpoints=False,
        scored=True,
        certified_ref=ref.model_dump(mode="json"),
    )
    assert receipt.status == "retired"
    assert not original.exists()
    assert certified_blob.read_bytes() == certified_bytes

    artifact_path = tmp_path / ref.artifact_ref.logical_ref
    artifact = TrainedModelArtifact.model_validate_json(artifact_path.read_bytes())
    assert artifact.checkpoint.ref.sha256 == trained["trained_model_candidate"]["checkpoint_sha256"]
    assert artifact.model_construction_contract.loss_type == "custom"
    assert artifact.task_inference_binding.task_composition_fingerprint == (
        composition.semantic_fingerprint
    )

    evaluation_dataset = task.validation_dataset(
        scopes.evaluation, SimpleNamespace(data_dir=bundle["data_dir"])
    )
    features = np.stack([row[0].numpy() for row in evaluation_dataset])
    targets = np.asarray([float(row[1][0]) for row in evaluation_dataset], dtype=np.float32)
    example_ids = np.asarray([row.sample_id.encode() for row in scopes.evaluation.rows])
    analysis_capability = _SyntheticRegressionAnalysisCapability(
        example_ids=example_ids, features=features, targets=targets
    )
    scope = ArtifactIntrinsicScope(
        split_id="validation", description="All synthetic validation rows"
    )
    task_location = TaskDataAssetLocation(
        task_data_path_id="synthetic_masked_regression",
        dataset_profile_sha256=canonical_sha256(composition.dataset_profile.to_wire()),
        logical_role="validation",
    )
    assets = (
        AnalysisAsset(
            asset_id="trained-model",
            asset_type="trained_model",
            description="Newly trained immutable synthetic scalar regressor.",
            location=TrainedModelArtifactLocation(artifact_ref=ref.artifact_ref, artifact=artifact),
            provenance=AssetProvenance(producer="training", run_id="reachability"),
            authorized_scope=scope,
            split_id="validation",
            allowed_operations=("infer",),
        ),
        AnalysisAsset(
            asset_id="validation-features",
            asset_type="dataset",
            description="Authorized validation features for historical inference.",
            location=task_location,
            provenance=AssetProvenance(producer="synthetic-task"),
            authorized_scope=scope,
            split_id="validation",
        ),
        AnalysisAsset(
            asset_id="validation-targets",
            asset_type="dataset",
            description="Separately authorized validation targets for diagnosis.",
            location=task_location,
            provenance=AssetProvenance(producer="synthetic-task"),
            authorized_scope=scope,
            split_id="validation",
        ),
    )
    from agent.data_analysis.reference_packs import builtin_pack_refs

    analysis_input = DataAnalysisInput(
        request_id="training-model-analysis-reachability",
        task_context={
            "task_id": "synthetic-regression",
            "scientific_goal": "Characterize a newly trained model's predictions.",
            "task_description": "Tiny deterministic synthetic scalar regression.",
            "target_description": "One continuous scalar.",
            "input_description": "Three continuous synthetic features.",
            "metric_summary": "Lower masked mean squared error is better.",
            "forward_contract": composition.forward_contract,
        },
        analysis_brief={
            "brief_id": "model-diagnostic-brief",
            "questions": [
                {
                    "question_id": "q-model",
                    "question": "Do the historical predictions show bias or range compression?",
                }
            ],
            "source": "orchestrator",
            "source_ref": "campaign-readiness",
        },
        available_assets=assets,
        declared_scope={
            "raw_input_asset_ids": ["validation-features"],
            "historical_model_asset_ids": ["trained-model"],
        },
        access_policy={
            "policy_id": "model-diagnostic-policy",
            "policy_version": 1,
            "purpose": "Target-isolated historical model diagnosis",
            "split_rules": [
                {
                    "split_id": "validation",
                    "data_visible": True,
                    "targets_visible": True,
                    "predictions_visible": True,
                }
            ],
            "allow_model_inference": True,
        },
        resource_envelope={
            "wall_time_budget_s": 30,
            "per_skill_timeout_s": 10,
            "preferred_device": "cpu",
        },
        allowed_skill_packs=builtin_pack_refs("core-analysis"),
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="reachability"),
        ),
        caller={"caller_id": "campaign-readiness", "caller_type": "orchestrator"},
    )
    inference = LocalPytorchHistoricalModelInferenceCapability(
        workspace=tmp_path,
        artifact_exporter=_WorkspaceExporter(tmp_path),
        plugin_resolver=_ExactPluginResolver(model_plugin),
    )
    with pytest.raises(AnalysisPlanResolutionError, match="analysis scope"):
        DataAnalysisAgent(
            task_analysis_capability=analysis_capability,
            bridge_factory=lambda **kwargs: _ModelDiagnosticBridge(
                analysis_input=analysis_input, **kwargs
            ),
            provider="test",
            model_id="controlled",
            historical_model_inference_capability=inference,
        ).run(analysis_input)
    assert not list(tmp_path.rglob("inference_receipts.jsonl"))
