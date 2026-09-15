"""Certification and persistence for newly trained historical-inference models.

The training subprocess reports the exact files and implementation it used.
This module turns that executor evidence plus already-bound task authorities
into an immutable :class:`TrainedModelArtifact`.  It never discovers legacy
checkpoints by filename and never puts an executable path in the artifact.
"""

from __future__ import annotations

import hashlib
import platform
import shutil
from pathlib import Path

from pydantic import Field, model_validator

from agent.schemas.data_analysis.common import (
    CertifiedArtifactRef,
    FrozenModel,
    NonEmptyStr,
    Sha256,
    canonical_json_bytes,
    canonical_sha256,
    utc_now,
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
from agent.schemas.model_io_contract import ModelIOContract
from agent.schemas.task_config import ForwardContract
from core.durable_io import publish_bytes_write_once
from core.runtime_control.gpu_milestone_trace import resolve_git_sha
from ml_models.models_format_sandbox import LossTypeName
from ml_models.models_sandbox import registered_model_construction_implementation_sha256


class TrainingArtifactCandidate(FrozenModel):
    """Executor-observed reconstruction inputs for one completed training run."""

    checkpoint_path: NonEmptyStr
    checkpoint_sha256: Sha256
    checkpoint_byte_size: int = Field(ge=0)
    model_config_path: NonEmptyStr
    model_config_sha256: Sha256
    model_config_byte_size: int = Field(ge=0)
    model_plugin_path: NonEmptyStr
    model_plugin_sha256: Sha256
    model_plugin_member: NonEmptyStr
    model_type: NonEmptyStr
    effective_loss_type: LossTypeName
    training_scope_path: str | None = None
    training_scope_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def validate_scope_pair(self) -> TrainingArtifactCandidate:
        if (self.training_scope_path is None) != (self.training_scope_sha256 is None):
            raise ValueError("training scope path and digest must be supplied together")
        return self


class TrainedModelEmissionContext(FrozenModel):
    """Already-resolved training authorities; no field is rediscovered here."""

    workspace: NonEmptyStr
    run_name: NonEmptyStr
    iteration_id: NonEmptyStr
    candidate_id: str | None = None
    experiment_id: NonEmptyStr
    model_io_contract: ModelIOContract
    forward_contract: ForwardContract
    dataset_profile: dict[str, object]
    task_data_path_id: NonEmptyStr
    task_data_path_content_sha256: Sha256
    task_composition_fingerprint: Sha256
    plugin_configured_ref: NonEmptyStr


def _verified_bytes(path: str, expected_sha256: str, expected_size: int | None = None) -> bytes:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"trained-model source is not a regular file: {source}")
    payload = source.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError(f"trained-model source digest changed before certification: {source}")
    if expected_size is not None and len(payload) != expected_size:
        raise ValueError(f"trained-model source size changed before certification: {source}")
    return payload


def _publish_blob(
    root: Path, payload: bytes, *, suffix: str, media_type: str
) -> CertifiedArtifactRef:
    digest = hashlib.sha256(payload).hexdigest()
    relative = Path("trained_model_artifacts") / "blobs" / f"{digest}{suffix}"
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        publish_bytes_write_once(str(destination), payload)
    except FileExistsError as exc:
        if destination.read_bytes() != payload:
            raise ValueError(
                "content-addressed trained-model blob disagrees with its digest"
            ) from exc
    return CertifiedArtifactRef(
        logical_ref=relative.as_posix(),
        sha256=digest,
        media_type=media_type,
        byte_size=len(payload),
    )


