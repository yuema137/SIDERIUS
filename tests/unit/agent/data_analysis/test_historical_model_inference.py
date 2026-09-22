from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pytest
import torch
from pydantic import ValidationError

from agent.data_analysis.authorization import authorize_materialization
from agent.schemas.data_analysis.access import (
    AnalysisAccessPolicy,
    InformationRequirement,
    SplitAccessRule,
)
from agent.schemas.data_analysis.assets import (
    AnalysisAsset,
    AnalysisAuthorizationReceipt,
    ArtifactIntrinsicScope,
    AssetProvenance,
    LegacyPartitionScope,
    MaterializedAnalysisView,
    TaskDataAssetLocation,
    TaskOpaqueScopeRef,
    TrainedModelArtifactLocation,
)
from agent.schemas.data_analysis.common import (
    CertifiedArtifactRef,
    canonical_json_bytes,
    canonical_sha256,
)
from agent.schemas.data_analysis.inference import (
    HistoricalInferenceConfiguration,
    HistoricalModelInferenceRequest,
)
from agent.schemas.data_analysis.resources import (
    AnalysisResourceEnvelope,
    CertifiedSelectionIdentity,
)
from agent.schemas.data_analysis.trained_model import (
    CheckpointArtifact,
    ModelConstructionContract,
    ModelEnvironmentIdentity,
    ModelPluginIdentity,
    ModelTrainingRunIdentity,
    TaskInferenceBindingIdentity,
    TrainedModelArtifact,
    TrainedModelArtifactProvenance,
    TrainedModelArtifactRef,
    TrainingScopeProvenance,
)
from agent.schemas.model_io_contract import (
    AxisRole,
    Dimension,
    ModelInferenceContract,
    ModelInferenceInformationRequirement,
    ModelIOContract,
    TensorAxis,
    TensorContract,
)
from agent.schemas.task_config import ForwardContract
from execute_tools.analysis_materialization import (
    AnalysisAuthorizationError,
    AnalysisMaterializationRequest,
    HistoricalInferenceInputDerivationRequest,
    validate_derived_historical_inference_input_asset,
)
from execute_tools.dataset_config import DataScope, DatasetProfile
from execute_tools.historical_model_inference import (
    HistoricalInferenceInputPath,
    HistoricalInferenceRuntimeInputs,
    LocalPytorchHistoricalModelInferenceCapability,
)
from ml_models.models_format_sandbox import DtypeAdmissibility, LossTypeName
from ml_models.models_sandbox import registered_model_construction_implementation_sha256


def _ref(
    path: Path,
    *,
    logical_ref: str | None = None,
    media_type: str = "application/octet-stream",
) -> CertifiedArtifactRef:
    payload = path.read_bytes()
    return CertifiedArtifactRef(
        logical_ref=logical_ref or path.name,
        sha256=hashlib.sha256(payload).hexdigest(),
        media_type=media_type,
        byte_size=len(payload),
    )


class _ArtifactExporter:
    def __init__(self, sources: dict[str, Path]) -> None:
        self._sources = sources

    def export_artifact(self, ref: CertifiedArtifactRef, destination: Path) -> None:
        destination.write_bytes(self._sources[ref.sha256].read_bytes())


class _PluginResolver:
    def __init__(self, source: Path) -> None:
        self.source = source
        self.seen_identity = None

    def resolve_model_plugin(self, identity: ModelPluginIdentity) -> Path:
        self.seen_identity = identity
        return self.source


