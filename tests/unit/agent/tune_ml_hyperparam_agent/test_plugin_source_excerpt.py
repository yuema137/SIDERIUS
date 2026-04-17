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
from pydantic import BaseModel, Field, model_validator, field_validator

from agent.prompts import (
    _PLUGIN_SOURCE_EXCERPT_MAX_CHARS,
    _extract_config_class_source,
    format_plugin_source_excerpt_block,
)


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
