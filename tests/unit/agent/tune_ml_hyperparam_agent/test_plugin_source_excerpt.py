"""Phase D.1 — plugin-config-class source excerpt for the tuner planner.

Covers the two helpers in ``agent/prompts.py`` that surface
``@model_validator(mode='after')`` bodies to the planner (which
``model_json_schema()`` cannot represent):

  * ``_extract_config_class_source``: wraps ``inspect.getsource`` with
    truncation and graceful handling of sources that cannot be retrieved.
  * ``format_plugin_source_excerpt_block``: wraps the extracted source in the
    pinned authoritative heading the planner prompt renders.

See docs/improving_validation_awareness.md §D.1.
"""
import textwrap

from pydantic import BaseModel, Field, model_validator, field_validator

from agent.prompts import (
    _PLUGIN_SOURCE_EXCERPT_MAX_CHARS,
    _extract_config_class_source,
    format_plugin_source_excerpt_block,
)
from ml_models.plugin_loader import _load_plugin


# ---------------------------------------------------------------------------
# Fixtures — local classes exercised by inspect.getsource
# ---------------------------------------------------------------------------

class _MonotoneCfg(BaseModel):
    """Mirrors the exact ``dual_path_skip_fusion_cnn`` invariant that blew up
    ``exploit_cnn_v1`` iter-1 on 2026-04-17."""
    a: int = Field(default=1, ge=1)
    b: int = Field(default=2, ge=1)
    c: int = Field(default=3, ge=1)

    @model_validator(mode='after')
    def check_monotone(self):
        if not (self.a <= self.b <= self.c):
            raise ValueError(
                f"values must be nondecreasing, got {self.a}, {self.b}, {self.c}"
            )
        return self


class _FieldValidatorCfg(BaseModel):
    kernel_size: int = Field(default=3, ge=1)

    @field_validator('kernel_size')
    @classmethod
    def _odd(cls, v):
        if v % 2 == 0:
            raise ValueError("kernel_size must be odd")
        return v


class _PerFieldOnlyCfg(BaseModel):
    """No validators — only per-field bounds. Excerpt should still be emitted
    (cheap) but without any decorator lines."""
    channels: int = Field(default=8, ge=1, multiple_of=8)


# ===========================================================================
# _extract_config_class_source
# ===========================================================================

class TestExtractor:

    def test_none_returns_empty(self):
        assert _extract_config_class_source(None) == ""

    def test_model_validator_body_present(self):
        """The whole point of D.1 — the validator body must be visible in the
        extracted source, because ``model_json_schema()`` drops it."""
        src = _extract_config_class_source(_MonotoneCfg)
        assert "class _MonotoneCfg" in src
        assert "@model_validator" in src
        assert "check_monotone" in src
        assert "nondecreasing" in src

    def test_field_validator_decorator_present(self):
        src = _extract_config_class_source(_FieldValidatorCfg)
        assert "@field_validator" in src
        assert "kernel_size must be odd" in src

    def test_per_field_only_class_still_returns_source(self):
        """A class with no validators is a boring (but valid) excerpt — the
        helper must not silently swallow it. The excerpt is still useful
        because per-field ``multiple_of`` and ``ge`` appear in Python syntax
        rather than JSON schema slugs, which is easier for the LLM to parse."""
        src = _extract_config_class_source(_PerFieldOnlyCfg)
        assert "class _PerFieldOnlyCfg" in src
        assert "multiple_of=8" in src

    def test_truncates_when_over_limit(self):
        """The truncation branch is path-level, not class-level. We test it
        by monkeypatching ``inspect.getsource`` to return an oversize
        string — cheaper and more isolated than synthesizing a class with
        a 4000-char body on disk."""
        import agent.prompts as prompts_mod
        original = prompts_mod.inspect.getsource
        try:
            prompts_mod.inspect.getsource = lambda _cls: "x = 1\n" * 3000  # ~18000 chars
            src = _extract_config_class_source(_MonotoneCfg)
        finally:
            prompts_mod.inspect.getsource = original
        assert src.endswith("... (truncated)")
        # Budget: max_chars for the class body + rstrip slack + marker length.
        assert len(src) <= _PLUGIN_SOURCE_EXCERPT_MAX_CHARS + len("\n... (truncated)")

    def test_graceful_on_dynamic_class(self):
        """Classes created via ``type(...)`` have no source file;
        ``inspect.getsource`` raises ``OSError``/``TypeError``. Must return ""."""
        DynCfg = type("DynCfg", (BaseModel,), {"__module__": __name__})
        assert _extract_config_class_source(DynCfg) == ""

    def test_real_builtin_config_class(self):
        """Regression guard: the ``PUNetConfig`` class in
        ``ml_models/models_format_sandbox.py`` has a ``@model_validator`` —
        must surface in the excerpt so the planner sees it for built-in
        runs (not only agent-generated plugins)."""
        from ml_models.models_format_sandbox import PUNetConfig
        src = _extract_config_class_source(PUNetConfig)
        assert "class PUNetConfig" in src
        assert "@model_validator" in src or "@field_validator" in src