def _write_plugin(path: Path, *, sleep_seconds: float = 0.0) -> None:
    path.write_text(
        "\n".join(
            [
                "from typing import Literal",
                "import time",
                "import torch",
                "from torch import nn",
                "from pydantic import BaseModel",
                "class SyntheticConfig(BaseModel):",
                '    model_type: Literal["synthetic_historical"] = "synthetic_historical"',
                "    input_width: int = 2",
                "    output_width: int = 1",
                "class SyntheticModel(nn.Module):",
                "    def __init__(self, config, *, loss_type):",
                "        super().__init__()",
                '        if loss_type != "smooth_l1":',
                '            raise ValueError("wrong effective construction loss")',
                "        self.linear = nn.Linear(config.input_width, config.output_width)",
                "    def forward(self, values):",
                f"        time.sleep({sleep_seconds!r})",
                "        return self.linear(values)",
                'PLUGIN_MODEL_TYPE = "synthetic_historical"',
                'PLUGIN_OUTPUT_TYPE = "regressor"',
                "PLUGIN_CONFIG_CLASS = SyntheticConfig",
                "PLUGIN_MODEL_CLASS = SyntheticModel",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _tensor_contract(width: int) -> TensorContract:
    return TensorContract(
        axes=(
            TensorAxis(role=AxisRole.BATCH, dimension=Dimension(symbolic="B")),
            TensorAxis(dimension=Dimension(fixed=width)),
        ),
        dtype=DtypeAdmissibility(admissible=("float32",)),
    )


def _artifact(
    checkpoint_ref: CertifiedArtifactRef,
    config_ref: CertifiedArtifactRef,
    plugin_ref: CertifiedArtifactRef,
    *,
    loss_type: LossTypeName = "smooth_l1",
    construction_sha256: str | None = None,
    dataset_profile_sha256: str = "2" * 64,
    target_standardization_sha256: str | None = None,
) -> TrainedModelArtifact:
    model_io = ModelIOContract(
        input=_tensor_contract(2),
        output=_tensor_contract(1),
        inference=ModelInferenceContract(
            accepted_input_view_formats=("siderius.numeric-array.v1",),
            required_information=(ModelInferenceInformationRequirement(information_class="data"),),
            prediction_output_format="siderius.numeric-array.v1",
            prediction_semantic_id="synthetic.scalar-prediction.v1",
        ),
    )
    checkpoint = CheckpointArtifact(ref=checkpoint_ref)
    plugin_identity = ModelPluginIdentity(
        configured_ref="operator-approved-model-pack",
        member="synthetic_model.py",
        model_type="synthetic_historical",
        content_sha256=plugin_ref.sha256,
    )
    construction = ModelConstructionContract(
        loss_type=loss_type,
        implementation_sha256=(
            construction_sha256 or registered_model_construction_implementation_sha256()
        ),
        target_standardization_implementation_sha256=target_standardization_sha256,
    )
    task_binding = TaskInferenceBindingIdentity(
        task_data_path_id="synthetic-source",
        task_data_path_content_sha256="1" * 64,
        dataset_profile_sha256=dataset_profile_sha256,
        task_composition_fingerprint="3" * 64,
    )
    environment = ModelEnvironmentIdentity(
        python_version="3.12",
        siderius_revision="test-revision",
    )
    identity = TrainedModelArtifact.compute_executable_identity_sha256(
        checkpoint=checkpoint,
        model_config_ref=config_ref,
        model_plugin_identity=plugin_identity,
        model_construction_contract=construction,
        model_io_contract=model_io,
        forward_contract=ForwardContract(model_io=model_io),
        task_inference_binding=task_binding,
        environment_identity=environment,
    )
    return TrainedModelArtifact(
        model_artifact_id=f"model-{identity[:12]}",
        executable_model_identity_sha256=identity,
        checkpoint=checkpoint,
        model_config_ref=config_ref,
        model_plugin_identity=plugin_identity,
        model_construction_contract=construction,
        model_io_contract=model_io,
        forward_contract=ForwardContract(model_io=model_io),
        task_inference_binding=task_binding,
        training_scope=TrainingScopeProvenance(
            split_id="train",
            scope_id="training-scope",
            scope_sha256="4" * 64,
        ),
        training_run=ModelTrainingRunIdentity(
            run_name="synthetic-run",
            iteration_id="iteration-1",
            experiment_id="experiment-1",
        ),
        environment_identity=environment,
        provenance=TrainedModelArtifactProvenance(
            produced_at="2026-09-15T00:00:00+00:00",
            producer="synthetic-test-producer",
        ),
    )


def _derivation_fixture() -> tuple[HistoricalInferenceInputDerivationRequest, AnalysisAsset]:
    """Use distinct raw-file and semantic-profile hashes, as production does."""

    profile = DatasetProfile(
        partition_count=2,
        anchor_selection_files=(0,),
        health_peek_files=(0,),
    )
    profile_json = json.dumps(profile.to_wire(), indent=2)
    config_json = '{"model_type":"synthetic_historical","input_width":2}'

    def ref(name: str, payload: str) -> CertifiedArtifactRef:
        encoded = payload.encode("utf-8")
        return CertifiedArtifactRef(
            logical_ref=name,
            sha256=hashlib.sha256(encoded).hexdigest(),
            media_type="application/json",
            byte_size=len(encoded),
        )

    model = _artifact(
        ref("checkpoint.pt", "checkpoint"),
        ref("model-config.json", config_json),
        ref("plugin.py", "plugin"),
        dataset_profile_sha256=canonical_sha256(profile.to_wire()),
    )
    base = AnalysisAsset(
        asset_id="validation-region",
        asset_type="dataset",
        description="Caller-authorized validation region",
        location=TaskDataAssetLocation(
            task_data_path_id="synthetic-source",
            dataset_profile_sha256=hashlib.sha256(profile_json.encode("utf-8")).hexdigest(),
            logical_role="validation_features",
        ),
        provenance=AssetProvenance(producer="synthetic-task"),
        authorized_scope=LegacyPartitionScope(data_scope=DataScope(file_indices=[0])),
        split_id="validation",
    )
    request = HistoricalInferenceInputDerivationRequest(
        base_asset=base,
        model_artifact=model,
        model_config_json=config_json,
        dataset_profile_json=profile_json,
    )
    serialized_scope = '{"partitions":[0],"candidate_width":2}'
    derived = AnalysisAsset(
        asset_id="candidate-validation-features",
        asset_type="dataset",
        description="Task-certified candidate-compatible validation features",
        location=TaskDataAssetLocation(
            task_data_path_id="synthetic-source",
            dataset_profile_sha256=base.location.dataset_profile_sha256,
            logical_role="validation_model_input",
        ),
        provenance=AssetProvenance(
            producer="synthetic-task",
            source_asset_ids=(base.asset_id,),
        ),
        authorized_scope=TaskOpaqueScopeRef(
            task_data_path_id="synthetic-source",
            serialized_scope=serialized_scope,
            sha256=hashlib.sha256(serialized_scope.encode("utf-8")).hexdigest(),
        ),
        split_id="validation",
        allowed_operations=("materialize",),
    )
    return request, derived


def test_historical_input_derivation_checks_raw_and_semantic_profile_identity() -> None:
    """The source file digest and model artifact's canonical profile are not interchangeable."""

    request, derived = _derivation_fixture()
    assert validate_derived_historical_inference_input_asset(request, derived) is derived
    with pytest.raises(ValidationError, match="configuration differs"):
        HistoricalInferenceInputDerivationRequest(
            base_asset=request.base_asset,
            model_artifact=request.model_artifact,
            model_config_json='{"model_type":"different"}',
            dataset_profile_json=request.dataset_profile_json,
        )
    with pytest.raises(ValidationError, match="profile differs from base asset source"):
        HistoricalInferenceInputDerivationRequest(
            base_asset=request.base_asset,
            model_artifact=request.model_artifact,
            model_config_json=request.model_config_json,
            dataset_profile_json=request.dataset_profile_json + " ",
        )


def test_historical_input_derivation_refuses_new_generic_authority() -> None:
    """A task may change representation, but not split, data owner or operation grant."""

    request, derived = _derivation_fixture()
    for changed, reason in (
        (derived.model_copy(update={"split_id": "test"}), "authorized split"),
        (
            derived.model_copy(update={"allowed_operations": ("materialize", "infer")}),
            "may grant only materialization",
        ),
        (
            derived.model_copy(
                update={
                    "location": derived.location.model_copy(update={"task_data_path_id": "other"})
                }
            ),
            "task data authority",
        ),
    ):
        with pytest.raises(ValueError, match=reason):
            validate_derived_historical_inference_input_asset(request, changed)


def _selection() -> CertifiedSelectionIdentity:
    return CertifiedSelectionIdentity(
        selection_id="selection-validation-two",
        selection_sha256="5" * 64,
        sampling_policy_sha256="6" * 64,
        sampling_mode="fixed",
        sampling_strategy="uniform",
        sampling_seed=17,
        population_unit="examples",
        total_available=2,
        selected_count=2,
    )


def _authorization(*, binding_id: str, slot_id: str) -> AnalysisAuthorizationReceipt:
    return AnalysisAuthorizationReceipt(
        invocation_id="invocation-historical",
        binding_id=binding_id,
        slot_id=slot_id,
        request_digest="7" * 64,
        policy_digest="8" * 64,
        asset_digest="9" * 64,
        authorized_at="2026-09-15T00:00:00+00:00",
    )


def _request(
    artifact: TrainedModelArtifact,
    artifact_ref: CertifiedArtifactRef,
    input_ref: CertifiedArtifactRef,
    *,
    timeout_s: float = 60.0,
) -> HistoricalModelInferenceRequest:
    """Allow contended CI cold start; the timeout test overrides this to 50 ms."""
    selection = _selection()
    input_view = MaterializedAnalysisView(
        materialization_id="materialization-model-input",
        invocation_id="invocation-historical",
        binding_id="model-input",
        slot_id="features",
        asset_id="dataset-validation",
        split_id="validation",
        content_ref=input_ref,
        format_id="siderius.numeric-array.v1",
        population_unit="examples",
        total_available=2,
        materialized_count=2,
        certified_information=({"information_class": "data"},),
        selection_identity=selection,
        source_digests=(input_ref.sha256,),
        authorization_receipt=_authorization(binding_id="model-input", slot_id="features"),
    )
    model_ref = TrainedModelArtifactRef(
        artifact_ref=artifact_ref,
        model_artifact_id=artifact.model_artifact_id,
        executable_model_identity_sha256=artifact.executable_model_identity_sha256,
    )
    return HistoricalModelInferenceRequest(
        request_id="historical-request",
        invocation_id="invocation-historical",
        output_binding_id="prediction-output",
        output_slot_id="prediction",
        output_asset_id="trained-model",
        model_artifact=artifact,
        model_artifact_ref=model_ref,
        model_authorization_receipt=_authorization(
            binding_id="prediction-output", slot_id="prediction"
        ),
        input_views=(input_view,),
        split_id="validation",
        requested_scope=ArtifactIntrinsicScope(
            split_id="validation", description="authorized validation examples"
        ),
        selection_identity=selection,
        requested_prediction_format="siderius.numeric-array.v1",
        requested_information=({"information_class": "prediction"},),
        configuration=HistoricalInferenceConfiguration(batch_size=2, device="cpu"),
        resource_envelope=AnalysisResourceEnvelope(
            wall_time_budget_s=max(timeout_s, 0.05),
            per_skill_timeout_s=max(timeout_s, 0.05),
        ),
        deadline_monotonic_s=time.monotonic() + max(timeout_s, 0.05),
    )


def _fixture(tmp_path: Path, *, sleep_seconds: float = 0.0, standardized: bool = False):
    plugin = tmp_path / "synthetic_model.py"
    _write_plugin(plugin, sleep_seconds=sleep_seconds)
    config = tmp_path / "model_config.json"
    config.write_text(
        json.dumps({"model_type": "synthetic_historical", "input_width": 2, "output_width": 1}),
        encoding="utf-8",
    )
    checkpoint = tmp_path / "checkpoint.pt"
    torch.save(
        {
            "linear.weight": torch.tensor([[2.0, -1.0]], dtype=torch.float32),
            "linear.bias": torch.tensor([0.5], dtype=torch.float32),
        },
        checkpoint,
    )
    model_input = tmp_path / "model_input.npz"
    with model_input.open("wb") as handle:
        np.savez(
            handle,
            example_ids=np.asarray(["example-a", "example-b"]),
            information__data=np.asarray([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32),
        )
    checkpoint_ref = _ref(checkpoint)
    transform_sha = None
    if standardized:
        from ml_models.target_standardization import target_standardization_implementation_sha256

        state = torch.load(checkpoint, weights_only=True)
        state = {"base_model." + key: value for key, value in state.items()}
        state.update(
            {
                "_siderius_target_standardization_version": torch.tensor(1, dtype=torch.int64),
                "target_mean": torch.tensor(10.0, dtype=torch.float64),
                "target_scale": torch.tensor(2.0, dtype=torch.float64),
            }
        )
        torch.save(state, checkpoint)
        checkpoint_ref = _ref(checkpoint)
        transform_sha = target_standardization_implementation_sha256()
    config_ref = _ref(config)
    plugin_ref = _ref(plugin)
    input_ref = _ref(model_input, media_type="application/x-npz")
    artifact = _artifact(
        checkpoint_ref, config_ref, plugin_ref, target_standardization_sha256=transform_sha
    )
    artifact_document = tmp_path / "trained_model_artifact.json"
    artifact_document.write_bytes(canonical_json_bytes(artifact))
    artifact_ref = _ref(artifact_document)
    request = _request(artifact, artifact_ref, input_ref)
    exporter = _ArtifactExporter({checkpoint_ref.sha256: checkpoint, config_ref.sha256: config})
    resolver = _PluginResolver(plugin)
    capability = LocalPytorchHistoricalModelInferenceCapability(
        workspace=tmp_path / "capability-workspace",
        artifact_exporter=exporter,
        plugin_resolver=resolver,
    )
    runtime_inputs = HistoricalInferenceRuntimeInputs(
        paths=(HistoricalInferenceInputPath(binding_id="model-input", path=str(model_input)),)
    )
    return capability, request, runtime_inputs, resolver


def test_certified_worker_restores_original_units_without_training_dataset(tmp_path):
    capability, request, runtime_inputs, _ = _fixture(tmp_path, standardized=True)
    result = capability.run_historical_inference(request, runtime_inputs)
    assert result.receipt.status == "completed"
    exported = tmp_path / "standardized_prediction.npz"
    capability.export_historical_prediction(result.view.content_ref, exported)
    with np.load(exported, allow_pickle=False) as archive:
        np.testing.assert_allclose(archive["information__prediction"], [[11.0], [15.0]])


def test_bounded_worker_reconstructs_exact_model_and_executor_certifies_predictions(
    tmp_path: Path,
) -> None:
    """Catches bypass of the recorded loss/plugin/checkpoint and self-reported row counts."""

    capability, request, runtime_inputs, resolver = _fixture(tmp_path)

    result = capability.run_historical_inference(request, runtime_inputs)

    assert result.receipt.status == "completed"
    assert result.receipt.target_exposed_to_inference is False
    assert result.receipt.construction_loss_type == "smooth_l1"
    assert result.receipt.prediction_count == 2
    assert resolver.seen_identity == request.model_artifact.model_plugin_identity
    assert result.view is not None
    exported = tmp_path / "exported_prediction.npz"
    capability.export_historical_prediction(result.view.content_ref, exported)
    with np.load(exported, allow_pickle=False) as archive:
        np.testing.assert_allclose(
            archive["information__prediction"],
            np.asarray([[0.5], [2.5]], dtype=np.float32),
        )


def test_historical_prediction_retirement_prevents_stale_resume_reuse(tmp_path: Path) -> None:
    capability, request, runtime_inputs, _resolver = _fixture(tmp_path)
    completed = capability.run_historical_inference(request, runtime_inputs)
    assert completed.receipt.status == "completed"
    assert completed.receipt.prediction_artifact_ref is not None

    retirement = capability.apply_prediction_retention(
        completed.receipt, retain_model_outputs=False
    )

    assert retirement.status == "retired"
    assert retirement.prediction_artifact_ref == completed.receipt.prediction_artifact_ref
    prediction = (
        tmp_path / "capability-workspace" / completed.receipt.prediction_artifact_ref.logical_ref
    )
    assert not prediction.exists()
    assert prediction.parent.joinpath("receipt.json").is_file()
    replay = capability.run_historical_inference(request, runtime_inputs)
    assert replay.receipt.status == "refused"
    assert replay.receipt.failure_code == "inference_prediction_retired"


def test_explicit_historical_prediction_retention_preserves_verified_cache(tmp_path: Path) -> None:
    capability, request, runtime_inputs, _resolver = _fixture(tmp_path)
    completed = capability.run_historical_inference(request, runtime_inputs)

    retention = capability.apply_prediction_retention(completed.receipt, retain_model_outputs=True)

    assert retention.status == "retained"
    assert (
        capability.run_historical_inference(request, runtime_inputs).receipt.status == "completed"
    )


def test_exact_inference_request_reuses_verified_prediction_without_rerunning_plugin(
    tmp_path: Path,
) -> None:
    """Catches exact standalone resume colliding or rerunning approved model code."""

    capability, request, runtime_inputs, resolver = _fixture(tmp_path)
    first = capability.run_historical_inference(request, runtime_inputs)
    assert first.receipt.status == "completed"
    resolver.source.unlink()

    second = capability.run_historical_inference(request, runtime_inputs)

    assert second.receipt == first.receipt
    assert second.view == first.view


def test_constructor_inputs_and_code_identity_change_executable_model_identity(
    tmp_path: Path,
) -> None:
    """Catches resume reuse after a constructor-affecting loss or constructor code change."""

    _, request, _, _ = _fixture(tmp_path)
    original = request.model_artifact
    focal = _artifact(
        original.checkpoint.ref,
        original.model_config_ref,
        CertifiedArtifactRef(
            logical_ref="plugin.py",
            sha256=original.model_plugin_identity.content_sha256,
            media_type="text/x-python",
        ),
        loss_type="focal",
    )
    changed_code = _artifact(
        original.checkpoint.ref,
        original.model_config_ref,
        CertifiedArtifactRef(
            logical_ref="plugin.py",
            sha256=original.model_plugin_identity.content_sha256,
            media_type="text/x-python",
        ),
        construction_sha256="a" * 64,
    )
    changed_checkpoint = _artifact(
        original.checkpoint.ref.model_copy(update={"sha256": "c" * 64}),
        original.model_config_ref,
        CertifiedArtifactRef(
            logical_ref="plugin.py",
            sha256=original.model_plugin_identity.content_sha256,
            media_type="text/x-python",
        ),
    )
    changed_plugin = _artifact(
        original.checkpoint.ref,
        original.model_config_ref,
        CertifiedArtifactRef(
            logical_ref="plugin.py",
            sha256="d" * 64,
            media_type="text/x-python",
        ),
    )

    assert focal.executable_model_identity_sha256 != original.executable_model_identity_sha256
    assert changed_code.executable_model_identity_sha256 != (
        original.executable_model_identity_sha256
    )
    assert changed_checkpoint.executable_model_identity_sha256 != (
        original.executable_model_identity_sha256
    )
    assert changed_plugin.executable_model_identity_sha256 != (
        original.executable_model_identity_sha256
    )


def test_inference_identity_tracks_science_but_excludes_host_resource_observations(
    tmp_path: Path,
) -> None:
    """Catches stale resume across selection changes and false invalidation across hosts."""

    _, request, _, _ = _fixture(tmp_path)
    changed_selection = request.selection_identity.model_copy(
        update={"selection_id": "different-selection", "selection_sha256": "b" * 64}
    )
    different_science = request.model_copy(
        update={
            "selection_identity": changed_selection,
            "input_views": (
                request.input_views[0].model_copy(update={"selection_identity": changed_selection}),
            ),
        }
    )
    different_host_budget = request.model_copy(
        update={
            "resource_envelope": AnalysisResourceEnvelope(
                wall_time_budget_s=300.0,
                per_skill_timeout_s=100.0,
                max_host_memory_gb=32.0,
                preferred_device="gpu",
            ),
            "deadline_monotonic_s": request.deadline_monotonic_s + 5000.0,
        }
    )
    different_scope = request.model_copy(
        update={
            "requested_scope": ArtifactIntrinsicScope(
                split_id="validation", description="a different authorized validation scope"
            )
        }
    )

    assert different_science.scientific_identity_sha256 != request.scientific_identity_sha256
    assert different_scope.scientific_identity_sha256 != request.scientific_identity_sha256
    assert different_host_budget.scientific_identity_sha256 == request.scientific_identity_sha256


def test_target_information_cannot_enter_historical_inference_request(tmp_path: Path) -> None:
    """Catches target leakage before a predictor worker can observe model input bytes."""

    _, request, _, _ = _fixture(tmp_path)
    leaking_view = request.input_views[0].model_copy(
        update={"certified_information": (InformationRequirement(information_class="target"),)}
    )

    with pytest.raises(ValidationError, match="never contain target"):
        HistoricalModelInferenceRequest.model_validate(
            {**request.model_dump(mode="python"), "input_views": (leaking_view,)}
        )


def test_model_input_cannot_expose_metadata_outside_model_io_contract(tmp_path: Path) -> None:
    """Catches an explicitly materialized but undeclared metadata field reaching the model."""

    _, request, _, _ = _fixture(tmp_path)
    broadened_view = request.input_views[0].model_copy(
        update={
            "certified_information": (
                InformationRequirement(information_class="data"),
                InformationRequirement(information_class="metadata", fields=("source_id",)),
            )
        }
    )

    with pytest.raises(ValidationError, match="exactly match ModelIOContract information"):
        HistoricalModelInferenceRequest.model_validate(
            {**request.model_dump(mode="python"), "input_views": (broadened_view,)}
        )


def test_inference_policy_refuses_before_any_model_or_data_capability_runs(tmp_path: Path) -> None:
    """Catches active inference bypassing the explicit allow_model_inference authority."""

    _, inference_request, _, _ = _fixture(tmp_path)
    artifact = inference_request.model_artifact
    scope = ArtifactIntrinsicScope(
        split_id="validation", description="authorized validation examples"
    )
    model_asset = AnalysisAsset(
        asset_id="trained-model",
        asset_type="trained_model",
        description="Exact immutable synthetic model",
        location=TrainedModelArtifactLocation(
            artifact_ref=CertifiedArtifactRef(
                logical_ref="trained-model-artifact.json",
                sha256=canonical_sha256(artifact),
                media_type="application/json",
            ),
            artifact=artifact,
        ),
        provenance=AssetProvenance(producer="synthetic-training"),
        authorized_scope=scope,
        split_id="validation",
        allowed_operations=("infer",),
    )
    policy = AnalysisAccessPolicy(
        policy_id="prediction-visible-but-inference-disabled",
        policy_version=1,
        purpose="Prove inference has its own authorization switch",
        split_rules=(
            SplitAccessRule(
                split_id="validation",
                data_visible=True,
                predictions_visible=True,
            ),
        ),
        allow_model_inference=False,
    )
    request = AnalysisMaterializationRequest(
        request_id="refused-inference",
        invocation_id="invocation-historical",
        binding_id="prediction-output",
        slot_id="prediction",
        asset=model_asset,
        split_id="validation",
        requested_scope=scope,
        requested_information=(InformationRequirement(information_class="prediction"),),
        requested_format_id="siderius.numeric-array.v1",
        operation="infer",
        sampling_policy={"mode": "fixed", "max_items": 2},
        access_policy=policy,
    )

    with pytest.raises(AnalysisAuthorizationError) as raised:
        authorize_materialization(request, available_assets={model_asset.asset_id: model_asset})

    assert raised.value.refusal.code == "model_inference_not_allowed"
    assert raised.value.refusal.materialization_occurred is False


def test_worker_timeout_returns_typed_receipt_without_partial_prediction(tmp_path: Path) -> None:
    """Catches a timed-out process tree being mistaken for a complete prediction artifact."""

    capability, request, runtime_inputs, _ = _fixture(tmp_path, sleep_seconds=2.0)
    request = request.model_copy(
        update={
            "resource_envelope": AnalysisResourceEnvelope(
                wall_time_budget_s=0.05,
                per_skill_timeout_s=0.05,
            ),
            "deadline_monotonic_s": time.monotonic() + 0.05,
        }
    )

    result = capability.run_historical_inference(request, runtime_inputs)

    assert result.view is None
    assert result.receipt.status == "timed_out"
    assert result.receipt.failure_code == "inference_timeout"
    assert result.receipt.prediction_artifact_ref is None


def test_invalid_checkpoint_returns_typed_failure_not_partial_success(tmp_path: Path) -> None:
    """Catches reconstruction failure escaping without the Gate-D disposition receipt."""

    capability, request, runtime_inputs, _ = _fixture(tmp_path)
    checkpoint = tmp_path / "checkpoint.pt"
    torch.save({"wrong.weight": torch.ones(1)}, checkpoint)
    changed_ref = _ref(checkpoint)
    changed_artifact = _artifact(
        changed_ref,
        request.model_artifact.model_config_ref,
        CertifiedArtifactRef(
            logical_ref="plugin.py",
            sha256=request.model_artifact.model_plugin_identity.content_sha256,
            media_type="text/x-python",
        ),
    )
    changed_artifact_document = tmp_path / "changed_artifact.json"
    changed_artifact_document.write_bytes(canonical_json_bytes(changed_artifact))
    changed_request = _request(
        changed_artifact, _ref(changed_artifact_document), request.input_views[0].content_ref
    )
    exporter = _ArtifactExporter(
        {
            changed_ref.sha256: checkpoint,
            changed_artifact.model_config_ref.sha256: tmp_path / "model_config.json",
        }
    )
    capability = LocalPytorchHistoricalModelInferenceCapability(
        workspace=tmp_path / "failed-capability-workspace",
        artifact_exporter=exporter,
        plugin_resolver=_PluginResolver(tmp_path / "synthetic_model.py"),
    )

    result = capability.run_historical_inference(changed_request, runtime_inputs)

    assert result.view is None
    assert result.receipt.status == "failed"
    assert result.receipt.prediction_artifact_ref is None
    assert result.receipt.failure_code


def test_exported_model_artifact_tampering_fails_during_staging_with_typed_receipt(
    tmp_path: Path,
) -> None:
    """Catches caller storage returning bytes different from the certified model refs."""

    _, request, runtime_inputs, _ = _fixture(tmp_path)

    class TamperingExporter:
        def export_artifact(self, _ref, destination: Path) -> None:
            destination.write_bytes(b"tampered")

    capability = LocalPytorchHistoricalModelInferenceCapability(
        workspace=tmp_path / "tampered-capability-workspace",
        artifact_exporter=TamperingExporter(),
        plugin_resolver=_PluginResolver(tmp_path / "synthetic_model.py"),
    )

    result = capability.run_historical_inference(request, runtime_inputs)

    assert result.view is None
    assert result.receipt.status == "failed"
    assert result.receipt.failure_code == "inference_staging_failed"
    assert result.receipt.prediction_artifact_ref is None


def test_runtime_model_input_must_match_its_certified_materialization(tmp_path: Path) -> None:
    """Catches a caller swapping input bytes after selection/materialization certification."""

    capability, request, runtime_inputs, _ = _fixture(tmp_path)
    Path(runtime_inputs.paths[0].path).write_bytes(b"different selected examples")

    result = capability.run_historical_inference(request, runtime_inputs)

    assert result.view is None
    assert result.receipt.status == "failed"
    assert result.receipt.failure_code == "inference_input_staging_failed"
