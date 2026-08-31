"""Framework minimal examples remain the executable baseline."""

from pathlib import Path

from workflows.task_composition import compose_run_task_bindings


def test_both_framework_examples_compose() -> None:
    root = Path(__file__).resolve().parents[3]
    for name in ("quickstart", "synthetic_masked_regression"):
        assert compose_run_task_bindings(
            str(root / "configs/task_composition" / f"{name}.yaml")
        ).semantic_fingerprint
