"""Immutable descriptive artifacts for reconstructing approved model inference."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from agent.schemas.model_io_contract import ModelIOContract
from agent.schemas.task_config import ForwardContract
from ml_models.models_format_sandbox import LossTypeName

from .common import CertifiedArtifactRef, FrozenModel, NonEmptyStr, Sha256, canonical_sha256
from .resources import ResourceUsage


class CheckpointArtifact(FrozenModel):
    ref: CertifiedArtifactRef
    format_id: Literal["siderius.pytorch-state-dict.v1"] = "siderius.pytorch-state-dict.v1"
    weights_only: Literal[True] = True
    strict_load: Literal[True] = True


class ModelPluginIdentity(FrozenModel):
    """Host-independent projection of the existing resolved plugin authority."""

    configured_ref: NonEmptyStr
    member: NonEmptyStr
    model_type: NonEmptyStr
    content_sha256: Sha256
    local_code_identity_sha256: Sha256 | None = None


class ModelConstructionContract(FrozenModel):
    """Minimal non-model-config inputs to the approved v1 constructor."""

    protocol_id: Literal["siderius.registered-model-construction.v1"] = (
        "siderius.registered-model-construction.v1"
    )
    loss_type: LossTypeName
    implementation_sha256: Sha256
    target_standardization_implementation_sha256: Sha256 | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class TaskInferenceBindingIdentity(FrozenModel):
    task_data_path_id: NonEmptyStr
    task_data_path_content_sha256: Sha256
    dataset_profile_sha256: Sha256
    task_composition_fingerprint: Sha256


class TrainingScopeProvenance(FrozenModel):
    split_id: NonEmptyStr
    scope_id: NonEmptyStr
    scope_sha256: Sha256
    scope_ref: CertifiedArtifactRef | None = None


class ModelEnvironmentIdentity(FrozenModel):
    python_version: NonEmptyStr
    siderius_revision: NonEmptyStr
    dependency_lock_ref: CertifiedArtifactRef | None = None


class ModelTrainingRunIdentity(FrozenModel):
    run_name: NonEmptyStr
    iteration_id: NonEmptyStr
    candidate_id: str | None = None
    experiment_id: NonEmptyStr


class ModelInferenceResourceHint(FrozenModel):
    preferred_device: Literal["cpu", "gpu", "either"] = "either"
    observed_batch_size: int | None = Field(default=None, gt=0)
    observed_usage: ResourceUsage | None = None


class TrainedModelArtifactProvenance(FrozenModel):
    produced_at: NonEmptyStr
    producer: NonEmptyStr
    host_details: dict[str, str] = Field(default_factory=dict)


def _executable_model_identity(
    *,
    checkpoint: CheckpointArtifact,
    model_config_ref: CertifiedArtifactRef,
    model_plugin_identity: ModelPluginIdentity,
    model_construction_contract: ModelConstructionContract,
    model_io_contract: ModelIOContract,
    forward_contract: ForwardContract,
    task_inference_binding: TaskInferenceBindingIdentity,
    inference_protocol_id: str,
    environment_identity: ModelEnvironmentIdentity,
) -> dict[str, object]:
    return {
        "checkpoint": checkpoint.model_dump(mode="json"),
        "model_config_ref": model_config_ref.model_dump(mode="json"),
        "model_plugin_identity": model_plugin_identity.model_dump(mode="json"),
        "model_construction_contract": model_construction_contract.model_dump(mode="json"),
        "model_io_contract": model_io_contract.model_dump(mode="json"),
        "forward_contract": forward_contract.model_dump(mode="json"),
        "task_inference_binding": task_inference_binding.model_dump(mode="json"),
        "inference_protocol_id": inference_protocol_id,
        "environment_identity": environment_identity.model_dump(mode="json"),
    }


class TrainedModelArtifact(FrozenModel):
    """Describes an immutable trained model without carrying executable authority."""

    schema_version: Literal[1] = 1
    model_artifact_id: NonEmptyStr
    executable_model_identity_sha256: Sha256
    checkpoint: CheckpointArtifact
    model_config_ref: CertifiedArtifactRef
    model_plugin_identity: ModelPluginIdentity
    model_construction_contract: ModelConstructionContract
    model_io_contract: ModelIOContract
    forward_contract: ForwardContract
    task_inference_binding: TaskInferenceBindingIdentity
    training_scope: TrainingScopeProvenance
    training_run: ModelTrainingRunIdentity
    inference_protocol_id: Literal["siderius.model-inference.v1"] = "siderius.model-inference.v1"
    environment_identity: ModelEnvironmentIdentity
    resource_hint: ModelInferenceResourceHint | None = None
    provenance: TrainedModelArtifactProvenance

    @staticmethod
    def compute_executable_identity_sha256(
        *,
        checkpoint: CheckpointArtifact,
        model_config_ref: CertifiedArtifactRef,
        model_plugin_identity: ModelPluginIdentity,
        model_construction_contract: ModelConstructionContract,
        model_io_contract: ModelIOContract,
        forward_contract: ForwardContract,
        task_inference_binding: TaskInferenceBindingIdentity,
        inference_protocol_id: str = "siderius.model-inference.v1",
        environment_identity: ModelEnvironmentIdentity,
    ) -> str:
        return canonical_sha256(
            _executable_model_identity(
                checkpoint=checkpoint,
                model_config_ref=model_config_ref,
                model_plugin_identity=model_plugin_identity,
                model_construction_contract=model_construction_contract,
                model_io_contract=model_io_contract,
                forward_contract=forward_contract,
                task_inference_binding=task_inference_binding,
                inference_protocol_id=inference_protocol_id,
                environment_identity=environment_identity,
            )
        )

    def executable_identity(self) -> dict[str, object]:
        return _executable_model_identity(
            checkpoint=self.checkpoint,
            model_config_ref=self.model_config_ref,
            model_plugin_identity=self.model_plugin_identity,
            model_construction_contract=self.model_construction_contract,
            model_io_contract=self.model_io_contract,
            forward_contract=self.forward_contract,
            task_inference_binding=self.task_inference_binding,
            inference_protocol_id=self.inference_protocol_id,
            environment_identity=self.environment_identity,
        )

    @model_validator(mode="after")
    def validate_artifact(self) -> TrainedModelArtifact:
        if self.model_io_contract.inference is None:
            raise ValueError("historical model artifacts require ModelIOContract.inference")
        expected = self.compute_executable_identity_sha256(
            checkpoint=self.checkpoint,
            model_config_ref=self.model_config_ref,
            model_plugin_identity=self.model_plugin_identity,
            model_construction_contract=self.model_construction_contract,
            model_io_contract=self.model_io_contract,
            forward_contract=self.forward_contract,
            task_inference_binding=self.task_inference_binding,
            inference_protocol_id=self.inference_protocol_id,
            environment_identity=self.environment_identity,
        )
        if expected != self.executable_model_identity_sha256:
            raise ValueError("executable model identity digest does not match its determinants")
        return self


class TrainedModelArtifactRef(FrozenModel):
    artifact_ref: CertifiedArtifactRef
    model_artifact_id: NonEmptyStr
    executable_model_identity_sha256: Sha256


class ModelInferenceReceipt(FrozenModel):
    """Executor-certified identity, isolation, count and resource receipt."""

    schema_version: Literal[1] = 1
    inference_id: NonEmptyStr
    request_sha256: Sha256
    model_artifact_ref: TrainedModelArtifactRef
    checkpoint_sha256: Sha256
    model_config_sha256: Sha256
    model_plugin_sha256: Sha256
    construction_protocol_id: NonEmptyStr
    construction_implementation_sha256: Sha256
    construction_loss_type: LossTypeName
    inference_protocol_id: NonEmptyStr
    input_materialization_ids: tuple[NonEmptyStr, ...]
    input_materialization_sha256s: tuple[Sha256, ...]
    split_id: NonEmptyStr
    scope_sha256: Sha256
    selection_sha256: Sha256
    prediction_count: int = Field(ge=0)
    prediction_artifact_ref: CertifiedArtifactRef | None = None
    prediction_output_format: NonEmptyStr
    prediction_semantic_id: NonEmptyStr
    target_exposed_to_inference: Literal[False] = False
    determinism: Literal["deterministic", "stochastic_seeded"]
    seed: int | None = Field(default=None, ge=0)
    status: Literal["completed", "failed", "refused", "timed_out"]
    failure_code: str | None = None
    failure_message: str | None = None
    resource_usage: ResourceUsage

    @model_validator(mode="after")
    def validate_disposition(self) -> ModelInferenceReceipt:
        if len(self.input_materialization_ids) != len(self.input_materialization_sha256s):
            raise ValueError("inference input identity arrays must align")
        if len(set(self.input_materialization_ids)) != len(self.input_materialization_ids):
            raise ValueError("inference input materialization IDs must be unique")
        if self.determinism == "stochastic_seeded" and self.seed is None:
            raise ValueError("seeded stochastic inference requires a seed")
        if self.status == "completed":
            if self.prediction_artifact_ref is None or self.failure_code or self.failure_message:
                raise ValueError("completed inference requires an artifact and no failure")
        elif self.prediction_artifact_ref is not None:
            raise ValueError("non-completed inference cannot certify a prediction artifact")
        return self
