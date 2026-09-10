"""A composed run acquires its metric from the manifest."""

from pathlib import Path

from workflows.task_composition import compose_metric_from_manifest


def test_framework_quickstart_metric_is_manifest_owned() -> None:
    root = Path(__file__).resolve().parents[3]
    metric = compose_metric_from_manifest(str(root / "configs/task_composition/quickstart.yaml"))
    assert metric.spec.id
    assert metric.spec.direction in {"higher", "lower"}
