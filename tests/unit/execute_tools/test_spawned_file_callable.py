"""Real spawn witnesses for externally owned file callables."""

from pathlib import Path

import pytest

from execute_tools.spawned_file_callable import (
    SpawnedFileCallable,
    map_spawned_file_callable,
)


def _write_plugin(path: Path) -> None:
    path.write_text(
        "def transform(value):\n    return {'input': value, 'output': value * 3}\n",
        encoding="utf-8",
    )


def test_external_callable_runs_in_real_spawn_workers(tmp_path: Path) -> None:
    plugin = tmp_path / "external_metric_worker.py"
    _write_plugin(plugin)
    reference = SpawnedFileCallable.capture(plugin, "transform")

    assert map_spawned_file_callable(reference, [2, 5], max_workers=2) == [
        {"input": 2, "output": 6},
        {"input": 5, "output": 15},
    ]


def test_worker_refuses_file_bytes_changed_after_capture(tmp_path: Path) -> None:
    plugin = tmp_path / "external_metric_worker.py"
    _write_plugin(plugin)
    reference = SpawnedFileCallable.capture(plugin, "transform")
    plugin.write_text("def transform(value):\n    return value * 99\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="content changed after capture"):
        map_spawned_file_callable(reference, [2], max_workers=1)
