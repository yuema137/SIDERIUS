"""TaskDataPath capability shape is checked through a synthetic implementation."""

from pathlib import Path

from workflows.task_composition import compose_run_task_bindings


def test_declared_task_data_path_exposes_the_complete_scope_codec() -> None:
    root = Path(__file__).resolve().parents[3]
    task = compose_run_task_bindings(
        str(root / "configs/task_composition/synthetic_masked_regression.yaml")
    ).task_data_path
    for name in (
        "build_training_scope",
        "build_eval_scope",
        "serialize_scope",
        "deserialize_scope",
    ):
        assert callable(getattr(task, name))
