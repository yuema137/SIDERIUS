"""Contract tests for the explicit, task-owned trial anchor reader."""

import json

import pytest

from execute_tools.task_data_path import bind_task_data_path
from execute_tools.trial_anchor_map import load_anchor_map


def test_loads_explicit_filename_and_preserves_payload(tmp_path, monkeypatch):
    """A caller path works from an unrelated CWD and retains extra metadata."""
    payload = {"s_max": 42.5, "anchors": {"arbitrary": [1.0]}, "owner": "task"}
    path = tmp_path / "caller-owned-map.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.chdir(tmp_path.parent)

    assert load_anchor_map(str(path)) == payload


@pytest.mark.parametrize(
    "content, expected",
    [
        ("{not-json", ValueError),
        ("[1, 2, 3]", ValueError),
        ('{"s_max": 1}', ValueError),
        ('{"anchors": {}}', ValueError),
    ],
)
def test_rejects_invalid_payloads(tmp_path, content, expected):
    path = tmp_path / "invalid.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(expected):
        load_anchor_map(str(path))


def test_missing_file_requires_caller_preparation(tmp_path):
    path = tmp_path / "missing.json"

    with pytest.raises(FileNotFoundError, match="caller- or task-owned"):
        load_anchor_map(str(path))


def test_tuner_public_alias_reaches_the_explicit_reader():
    """The production tuner seam must be the reusable reader, not a bypass."""
    import nodes.ml_hyperparameter_tune_agent as tuner

    assert tuner.load_anchor_map is load_anchor_map


class _TaskPath:
    task_data_path_id = "synthetic-anchor-task"

    def training_dataset(self, scope, params): ...
    def validation_dataset(self, scope, params): ...
    def write_deliverable(self, outputs, request): ...
    def read_evaluation_payload(self, request): ...

    def trial_anchor_path(self, data_root):
        return str(__import__("pathlib").Path(data_root) / "custom.json")


class _TaskWithoutAnchoring(_TaskPath):
    trial_anchor_path = None


def _write_map(path):
    path.write_text(json.dumps({"s_max": 2.0, "anchors": {"0": [1.0]}}), encoding="utf-8")


def test_real_tuner_declared_path_reaches_reader(tmp_path):
    from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
        _load_trial_anchor_map,
    )

    _write_map(tmp_path / "custom.json")
    with bind_task_data_path(_TaskPath()):
        assert _load_trial_anchor_map(composed=True, data_root=str(tmp_path))["s_max"] == 2.0


def test_real_tuner_declared_none_and_unresolved_composed_do_not_read(tmp_path, monkeypatch):
    from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
        _load_trial_anchor_map,
    )

    def fail(*args, **kwargs):
        raise AssertionError("absence branch attempted an anchor read")

    monkeypatch.setitem(_load_trial_anchor_map.__globals__, "load_anchor_map", fail)
    with bind_task_data_path(_TaskWithoutAnchoring()):
        assert _load_trial_anchor_map(composed=True, data_root=str(tmp_path)) is None
    assert _load_trial_anchor_map(composed=True, data_root=str(tmp_path)) is None


def test_real_tuner_legacy_path_remains_explicit(tmp_path):
    from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
        _load_trial_anchor_map,
    )

    _write_map(tmp_path / "segment_anchors.json")
    assert _load_trial_anchor_map(composed=False, data_root=str(tmp_path))["s_max"] == 2.0
