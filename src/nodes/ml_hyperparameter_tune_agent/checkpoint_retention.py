"""Attempt-owned training checkpoint lifetime after its last live consumer.

Certified model blobs are never retired here. A scored attempt without a
durable certified model keeps its original checkpoint for investigation.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.schemas.data_analysis.trained_model import (
    TrainedModelArtifact,
    TrainedModelArtifactRef,
)
from agent.schemas.hyperparam_tuning import ExperimentRecord
from core.campaign_identity import validate_path_component
from core.durable_io import append_line_durably
from core.sandbox_executor import sandbox_models_dir
from core.sandbox_layout import training_checkpoint_path
from execute_tools.trained_model_artifact import (
    read_certified_artifact,
    verify_certified_artifact_file,
)


class CheckpointRetentionError(RuntimeError):
    """The checkpoint lifetime could not be certified or durably recorded."""


@dataclass(frozen=True)
class CompletedTrainingAttempt:
    """One attempt whose last live checkpoint consumer has returned."""

    workspace: str
    run_name: str
    exp_id: str
    model_type: str
    is_trial: bool
    # A recorded scalar exists, even if a later gate invalidated the round.
    # Running the scorer with no usable scalar does not require model replay.
    scored: bool
    certified_ref: dict[str, object] | None


def recorded_experiment_ids(records: list[ExperimentRecord]) -> set[str]:
    """Identify attempts with records in the completed tuner output."""

    return {record.exp_id for record in records}


class CheckpointRetentionReceipt(BaseModel):
    """An exact training attempt's checkpoint disposition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_name: str = Field(min_length=1)
    exp_id: str = Field(min_length=1)
    model_type: str = Field(min_length=1)
    is_trial: bool
    status: Literal["absent", "retained", "retirement_planned", "retired", "failed"]
    reason: str
    checkpoint_sha256: str | None = None
    checkpoint_byte_size: int | None = None
    certified_checkpoint_sha256: str | None = None


def _file_identity(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _certified_checkpoint_sha256(
    workspace: Path,
    reference: TrainedModelArtifactRef,
    *,
    run_name: str,
    exp_id: str,
    source_digest: str,
    source_size: int,
) -> str:
    artifact = TrainedModelArtifact.model_validate_json(
        read_certified_artifact(workspace, reference.artifact_ref)
    )
    if (
        artifact.model_artifact_id != reference.model_artifact_id
        or artifact.executable_model_identity_sha256 != reference.executable_model_identity_sha256
        or artifact.training_run.run_name != run_name
        or artifact.training_run.experiment_id != exp_id
    ):
        raise ValueError("certified model document does not name this training attempt")
    checkpoint = artifact.checkpoint.ref
    if checkpoint.sha256 != source_digest or checkpoint.byte_size != source_size:
        raise ValueError("certified checkpoint differs from the training original")
    verify_certified_artifact_file(workspace, checkpoint)
    return checkpoint.sha256


def finalize_attempt_checkpoint(
    *,
    workspace: str,
    models_dir: str,
    run_name: str,
    exp_id: str,
    model_type: str,
    is_trial: bool,
    retain_training_checkpoints: bool,
    scored: bool,
    certified_ref: dict[str, object] | None,
    record_persisted: bool = True,
) -> CheckpointRetentionReceipt:
    """Retire only this attempt's original after scoring and certification.

    The intent is fsynced before unlinking. A completed receipt is fsynced
    afterwards. Any refusal leaves the source untouched and stops the run.
    """

    try:
        validate_path_component(model_type, kind="model type")
        validate_path_component(exp_id, kind="experiment ID")
        root = Path(workspace)
        models = Path(models_dir)
        if (
            models.is_symlink()
            or (models.exists() and not models.is_dir())
            or models.resolve() != Path(sandbox_models_dir(str(root.resolve())))
        ):
            raise ValueError("checkpoint directory is not this tuner workspace's cached_models")
        source = training_checkpoint_path(models, model_type, exp_id)
        if source.is_symlink() or (source.exists() and not source.is_file()):
            raise ValueError("attempt checkpoint is not a regular, non-symlink file")

        receipt_path = root / "training_checkpoint_retention_receipts.jsonl"

        def record(
            status: Literal["absent", "retained", "retirement_planned", "retired", "failed"],
            reason: str,
            digest: str | None = None,
            size: int | None = None,
            certified_digest: str | None = None,
        ) -> CheckpointRetentionReceipt:
            receipt = CheckpointRetentionReceipt(
                run_name=run_name,
                exp_id=exp_id,
                model_type=model_type,
                is_trial=is_trial,
                status=status,
                reason=reason,
                checkpoint_sha256=digest,
                checkpoint_byte_size=size,
                certified_checkpoint_sha256=certified_digest,
            )
            append_line_durably(str(receipt_path), receipt.model_dump_json())
            return receipt

        if not source.exists():
            return record("absent", "training produced no checkpoint")

        digest, size = _file_identity(source)
        certified_digest = None
        if certified_ref is not None:
            try:
                reference = TrainedModelArtifactRef.model_validate(certified_ref)
                certified_digest = _certified_checkpoint_sha256(
                    root,
                    reference,
                    run_name=run_name,
                    exp_id=exp_id,
                    source_digest=digest,
                    source_size=size,
                )
            except (OSError, ValueError) as exc:
                record("failed", f"certified model verification failed: {exc}", digest, size)
                raise
        if retain_training_checkpoints:
            return record("retained", "explicit retention request", digest, size, certified_digest)
        if not record_persisted:
            return record(
                "retained", "attempt record missing from run output", digest, size, certified_digest
            )
        if scored and certified_digest is None:
            return record("retained", "scored attempt has no certified model", digest, size)

        reason = "certified model preserved" if certified_digest else "attempt produced no score"
        record("retirement_planned", reason, digest, size, certified_digest)
        try:
            source.unlink()
            directory_fd = os.open(models, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            record("failed", f"checkpoint retirement failed: {exc}", digest, size, certified_digest)
            raise
        return record("retired", reason, digest, size, certified_digest)
    except (OSError, ValueError) as exc:
        raise CheckpointRetentionError(
            f"attempt {exp_id} checkpoint retention failed: {exc}"
        ) from exc


def finalize_run_checkpoints(
    attempts: list[CompletedTrainingAttempt],
    *,
    retain_training_checkpoints: bool,
    recorded_exp_ids: set[str],
) -> list[CheckpointRetentionReceipt]:
    """Retire originals after the whole tuner iteration and its output finish.

    The caller collects exact attempts as they finish. No directory scan can
    confuse another iteration's checkpoint with this run's failed attempts.
    """

    return [
        finalize_attempt_checkpoint(
            workspace=attempt.workspace,
            models_dir=sandbox_models_dir(attempt.workspace),
            run_name=attempt.run_name,
            exp_id=attempt.exp_id,
            model_type=attempt.model_type,
            is_trial=attempt.is_trial,
            retain_training_checkpoints=retain_training_checkpoints,
            scored=attempt.scored,
            certified_ref=attempt.certified_ref,
            record_persisted=attempt.exp_id in recorded_exp_ids,
        )
        for attempt in attempts
    ]
