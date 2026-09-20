"""Attempt output lifetime after scoring and Health have consumed the files.

The task is the deliverable naming authority. The framework's atomic HDF5
writer owns its own marker and temporary-file suffixes; the run's existing
attempt-scoped naming contract bounds their cleanup. An uncomposed indexed
deliverable uses that same contract for its published files. Neither path
scans unrelated workspaces or checkpoints.
"""

from __future__ import annotations

from pathlib import Path

from core.campaign_identity import validate_path_component
from core.durable_io import append_line_durably
from execute_tools.array2h5 import atomic_abra_auxiliary_patterns
from execute_tools.deliverable_spec import DeliverableNaming
from execute_tools.evaluation_execution import candidate_evaluation_executor
from execute_tools.model_output_retention import OutputRetentionReceipt, apply_output_retention
from execute_tools.task_data_path import (
    EvaluationReadRequest,
    TaskOutputArtifactCapability,
    TaskOutputArtifactInventory,
)


class OutputRetentionError(RuntimeError):
    """Output retirement could not be certified; this is not model evidence."""


class _LegacyIndexedOutputInventory:
    """Compatibility adapter for an uncomposed indexed deliverable contract."""

    def __init__(self, naming: DeliverableNaming) -> None:
        self._naming = naming

    def enumerate_output_artifacts(
        self, request: EvaluationReadRequest
    ) -> TaskOutputArtifactInventory:
        # The legacy naming contract interpolates these values into a glob.
        # Validate the values before constructing the pattern so one attempt
        # cannot widen its inventory to neighboring attempts.
        validate_path_component(request.model_type, kind="model_type")
        validate_path_component(request.run_name, kind="run_name")
        validate_path_component(request.exp_id, kind="exp_id")
        pattern = self._naming.attempt_glob(
            model_type=request.model_type,
            run_name=request.run_name,
            exp_id=request.exp_id,
        )
        paths = tuple(sorted(path.name for path in Path(request.deliverable_dir).glob(pattern)))
        paths += _atomic_writer_auxiliaries(request, self._naming)
        return TaskOutputArtifactInventory(
            run_name=request.run_name,
            exp_id=request.exp_id,
            model_type=request.model_type,
            relative_paths=paths,
        )


def _atomic_writer_auxiliaries(
    request: EvaluationReadRequest, naming: DeliverableNaming
) -> tuple[str, ...]:
    """Enumerate only files the framework's atomic HDF5 writer can leave.

    The scientific task still owns its deliverable inventory. These suffixes
    are owned by the framework writer and can outlive a killed child before a
    finished deliverable exists for the task to enumerate.
    """

    for value, kind in (
        (request.model_type, "model_type"),
        (request.run_name, "run_name"),
        (request.exp_id, "exp_id"),
    ):
        validate_path_component(value, kind=kind)
    pattern = naming.attempt_glob(
        model_type=request.model_type,
        run_name=request.run_name,
        exp_id=request.exp_id,
    )
    root = Path(request.deliverable_dir)
    return tuple(
        sorted(
            path.name
            for auxiliary_pattern in atomic_abra_auxiliary_patterns(pattern)
            for path in root.glob(auxiliary_pattern)
        )
    )


class _WriterAugmentedOutputInventory:
    """Add framework-owned atomic-writer files to a task's exact inventory."""

    def __init__(self, task: TaskOutputArtifactCapability, naming: DeliverableNaming) -> None:
        self._task = task
        self._naming = naming

    def enumerate_output_artifacts(
        self, request: EvaluationReadRequest
    ) -> TaskOutputArtifactInventory:
        declared = TaskOutputArtifactInventory.model_validate(
            self._task.enumerate_output_artifacts(request)
        )
        if (declared.run_name, declared.exp_id, declared.model_type) != (
            request.run_name,
            request.exp_id,
            request.model_type,
        ):
            raise ValueError("output inventory names a different inference attempt")
        return TaskOutputArtifactInventory(
            run_name=request.run_name,
            exp_id=request.exp_id,
            model_type=request.model_type,
            relative_paths=tuple(
                dict.fromkeys(
                    (*declared.relative_paths, *_atomic_writer_auxiliaries(request, self._naming))
                )
            ),
        )


def finalize_attempt_outputs(
    *,
    task_data_path: object | None,
    legacy_naming: DeliverableNaming | None,
    deliverable_dir: str,
    workspace: str,
    run_name: str,
    exp_id: str,
    model_type: str,
    retain_model_outputs: bool,
) -> OutputRetentionReceipt | None:
    """Certify local outputs; a complete evaluator owns its external outputs."""

    # No local inference writer runs under this explicit binding. Its evaluator
    # owns output retention and the outer deployment owns interrupted-job cleanup.
    # Do not require a local inventory or manufacture a local cleanup receipt.
    if candidate_evaluation_executor() is not None:
        return None

    task: TaskOutputArtifactCapability | None = None
    if isinstance(task_data_path, TaskOutputArtifactCapability):
        task = (
            _WriterAugmentedOutputInventory(task_data_path, legacy_naming)
            if legacy_naming is not None
            else task_data_path
        )
    elif task_data_path is None and legacy_naming is not None:
        task = _LegacyIndexedOutputInventory(legacy_naming)

    receipt = apply_output_retention(
        task=task,
        request=EvaluationReadRequest(
            deliverable_dir=deliverable_dir,
            exp_id=exp_id,
            run_name=run_name,
            model_type=model_type,
        ),
        retain_model_outputs=retain_model_outputs,
    )
    receipt_path = Path(workspace) / "model_output_retention_receipts.jsonl"
    try:
        append_line_durably(str(receipt_path), receipt.model_dump_json())
    except (OSError, ValueError) as exc:
        raise OutputRetentionError(
            f"attempt {exp_id}: output retention receipt could not be persisted: {exc}"
        ) from exc
    if receipt.status != "completed":
        raise OutputRetentionError(
            f"attempt {exp_id}: model output retention {receipt.status}: "
            f"{receipt.failure_code}: {receipt.failure_message}"
        )
    return receipt
