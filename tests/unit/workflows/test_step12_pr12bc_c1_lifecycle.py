"""One synthetic task composition binds the full lifecycle authorities."""

from pathlib import Path

from workflows.task_composition import compose_run_task_bindings


def test_synthetic_composition_binds_training_scoring_and_health() -> None:
    root = Path(__file__).resolve().parents[3]
    composition = compose_run_task_bindings(
        str(root / "configs/task_composition/synthetic_masked_regression.yaml")
    )
    assert composition.task_data_path is not None
    assert composition.metric is not None
    assert composition.task_health_binding
    assert composition.objective is not None
