"""
Unit tests for workflows/task_config.py

Covers:
  - load_task_config: fail-fast on missing file, empty/non-dict YAML,
    empty task_description, missing forward_contract block, ForwardContract
    ValidationError on missing key, and happy-path round-trip.
  - get_task_description: happy path + caller-bypass empty path.
  - render_forward_contract: full ForwardContract → multi-line block with the
    expected anchors; default ForwardContract → empty string; custom non-SQUID
    ForwardContract → custom values present, SQUID values absent.
  - Module-level cache: same path served from cache; distinct paths cached
    independently; ``_clear_cache_for_tests`` resets between fixtures.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.schemas.task_config import ForwardContract
from workflows.task_config import (
    _clear_cache_for_tests,
    get_task_description,
    load_task_config,
    render_forward_contract,
)

# ---------------------------------------------------------------------------
# Fixtures — synthetic YAML strings written to a tmp_path each test
# ---------------------------------------------------------------------------

_VALID_YAML = """\
task_description: |
  full-spectrum 1-D time-series denoising of SQUID dark-matter
  detector data.

forward_contract:
  input_shape: "[B, T] int64"
  input_description: "raw signal, integer class indices 0-255"
  output_shape: "[B, 256, T] float32"
  output_description: "per-timestep logits over 256 denoising classes"
  num_classes: 256
  embedding_note: >
    Input values are integer class indices — use nn.Embedding.
  output_head_note: >
    Output must be exactly [B, 256, T] — use a final Conv1d head.
  task_type: "classification"
  task_note: >
    Offline denoising — output at position t may depend on all positions.
"""

_EMPTY_TASK_DESCRIPTION_YAML = """\
task_description: "   "
forward_contract:
  input_shape: "[B, T] int64"
  input_description: "raw"
  output_shape: "[B, 256, T] float32"
  output_description: "logits"
  num_classes: 256
  embedding_note: ""
  output_head_note: ""
  task_type: "classification"
  task_note: ""
"""

_MISSING_FC_KEY_YAML = """\
task_description: "ok"
forward_contract:
  input_shapes: "[B, T] int64"   # typo: plural — triggers ValidationError
  input_description: "raw"
  output_shape: "[B, 256, T] float32"
  output_description: "logits"
  num_classes: 256
  embedding_note: ""
  output_head_note: ""
  task_type: "classification"
  task_note: ""
"""

_MISSING_FC_BLOCK_YAML = """\
task_description: "ok"
"""

_FC_NOT_MAPPING_YAML = """\
task_description: "ok"
forward_contract: "not a mapping"
"""


def _write(tmp_path: Path, body: str, name: str = "task_config.yaml") -> str:
    """Write ``body`` to ``tmp_path/name`` and return the absolute path."""
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return str(p)


@pytest.fixture(autouse=True)
def _reset_cache():
    """Drop the module-level cache between tests so stale parsed dicts from
    a previous fixture file path can't leak into the next test."""
    _clear_cache_for_tests()
    yield
    _clear_cache_for_tests()


# ---------------------------------------------------------------------------
# load_task_config
# ---------------------------------------------------------------------------


