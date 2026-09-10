"""Objective declarations are resolved by the generic composition boundary."""

from pathlib import Path

from workflows.task_composition import compose_run_task_bindings


def test_quickstart_builtin_objective_composes() -> None:
    root = Path(__file__).resolve().parents[3]
    composition = compose_run_task_bindings(str(root / "configs/task_composition/quickstart.yaml"))
    assert composition.objective is not None
