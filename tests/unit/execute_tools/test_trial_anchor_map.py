"""Contract tests for the explicit, task-owned trial anchor reader."""

import json

import pytest

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
