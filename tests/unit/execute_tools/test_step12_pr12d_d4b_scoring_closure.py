"""Composed scoring binds declared deliverable and metric authorities."""

from pathlib import Path

from workflows.task_composition import compose_run_task_bindings


def test_quickstart_composition_binds_scoring_authorities() -> None:
    root = Path(__file__).resolve().parents[3]
    composition = compose_run_task_bindings(str(root / "configs/task_composition/quickstart.yaml"))
    assert composition.metric.spec.id
    assert composition.deliverable_naming is not None