# ===========================================================================
# format_plugin_source_excerpt_block
# ===========================================================================

class TestBlockFormatter:

    def test_none_returns_empty(self):
        assert format_plugin_source_excerpt_block(None) == ""

    def test_heading_and_fence_present(self):
        block = format_plugin_source_excerpt_block(_MonotoneCfg)
        assert "## PLUGIN CONFIG SCHEMA" in block
        assert "authoritative" in block
        # Python code fence so the LLM treats it as code, not prose.
        assert "```python" in block
        assert block.rstrip().endswith("```")

    def test_embeds_extracted_source(self):
        block = format_plugin_source_excerpt_block(_MonotoneCfg)
        assert "check_monotone" in block
        assert "nondecreasing" in block

    def test_empty_when_source_unavailable(self):
        """Dynamic class → extractor returns "" → block returns "". Must NOT
        render a heading with an empty code fence (LLM would waste tokens
        reading an empty block)."""
        DynCfg = type("DynCfg2", (BaseModel,), {"__module__": __name__})
        assert format_plugin_source_excerpt_block(DynCfg) == ""


# ===========================================================================
# Plugin-loader integration — regression guard on the sys.modules registration
# ===========================================================================

_PLUGIN_SRC_WITH_VALIDATOR = textwrap.dedent("""\
    import torch
    import torch.nn as nn
    from pydantic import BaseModel, Field, model_validator

    PLUGIN_MODEL_TYPE = "monotone_test_plugin"

    class MonotoneTestCfg(BaseModel):
        model_type: str = "monotone_test_plugin"
        segmentation_size: int = Field(default=1000, ge=100)
        batch_size: int = 1
        a: int = Field(default=1, ge=1)
        b: int = Field(default=2, ge=1)
        c: int = Field(default=3, ge=1)

        @model_validator(mode='after')
        def _check_abc_monotone(self):
            if not (self.a <= self.b <= self.c):
                raise ValueError('a, b, c must be nondecreasing')
            return self

    class MonotoneTestModel(nn.Module):
        def __init__(self, config):
            super().__init__()
            self.linear = nn.Linear(config.segmentation_size, config.segmentation_size)

        def forward(self, x):
            out = self.linear(x.float())
            return out.unsqueeze(1).expand(-1, 256, -1)

    PLUGIN_CONFIG_CLASS = MonotoneTestCfg
    PLUGIN_MODEL_CLASS  = MonotoneTestModel
""")


