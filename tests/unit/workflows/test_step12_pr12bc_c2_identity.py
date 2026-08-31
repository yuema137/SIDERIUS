"""Composition identity is content-derived rather than path-derived."""

from pathlib import Path

from workflows.task_composition import compose_run_task_bindings


def test_repeated_composition_has_one_semantic_identity() -> None:
    root = Path(__file__).resolve().parents[3]
    manifest = root / "configs/task_composition/synthetic_masked_regression.yaml"
    assert (
        compose_run_task_bindings(str(manifest)).semantic_fingerprint
        == compose_run_task_bindings(str(manifest)).semantic_fingerprint
    )
