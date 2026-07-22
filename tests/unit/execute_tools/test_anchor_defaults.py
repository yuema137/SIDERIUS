"""Focused tests for the committed reference anchor-map default (H100 portability PR).

Verifies that scoring uses the committed ``reference_data/segment_anchors.json``
by default, resolved independently of the current working directory, that an
explicit override wins, and that a missing / malformed artifact fails clearly.
No scoring mathematics is exercised here — only path resolution and loading.
"""

import json
import os

import pytest

from execute_tools.build_anchor_map import (
    default_anchor_map_path,
    load_anchor_map,
    resolve_anchor_map_path,
)


def test_default_points_to_committed_artifact():
    p = default_anchor_map_path()
    assert os.path.isabs(p)
    assert p.endswith(os.path.join("reference_data", "segment_anchors.json"))
    assert os.path.exists(p), "committed reference anchor map must exist in the repo"


def test_default_is_cwd_independent(tmp_path, monkeypatch):
    """Launched from the repo root vs. an unrelated directory → same path."""
    from_here = default_anchor_map_path()
    monkeypatch.chdir(tmp_path)
    from_elsewhere = default_anchor_map_path()
    assert from_here == from_elsewhere
    assert os.path.exists(from_elsewhere)


def test_resolve_prefers_explicit_override():
    assert resolve_anchor_map_path("/custom/anchors.json") == "/custom/anchors.json"


def test_resolve_falls_back_to_committed_default():
    assert resolve_anchor_map_path(None) == default_anchor_map_path()


def test_committed_artifact_loads_with_required_keys():
    data = load_anchor_map(default_anchor_map_path())
    assert "s_max" in data and "anchors" in data
    assert isinstance(data["s_max"], (int, float))


def test_missing_artifact_fails_clearly(tmp_path):
    with pytest.raises(FileNotFoundError, match="segment anchor map not found"):
        load_anchor_map(str(tmp_path / "does_not_exist.json"))


def test_malformed_json_fails_clearly(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not valid json ")
    with pytest.raises(ValueError, match="malformed JSON"):
        load_anchor_map(str(bad))


def test_valid_json_missing_required_keys_fails_clearly(tmp_path):
    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text(json.dumps({"anchors": {}}))  # missing "s_max"
    with pytest.raises(ValueError, match="missing required keys"):
        load_anchor_map(str(incomplete))