class TestLoadTaskConfig:
    def test_valid_yaml_returns_dict_with_correct_keys(self, tmp_path):
        path = _write(tmp_path, _VALID_YAML)
        cfg = load_task_config(path)
        assert isinstance(cfg, dict)
        assert "task_description" in cfg
        assert "forward_contract" in cfg
        assert cfg["task_description"].startswith("full-spectrum 1-D")
        assert cfg["forward_contract"]["num_classes"] == 256
        assert cfg["forward_contract"]["input_shape"] == "[B, T] int64"

    def test_missing_file_raises_filenotfounderror_with_remediation(self, tmp_path):
        bogus = str(tmp_path / "nope.yaml")
        with pytest.raises(FileNotFoundError) as exc:
            load_task_config(bogus)
        msg = str(exc.value)
        assert "not found" in msg
        assert "--task_composition" in msg
        assert "does not select a scientific task by default" in msg

    def test_empty_yaml_raises_valueerror(self, tmp_path):
        path = _write(tmp_path, "")
        with pytest.raises(ValueError, match="empty or not a mapping"):
            load_task_config(path)

    def test_yaml_top_level_list_raises_valueerror(self, tmp_path):
        # YAML that parses to a list, not a dict — also rejected at the
        # same fail-fast checkpoint.
        path = _write(tmp_path, "- a\n- b\n")
        with pytest.raises(ValueError, match="empty or not a mapping"):
            load_task_config(path)

    def test_empty_task_description_raises_valueerror(self, tmp_path):
        path = _write(tmp_path, _EMPTY_TASK_DESCRIPTION_YAML)
        with pytest.raises(ValueError, match="'task_description' is missing or empty"):
            load_task_config(path)

    def test_missing_forward_contract_block_raises_valueerror(self, tmp_path):
        path = _write(tmp_path, _MISSING_FC_BLOCK_YAML)
        with pytest.raises(ValueError, match="'forward_contract' block is missing"):
            load_task_config(path)

    def test_forward_contract_not_mapping_raises_valueerror(self, tmp_path):
        path = _write(tmp_path, _FC_NOT_MAPPING_YAML)
        with pytest.raises(ValueError, match="'forward_contract' must be a mapping"):
            load_task_config(path)

    def test_missing_forward_contract_key_raises_validationerror(self, tmp_path):
        path = _write(tmp_path, _MISSING_FC_KEY_YAML)
        # ``extra="forbid"`` makes ``input_shapes`` (extra) reject the dict.
        with pytest.raises(ValidationError):
            load_task_config(path)

    def test_task_description_is_stripped(self, tmp_path):
        yaml_body = (
            'task_description: "   stripped value   "\n'
            "forward_contract:\n"
            '  input_shape: "[B, T] int64"\n'
            '  input_description: "raw"\n'
            '  output_shape: "[B, 256, T] float32"\n'
            '  output_description: "logits"\n'
            "  num_classes: 256\n"
            '  embedding_note: ""\n'
            '  output_head_note: ""\n'
            '  task_type: "classification"\n'
            '  task_note: ""\n'
        )
        path = _write(tmp_path, yaml_body)
        cfg = load_task_config(path)
        assert cfg["task_description"] == "stripped value"

    def test_cache_returns_same_object_on_second_call(self, tmp_path):
        path = _write(tmp_path, _VALID_YAML)
        cfg1 = load_task_config(path)
        cfg2 = load_task_config(path)
        # Same dict object → cache hit, not a re-parse.
        assert cfg1 is cfg2

    def test_distinct_paths_cached_independently(self, tmp_path):
        path_a = _write(tmp_path, _VALID_YAML, name="a.yaml")
        # Vary the task_description to detect cross-contamination.
        body_b = _VALID_YAML.replace("full-spectrum", "alt-task")
        path_b = _write(tmp_path, body_b, name="b.yaml")
        cfg_a = load_task_config(path_a)
        cfg_b = load_task_config(path_b)
        assert cfg_a["task_description"].startswith("full-spectrum")
        assert cfg_b["task_description"].startswith("alt-task")
        assert cfg_a is not cfg_b


# ---------------------------------------------------------------------------
# get_task_description
# ---------------------------------------------------------------------------


class TestGetTaskDescription:
    def test_happy_path(self):
        cfg = {"task_description": "hello world"}
        assert get_task_description(cfg) == "hello world"

    def test_strips_surrounding_whitespace(self):
        cfg = {"task_description": "   padded   "}
        assert get_task_description(cfg) == "padded"

    def test_missing_key_returns_empty(self):
        # Only reachable when caller bypasses load_task_config.
        assert get_task_description({}) == ""

    def test_none_value_returns_empty(self):
        assert get_task_description({"task_description": None}) == ""


# ---------------------------------------------------------------------------
# render_forward_contract
# ---------------------------------------------------------------------------