class TestPluginLoaderIntegration:
    """Regression guard on the bug discovered 2026-04-17 during Phase D.5
    preparation: ``ml_models/plugin_loader._load_plugin`` used to register
    plugins under the placeholder name ``"_siderius_plugin_tmp"`` without
    adding them to ``sys.modules``. Python's inspect machinery therefore
    treated every plugin config class as a built-in, and
    ``_extract_config_class_source`` silently returned ``""`` — defeating the
    entire point of Phase D.1 for plugin runs (the failing-case class).

    The fix: each plugin is now registered as
    ``siderius_plugin_<filename_stem>`` in ``sys.modules``. These tests lock
    in that contract by exercising the full path end-to-end."""

    def test_extractor_resolves_plugin_class(self, tmp_path):
        """Plugin loaded via the real loader → extractor returns source with
        the validator body present. If the sys.modules registration
        regresses, ``inspect.getsource`` would raise ``TypeError`` again and
        this returns ``""``."""
        plugin_path = tmp_path / "monotone_test_plugin.py"
        plugin_path.write_text(_PLUGIN_SRC_WITH_VALIDATOR)

        plugin = _load_plugin(str(plugin_path))
        assert plugin is not None, "pre-condition: plugin should load cleanly"

        src = _extract_config_class_source(plugin["config_class"])
        assert "class MonotoneTestCfg" in src
        assert "@model_validator" in src
        assert "nondecreasing" in src

    def test_block_formatter_resolves_plugin_class(self, tmp_path):
        plugin_path = tmp_path / "monotone_test_plugin2.py"
        plugin_path.write_text(_PLUGIN_SRC_WITH_VALIDATOR)

        plugin = _load_plugin(str(plugin_path))
        block = format_plugin_source_excerpt_block(plugin["config_class"])

        assert "## PLUGIN CONFIG SCHEMA" in block
        assert "@model_validator" in block
        assert "nondecreasing" in block


# ===========================================================================
# LLMBridge.plan — end-to-end rendering check (step 2 of D.1)
# ===========================================================================

from unittest.mock import patch

from agent.llm_bridge import LLMBridge


class TestBrainPlanRendering:
    """Verifies ``LLMBridge.plan`` threads ``plugin_source_excerpt`` into the
    assembled user prompt. We sidestep the real LLM constructor (which
    requires an API key) by patching ``__init__`` and stubbing
    ``self.generate`` on the instance."""

    def _make_bridge(self):
        with patch.object(LLMBridge, "__init__", lambda self: None):
            bridge = LLMBridge()
        captured = {}

        def fake_generate(system_prompt, user_prompt):
            captured["system_prompt"] = system_prompt
            captured["user_prompt"] = user_prompt
            return {}

        bridge.generate = fake_generate
        return bridge, captured

    def test_excerpt_embedded_in_user_prompt_when_supplied(self):
        bridge, captured = self._make_bridge()
        block = format_plugin_source_excerpt_block(_MonotoneCfg)
        assert block, "pre-condition: block helper should emit non-empty text"

        bridge.plan(
            memory_history=[],
            plugin_source_excerpt=block,
        )
        user_prompt = captured["user_prompt"]
        # The pinned heading appears.
        assert "## PLUGIN CONFIG SCHEMA" in user_prompt
        # The validator body from the config class is inside the rendered prompt.
        assert "check_monotone" in user_prompt
        assert "nondecreasing" in user_prompt

    def test_section_omitted_when_excerpt_empty(self):
        bridge, captured = self._make_bridge()
        bridge.plan(memory_history=[], plugin_source_excerpt="")
        assert "## PLUGIN CONFIG SCHEMA" not in captured["user_prompt"]

    def test_excerpt_rendered_before_checklist(self):
        """Adjacency matters: the raw validator body must appear before the
        tried-values checklist so the planner reasons about both at the same
        moment (rule → values, not values → then rule)."""
        bridge, captured = self._make_bridge()
        block = format_plugin_source_excerpt_block(_MonotoneCfg)
        checklist = "### EXPLORATION CHECKLIST\n- sentinel_checklist_marker"

        bridge.plan(
            memory_history=[],
            plugin_source_excerpt=block,
            exploration_checklist=checklist,
        )
        user_prompt = captured["user_prompt"]
        i_schema = user_prompt.find("## PLUGIN CONFIG SCHEMA")
        i_checklist = user_prompt.find("sentinel_checklist_marker")
        assert i_schema != -1 and i_checklist != -1
        assert i_schema < i_checklist
