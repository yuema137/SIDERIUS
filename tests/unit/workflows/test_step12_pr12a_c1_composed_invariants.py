"""Composed bindings are deterministic and relocation-independent."""

from pathlib import Path

from workflows.task_composition import compose_run_task_bindings


def test_quickstart_composition_is_stable() -> None:
    root = Path(__file__).resolve().parents[3]
    manifest = root / "configs/task_composition/quickstart.yaml"
    first = compose_run_task_bindings(str(manifest))
    second = compose_run_task_bindings(str(manifest))
    assert first.semantic_fingerprint == second.semantic_fingerprint
    assert first.task_data_path.task_data_path_id == second.task_data_path.task_data_path_id