class TestRenderForwardContract:
    def _full_fc(self, **overrides) -> ForwardContract:
        """Construct a populated SQUID-default ForwardContract; overrides
        are applied on top for the custom-shape test."""
        defaults: dict[str, str | int] = {
            "input_shape": "[B, T] int64",
            "input_description": "raw signal, integer class indices 0-255",
            "output_shape": "[B, 256, T] float32",
            "output_description": "per-timestep logits over 256 denoising classes",
            "num_classes": 256,
            "embedding_note": "Use nn.Embedding(256, embed_dim) for the input.",
            "output_head_note": "Use a final Conv1d(channels, 256, 1) head.",
            "task_type": "classification",
            "task_note": "Offline denoising — non-causal.",
        }
        defaults.update(overrides)
        return ForwardContract(**defaults)  # type: ignore[arg-type]

    def test_full_forward_contract_contains_expected_anchors(self):
        rendered = render_forward_contract(self._full_fc())
        # The four anchors named in the design doc's T1a test plan.
        assert "[B, T] int64" in rendered  # input_shape
        assert "[B, 256, T] float32" in rendered  # output_shape
        assert "nn.Embedding(256, embed_dim)" in rendered  # embedding_note
        assert "classification" in rendered  # task_type
        # Plus the non-negotiable header line.
        assert "forward contract" in rendered.lower()
        # The placeholder name itself never appears in the rendered output.
        assert "{FORWARD_CONTRACT}" not in rendered

    def test_default_forward_contract_renders_to_empty_string(self):
        assert render_forward_contract(ForwardContract()) == ""

    def test_custom_non_squid_shapes_replace_defaults(self):
        # Regressor-style contract: 1-D float output, no class count.
        fc = self._full_fc(
            input_shape="[B, T] float32",
            input_description="raw audio, normalised",
            output_shape="[B, T] float32",
            output_description="denoised audio waveform",
            num_classes=0,
            embedding_note="",
            output_head_note="Use a Linear(channels, 1) head + squeeze.",
            task_type="regression",
            task_note="Causal masking required.",
        )
        rendered = render_forward_contract(fc)
        # Custom shapes present.
        assert "[B, T] float32" in rendered
        assert "denoised audio waveform" in rendered
        assert "regression" in rendered
        # The SQUID classifier shape from the default fixture is gone.
        assert "[B, 256, T]" not in rendered
        # When num_classes == 0, the "(per-timestep N-class)" descriptor is
        # suppressed — the task_type line stays bare.
        assert "256-class" not in rendered

    def test_optional_notes_omitted_when_empty(self):
        # Minimum-viable populated contract — only the shapes and task_type.
        fc = ForwardContract(
            input_shape="[B, T] int64",
            input_description="raw",
            output_shape="[B, T] float32",
            output_description="denoised",
            num_classes=0,
            embedding_note="",
            output_head_note="",
            task_type="regression",
            task_note="",
        )
        rendered = render_forward_contract(fc)
        # Header + shapes + task_type line — but no blank-line-separated
        # extra paragraphs from the optional notes.
        assert "Use a final" not in rendered  # no output_head_note
        assert "may depend on" not in rendered  # no task_note
        # Renders without trailing whitespace.
        assert rendered == rendered.rstrip()


# ---------------------------------------------------------------------------
# Caller-owned binding and snapshot
# ---------------------------------------------------------------------------


class TestCallerOwnedTaskConfig:
    def test_no_argument_refuses_without_an_active_task(self):
        with pytest.raises(ValueError, match="no task configuration is bound"):
            load_task_config()

    def test_snapshot_persists_the_active_binding(self, tmp_path):
        from workflows.model_exploration import _snapshot_task_config
        from workflows.task_config import bind_task_config

        values = load_task_config(_write(tmp_path, _VALID_YAML))
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        with bind_task_config(values):
            _snapshot_task_config(str(run_dir))

        snapshot = load_task_config(str(run_dir / "task_config_snapshot.yaml"))
        assert snapshot == values
