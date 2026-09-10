"""Regression for issue #386: generic import must not select a task config."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_generic_workflow_import_does_not_read_legacy_task_config() -> None:
    """Fail when importing the generic workflow emits the legacy warning.

    The subprocess starts with a clean module cache. Promoting warnings to
    errors makes the pre-repair import-time configuration read terminate at
    the exact offending edge; ordinary schema validation cannot detect file
    I/O that happens merely because a module was imported.
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    completed = subprocess.run(
        [
            sys.executable,
            "-W",
            "error",
            "-c",
            "import workflows.model_exploration",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_explicit_data_root_refusal_does_not_fall_through_to_legacy_config(
    tmp_path: Path,
) -> None:
    """Catch restoring a task-config fallback behind explicit root validation."""
    import execute_tools.data_paths as data_paths

    assert not hasattr(data_paths, "_legacy_data_config")
    with pytest.raises(data_paths.DatasetDirectoryUnavailable, match="--data_dir"):
        data_paths.resolve_dataset_dir(str(tmp_path / "missing-data"), purpose="external task")
