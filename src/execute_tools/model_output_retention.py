"""Exact, task-certified lifecycle for per-sample inference outputs.

The task names its own artifacts. This module validates filesystem containment,
records content identities, and applies the run's retention policy. It never
discovers output files by a framework-owned glob or task name.
"""

from __future__ import annotations

import hashlib
import stat
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from execute_tools.task_data_path import (
    EvaluationReadRequest,
    TaskOutputArtifactCapability,
    TaskOutputArtifactInventory,
)


class OutputArtifactEvidence(BaseModel):
    """Content identity and observed disposition of one exact output file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    relative_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=0)
    disposition: Literal["retained", "retired"]


class OutputRetentionReceipt(BaseModel):
    """Attempt-scoped receipt; not a Data Analysis source or access grant."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_name: str = Field(min_length=1)
    exp_id: str = Field(min_length=1)
    model_type: str = Field(min_length=1)
    retain_model_outputs: bool
    status: Literal["completed", "refused", "failed"]
    artifacts: tuple[OutputArtifactEvidence, ...] = ()
    failure_code: str | None = None
    failure_message: str | None = None


def _exact_files(
    request: EvaluationReadRequest, inventory: TaskOutputArtifactInventory
) -> tuple[tuple[str, Path], ...]:
    if (inventory.run_name, inventory.exp_id, inventory.model_type) != (
        request.run_name,
        request.exp_id,
        request.model_type,
    ):
        raise ValueError("output inventory names a different inference attempt")
    root = Path(request.deliverable_dir)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("output root must be an existing non-symlink directory")
    files: list[tuple[str, Path]] = []
    for relative in inventory.relative_paths:
        parsed = PurePosixPath(relative)
        if (
            parsed.is_absolute()
            or not parsed.parts
            or any(part in {".", ".."} for part in relative.split("/"))
            or str(parsed) != relative
        ):
            raise ValueError("output inventory contains an unsafe relative path")
        current = root
        for part in parsed.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("output inventory traverses a symlink")
        if not stat.S_ISREG(current.stat(follow_symlinks=False).st_mode):
            raise ValueError("output inventory contains a non-regular file")
        files.append((relative, current))
    return tuple(files)


def _digest_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
            count += len(block)
    return digest.hexdigest(), count


def apply_output_retention(
    *,
    task: TaskOutputArtifactCapability | None,
    request: EvaluationReadRequest,
    retain_model_outputs: bool,
) -> OutputRetentionReceipt:
    """Certify exact outputs and retire them only after their consumers finish.

    Invalid inventories are refused before any deletion. A filesystem failure
    during deletion is visible with the successfully retired prefix recorded;
    callers must treat any non-completed receipt as an attempt failure.
    """

    def receipt(
        status: Literal["completed", "refused", "failed"],
        *,
        artifacts: tuple[OutputArtifactEvidence, ...] = (),
        failure_code: str | None = None,
        failure_message: str | None = None,
    ) -> OutputRetentionReceipt:
        return OutputRetentionReceipt(
            run_name=request.run_name,
            exp_id=request.exp_id,
            model_type=request.model_type,
            retain_model_outputs=retain_model_outputs,
            status=status,
            artifacts=artifacts,
            failure_code=failure_code,
            failure_message=failure_message,
        )

    if task is None:
        return receipt(
            "refused",
            failure_code="output_inventory_unavailable",
            failure_message="task does not declare exact output artifacts",
        )
    try:
        inventory = TaskOutputArtifactInventory.model_validate(
            task.enumerate_output_artifacts(request)
        )
        files = _exact_files(request, inventory)
        measured = [(relative, path, *_digest_file(path)) for relative, path in files]
    except (OSError, ValueError) as exc:
        return receipt(
            "refused",
            failure_code="invalid_output_inventory",
            failure_message=str(exc) or type(exc).__name__,
        )
    except Exception as exc:
        return receipt(
            "failed",
            failure_code="output_inventory_failed",
            failure_message=f"{type(exc).__name__}: {exc}",
        )

    evidence: list[OutputArtifactEvidence] = []
    for relative, path, digest, size in measured:
        disposition: Literal["retained", "retired"] = "retained"
        if not retain_model_outputs:
            try:
                path.unlink()
            except OSError as exc:
                return receipt(
                    "failed",
                    artifacts=tuple(evidence),
                    failure_code="output_retirement_failed",
                    failure_message=f"{relative}: {exc}",
                )
            disposition = "retired"
        evidence.append(
            OutputArtifactEvidence(
                relative_path=relative,
                sha256=digest,
                byte_size=size,
                disposition=disposition,
            )
        )
    return receipt("completed", artifacts=tuple(evidence))
