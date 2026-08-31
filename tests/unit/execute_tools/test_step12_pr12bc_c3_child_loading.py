"""External task implementations load through the declared plugin boundary."""

from pathlib import Path

from workflows.task_composition import compose_run_task_bindings


def test_synthetic_task_implementation_loads_from_its_manifest() -> None:
    root = Path(__file__).resolve().parents[3]
    composition = compose_run_task_bindings(
        str(root / "configs/task_composition/synthetic_masked_regression.yaml")
    )
    assert composition.task_data_path.task_data_path_id == "synthetic_masked_regression"
