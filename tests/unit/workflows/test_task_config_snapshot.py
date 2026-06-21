"""
Unit tests for the task config snapshot helper in
``workflows/model_exploration.py`` (Commit T1b).

The helper :func:`workflows.model_exploration._snapshot_task_config` is the
one-line dependency of ``run_workflow`` that copies the active
``configs/task_config.yaml`` into ``{workspace}/{run_name}/task_config_snapshot.yaml``
exactly once per chain — see ``docs/design/enable_global_task_config.md``
§ Commit T1b.

These tests exercise the helper directly so we don't have to stand up the
full agent loop.

Covered behaviours:
  1. Clean ``run_dir`` → snapshot is written, content is byte-identical to
     the source ``configs/task_config.yaml``.
  2. Pre-existing snapshot → helper does NOT overwrite it (chain-mode
     iter 2+ semantics: the snapshot reflects the config active when the
     run was initialized, not whatever the operator edited mid-chain).
  3. The source path resolves relative to ``SIDERIUS_ROOT`` (anchored to
     the repo root), not the process cwd — verified by running the helper
     from a tmp cwd and confirming the snapshot still gets the committed
     repo content.
"""

from __future__ import annotations

import os
from pathlib import Path

from workflows.model_exploration import SIDERIUS_ROOT, _snapshot_task_config

_REPO_TASK_CONFIG = os.path.join(SIDERIUS_ROOT, "configs", "task_config.yaml")


def _read(path: str | os.PathLike[str]) -> bytes:
    return Path(path).read_bytes()


class TestSnapshotTaskConfig:
    def test_clean_run_dir_writes_snapshot(self, tmp_path):
        """First invocation on a clean run_dir → snapshot appears on disk."""
        run_dir = tmp_path / "ws" / "run_alpha"
        run_dir.mkdir(parents=True)
        snapshot = run_dir / "task_config_snapshot.yaml"
        assert not snapshot.exists(), "fixture setup error: snapshot pre-existed"

        _snapshot_task_config(str(run_dir))

        assert snapshot.exists(), "helper did not write the snapshot"

    def test_snapshot_is_byte_identical_to_source(self, tmp_path):
        """The snapshot content matches the committed configs/task_config.yaml
        byte-for-byte — uses shutil.copy2, not a re-serialise pass."""
        run_dir = tmp_path / "ws" / "run_alpha"
        run_dir.mkdir(parents=True)

        _snapshot_task_config(str(run_dir))

        assert _read(run_dir / "task_config_snapshot.yaml") == _read(_REPO_TASK_CONFIG)

    def test_existing_snapshot_is_not_overwritten(self, tmp_path):
        """Chain-mode iter 2+ semantics: a pre-existing snapshot survives a
        second call. The operator could edit configs/task_config.yaml between
        iter 1 and iter 2 and the snapshot must still reflect iter 1."""
        run_dir = tmp_path / "ws" / "run_alpha"
        run_dir.mkdir(parents=True)
        snapshot = run_dir / "task_config_snapshot.yaml"

        sentinel = b"# sentinel content set by iter 1\n"
        snapshot.write_bytes(sentinel)

        _snapshot_task_config(str(run_dir))

        assert _read(snapshot) == sentinel, (
            "helper overwrote an existing snapshot — chain-mode iter 2+ would "
            "silently lose the iter-1 provenance"
        )

    def test_source_path_is_resolved_relative_to_repo_root_not_cwd(self, tmp_path, monkeypatch):
        """Helper anchors the source path on SIDERIUS_ROOT so integration
        tests that don't chdir into the repo root still pick up the
        committed config."""
        # chdir into a tmp dir that has no configs/ subtree at all — a
        # cwd-relative copy would raise FileNotFoundError here.
        foreign_cwd = tmp_path / "foreign_cwd"
        foreign_cwd.mkdir()
        monkeypatch.chdir(foreign_cwd)

        run_dir = tmp_path / "ws" / "run_alpha"
        run_dir.mkdir(parents=True)

        _snapshot_task_config(str(run_dir))

        # The snapshot must exist + carry the REPO content (not whatever
        # might happen to live in the foreign cwd).
        assert (run_dir / "task_config_snapshot.yaml").exists()
        assert _read(run_dir / "task_config_snapshot.yaml") == _read(_REPO_TASK_CONFIG)
