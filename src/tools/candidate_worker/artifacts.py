"""Verify native output ownership and capture only absent native records."""

from pathlib import Path

from pydantic import BaseModel

from agent.schemas.custom_loss_contract import merge_task_owned_custom_loss
from agent.schemas.hyperparam_tuning import TaskCompositionRef
from agent.schemas.implementor import ImplementorOutput
from core.durable_io import publish_bytes_write_once
from ml_models.plugin_binding import (
    active_run_model_plugins,
    declared_package_model,
    require_declared_model_source,
)
from workflows.attempt_storage import ImplAttemptStorage

from .record_json import record_json


def capture_record(path: Path, output: BaseModel) -> None:
    """Preserve a node's bytes; missing native persistence is worker-owned."""
    if path.exists():
        recorded = type(output).model_validate_json(path.read_bytes())
        if recorded != output:
            raise ValueError(f"native record disagrees with returned output: {path}")
        return
    publish_bytes_write_once(str(path), record_json(output, indent=2) + b"\n")


def require_contained(path: str, roots: tuple[Path, ...]) -> None:
    if not Path(path).is_absolute() or not any(
        Path(path).resolve().is_relative_to(root.resolve()) for root in roots
    ):
        raise ValueError(f"native artifact escapes declared roots: {path}")


def verify_artifacts(
    output: ImplementorOutput,
    attempt: ImplAttemptStorage,
    read_only: tuple[str, ...],
    task_ref: TaskCompositionRef,
) -> None:
    model_roots = (Path(attempt.plugin_dir),)
    declared = declared_package_model(output.model_type, active_run_model_plugins())
    if Path(output.model_file_path).resolve().is_relative_to(Path(attempt.plugin_dir).resolve()):
        require_contained(output.test_file_path, (Path(attempt.test_dir),))
        require_contained(output.description_file_path, model_roots)
    else:
        if declared is None:
            raise ValueError("reused model is not a task-declared package model")
        require_declared_model_source(declared, output.model_file_path)
        roots = tuple(Path(p) for p in read_only)
        require_contained(output.model_file_path, roots)
        expected_description = (
            Path(output.model_file_path).parent / output.model_type / "description.md"
        )
        if (
            Path(output.description_file_path) != expected_description
            or output.test_file_path != ""
        ):
            raise ValueError(
                "reused model must preserve native description path and empty test sentinel"
            )
        require_contained(output.description_file_path, roots)
    require_contained(
        output.model_file_path,
        model_roots if declared is None else (*model_roots, *(Path(p) for p in read_only)),
    )
    loss = output.loss_provenance
    if loss is not None:
        if loss.action == "generated":
            require_contained(loss.loss_file_path, (Path(attempt.loss_dir),))
        else:
            task_loss = task_ref.task_owned_custom_loss
            if task_loss is None or (
                loss.loss_name,
                Path(loss.loss_file_path).resolve(),
                loss.contract_snapshot,
            ) != (task_loss.name, Path(task_loss.file_path).resolve(), task_loss.contract_snapshot):
                raise ValueError("reused loss disagrees with task-declared source")
            merge_task_owned_custom_loss((), task_loss)
            require_contained(loss.loss_file_path, tuple(Path(p) for p in read_only))
