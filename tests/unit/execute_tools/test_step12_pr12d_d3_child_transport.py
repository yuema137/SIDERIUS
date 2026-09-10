"""Generic child transport binds a task-owned scope codec."""

from pathlib import Path

from workflows.task_composition import compose_run_task_bindings


def test_synthetic_composition_binds_scope_serialization() -> None:
    root = Path(__file__).resolve().parents[3]
    composition = compose_run_task_bindings(
        str(root / "configs/task_composition/synthetic_masked_regression.yaml")
    )
    task = composition.task_data_path
    assert callable(task.serialize_scope)
    assert callable(task.deserialize_scope)
