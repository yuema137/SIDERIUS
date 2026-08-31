"""
Unit tests for the task config snapshot helper in
``workflows/model_exploration.py`` (Commit T1b).

The helper :func:`workflows.model_exploration._snapshot_task_config` is the
one-line dependency of ``run_workflow`` that serializes the active task
binding into ``{workspace}/{run_name}/task_config_snapshot.yaml`` exactly
once per chain.

These tests exercise the helper directly so we don't have to stand up the
full agent loop.

Covered behaviours:
  1. Clean ``run_dir`` → the active binding is written.
  2. Pre-existing snapshot → helper does NOT overwrite it (chain-mode
     iter 2+ semantics: the snapshot reflects the config active when the
     run was initialized, not whatever the operator edited mid-chain).
  3. Snapshotting is independent of the process cwd.
"""

from __future__ import annotations

import yaml

from workflows.model_exploration import _snapshot_task_config
from workflows.task_config import bind_task_config

TASK_CONFIG = {
    "task_description": "Predict a scalar response from a compact feature vector.",
    "forward_contract": {
        "input_shape": "[B, F] float32",
        "input_description": "compact feature vector",
        "output_shape": "[B, 1] float32",
        "output_description": "continuous scalar response",
        "num_classes": 0,
        "task_type": "regression",
    },
}


def _snapshot_bound_config(run_dir) -> None:
    with bind_task_config(TASK_CONFIG):
        _snapshot_task_config(str(run_dir))


class TestSnapshotTaskConfig:
    def test_clean_run_dir_writes_snapshot(self, tmp_path):
        """First invocation on a clean run_dir → snapshot appears on disk."""
        run_dir = tmp_path / "ws" / "run_alpha"
        run_dir.mkdir(parents=True)
        snapshot = run_dir / "task_config_snapshot.yaml"
        assert not snapshot.exists(), "fixture setup error: snapshot pre-existed"

        _snapshot_bound_config(run_dir)

        assert snapshot.exists(), "helper did not write the snapshot"

    def test_snapshot_semantically_matches_active_binding(self, tmp_path):
        """The snapshot records the active task declaration."""
        run_dir = tmp_path / "ws" / "run_alpha"
        run_dir.mkdir(parents=True)

        _snapshot_bound_config(run_dir)

        snapshot = yaml.safe_load((run_dir / "task_config_snapshot.yaml").read_text())
        assert snapshot == TASK_CONFIG

    def test_existing_snapshot_is_not_overwritten(self, tmp_path):
        """Chain-mode iter 2+ semantics: a pre-existing snapshot survives a
        second call. The operator could edit configs/task_config.yaml between
        iter 1 and iter 2 and the snapshot must still reflect iter 1."""
        run_dir = tmp_path / "ws" / "run_alpha"
        run_dir.mkdir(parents=True)
        snapshot = run_dir / "task_config_snapshot.yaml"

        sentinel = b"# sentinel content set by iter 1\n"
        snapshot.write_bytes(sentinel)

        _snapshot_bound_config(run_dir)

        assert snapshot.read_bytes() == sentinel, (
            "helper overwrote an existing snapshot — chain-mode iter 2+ would "
            "silently lose the iter-1 provenance"
        )

    def test_active_binding_is_independent_of_cwd(self, tmp_path, monkeypatch):
        """The helper does not look for an ambient cwd-relative task file."""
        foreign_cwd = tmp_path / "foreign_cwd"
        foreign_cwd.mkdir()
        monkeypatch.chdir(foreign_cwd)

        run_dir = tmp_path / "ws" / "run_alpha"
        run_dir.mkdir(parents=True)

        _snapshot_bound_config(run_dir)

        snapshot = yaml.safe_load((run_dir / "task_config_snapshot.yaml").read_text())
        assert snapshot == TASK_CONFIG