def emit_trained_model_artifact(
    candidate: TrainingArtifactCandidate,
    context: TrainedModelEmissionContext,
) -> TrainedModelArtifactRef:
    """Persist one immutable artifact from explicit executor/task evidence."""

    candidate = TrainingArtifactCandidate.model_validate(candidate)
    context = TrainedModelEmissionContext.model_validate(context)
    if context.model_io_contract.inference is None:
        raise ValueError("trained-model emission requires ModelIOContract.inference")
    if context.forward_contract.model_io != context.model_io_contract:
        raise ValueError("forward contract and run-bound ModelIOContract disagree")

    root = Path(context.workspace).resolve()
    root.mkdir(parents=True, exist_ok=True)
    checkpoint_payload = _verified_bytes(
        candidate.checkpoint_path,
        candidate.checkpoint_sha256,
        candidate.checkpoint_byte_size,
    )
    config_payload = _verified_bytes(
        candidate.model_config_path,
        candidate.model_config_sha256,
        candidate.model_config_byte_size,
    )
    _verified_bytes(candidate.model_plugin_path, candidate.model_plugin_sha256)
    checkpoint_ref = _publish_blob(
        root, checkpoint_payload, suffix=".pt", media_type="application/x-pytorch-state-dict"
    )
    config_ref = _publish_blob(root, config_payload, suffix=".json", media_type="application/json")
    dependency_lock_ref = None
    checkout_lock = Path(__file__).resolve().parents[2] / "uv.lock"
    if checkout_lock.is_file():
        dependency_lock_ref = _publish_blob(
            root,
            checkout_lock.read_bytes(),
            suffix=".lock",
            media_type="text/plain",
        )

    scope_ref = None
    scope_sha256 = candidate.training_scope_sha256
    if candidate.training_scope_path is not None and scope_sha256 is not None:
        scope_payload = _verified_bytes(candidate.training_scope_path, scope_sha256)
        scope_ref = _publish_blob(
            root, scope_payload, suffix=".json", media_type="application/json"
        )
    else:
        raise ValueError("historical-inference model emission requires certified training scope")

    checkpoint = CheckpointArtifact(ref=checkpoint_ref)
    plugin_identity = ModelPluginIdentity(
        configured_ref=context.plugin_configured_ref,
        member=candidate.model_plugin_member,
        model_type=candidate.model_type,
        content_sha256=candidate.model_plugin_sha256,
    )
    construction = ModelConstructionContract(
        loss_type=candidate.effective_loss_type,
        implementation_sha256=registered_model_construction_implementation_sha256(),
    )
    task_binding = TaskInferenceBindingIdentity(
        task_data_path_id=context.task_data_path_id,
        task_data_path_content_sha256=context.task_data_path_content_sha256,
        dataset_profile_sha256=canonical_sha256(context.dataset_profile),
        task_composition_fingerprint=context.task_composition_fingerprint,
    )
    environment = ModelEnvironmentIdentity(
        python_version=platform.python_version(),
        siderius_revision=resolve_git_sha(),
        dependency_lock_ref=dependency_lock_ref,
    )
    executable_sha = TrainedModelArtifact.compute_executable_identity_sha256(
        checkpoint=checkpoint,
        model_config_ref=config_ref,
        model_plugin_identity=plugin_identity,
        model_construction_contract=construction,
        model_io_contract=context.model_io_contract,
        forward_contract=context.forward_contract,
        task_inference_binding=task_binding,
        environment_identity=environment,
    )
    artifact = TrainedModelArtifact(
        model_artifact_id=f"trained-model-{executable_sha[:20]}",
        executable_model_identity_sha256=executable_sha,
        checkpoint=checkpoint,
        model_config_ref=config_ref,
        model_plugin_identity=plugin_identity,
        model_construction_contract=construction,
        model_io_contract=context.model_io_contract,
        forward_contract=context.forward_contract,
        task_inference_binding=task_binding,
        training_scope=TrainingScopeProvenance(
            split_id="train",
            scope_id=f"training-scope-{scope_sha256[:20]}",
            scope_sha256=scope_sha256,
            scope_ref=scope_ref,
        ),
        training_run=ModelTrainingRunIdentity(
            run_name=context.run_name,
            iteration_id=context.iteration_id,
            candidate_id=context.candidate_id,
            experiment_id=context.experiment_id,
        ),
        environment_identity=environment,
        provenance=TrainedModelArtifactProvenance(
            produced_at=utc_now(),
            producer="siderius.training-artifact-emitter.v1",
        ),
    )
    artifact_payload = canonical_json_bytes(artifact)
    artifact_sha = hashlib.sha256(artifact_payload).hexdigest()
    relative = Path("trained_model_artifacts") / f"{artifact_sha}.json"
    destination = root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        publish_bytes_write_once(str(destination), artifact_payload)
    except FileExistsError as exc:
        if destination.read_bytes() != artifact_payload:
            raise ValueError(
                "trained-model artifact identity collided with different bytes"
            ) from exc
    return TrainedModelArtifactRef(
        artifact_ref=CertifiedArtifactRef(
            logical_ref=relative.as_posix(),
            sha256=artifact_sha,
            media_type="application/json",
            byte_size=len(artifact_payload),
        ),
        model_artifact_id=artifact.model_artifact_id,
        executable_model_identity_sha256=artifact.executable_model_identity_sha256,
    )


def copy_certified_artifact(root: Path, ref: CertifiedArtifactRef, destination: Path) -> None:
    """Small filesystem artifact authority used by local production/smoke callers."""

    source = (root.resolve() / ref.logical_ref).resolve()
    if root.resolve() not in source.parents or source.is_symlink() or not source.is_file():
        raise ValueError("certified trained-model ref escapes its workspace authority")
    payload = source.read_bytes()
    if hashlib.sha256(payload).hexdigest() != ref.sha256:
        raise ValueError("certified trained-model artifact digest mismatch")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
