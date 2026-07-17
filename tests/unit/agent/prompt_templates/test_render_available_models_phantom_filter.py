"""
Change 2 verification — ``render_available_models`` filters out entries
whose plugin has not actually loaded into ``MODEL_REGISTRY``.

Historically the ``## Available custom models`` prompt block advertised
every row in ``_capability_index.json``, including phantoms written by
the pre-fix implementor before validation. The proposer would then
propose Branch B against a phantom, the schema validator would reject
it, and the retry loop would eventually exhaust — a slow, wasteful
failure. This filter cuts phantoms at the prompt layer so the LLM never
sees them.

The filter is a lazy import of ``ml_models.models_sandbox.MODEL_REGISTRY``
with an "empty registry means no filter" fallback so existing render-
shape tests using a stub registry keep working.
"""

from __future__ import annotations

from unittest.mock import patch

from agent.prompt_templates.proposal import (
    _MODEL_REGISTRY_EMPTY_FALLBACK,
    render_available_models,
)


class _StubMeta:
    def __init__(self, name, capability_type="model"):
        self.name = name
        self.capability_type = capability_type
        self.description = f"desc for {name}"
        self.mathematical_definition = f"y = f_{name}(x)"
        self.created_at = "2026-06-25T00:00:00+00:00"
        self.source_iteration = "iter_001"


class _StubRegistry:
    def __init__(self, metas):
        self._metas = list(metas)

    def list(self, capability_type=None):
        if capability_type is None:
            return list(self._metas)
        return [m for m in self._metas if m.capability_type == capability_type]


class TestPhantomModelNotShownInAvailableBlock:
    """The Change 2 property: names in the index but not in
    ``MODEL_REGISTRY`` do not appear in the rendered block."""

    def test_phantom_filtered_when_registry_partially_populated(self):
        registry = _StubRegistry(
            [
                _StubMeta("real_model"),
                _StubMeta("gated_dilated_tcn"),  # v16 iter_015 phantom
            ]
        )
        with patch(
            "ml_models.models_sandbox.MODEL_REGISTRY",
            new={"real_model": object()},  # phantom absent
        ):
            block = render_available_models(registry)
        assert "### `real_model`" in block
        assert "gated_dilated_tcn" not in block

    def test_all_phantoms_renders_empty_fallback(self):
        """If every indexed model is a phantom, the block collapses to
        the documented 'no models registered yet' fallback."""
        registry = _StubRegistry(
            [
                _StubMeta("phantom_a"),
                _StubMeta("phantom_b"),
            ]
        )
        with patch("ml_models.models_sandbox.MODEL_REGISTRY", new={"unrelated": object()}):
            block = render_available_models(registry)
        assert block == _MODEL_REGISTRY_EMPTY_FALLBACK

    def test_all_live_renders_all(self):
        """No phantoms — everything in the index is loadable and appears."""
        registry = _StubRegistry(
            [
                _StubMeta("wavenet_baseline_v16"),
                _StubMeta("mamba_v1"),
            ]
        )
        with patch(
            "ml_models.models_sandbox.MODEL_REGISTRY",
            new={"wavenet_baseline_v16": object(), "mamba_v1": object()},
        ):
            block = render_available_models(registry)
        assert "### `wavenet_baseline_v16`" in block
        assert "### `mamba_v1`" in block

    def test_empty_registry_disables_filter_for_back_compat(self):
        """When ``MODEL_REGISTRY`` is empty (fresh workspace / stubbed-out
        test), the filter is a no-op so legacy render-shape tests that
        never populate ``MODEL_REGISTRY`` keep working."""
        registry = _StubRegistry([_StubMeta("legacy_shape_test_model")])
        with patch("ml_models.models_sandbox.MODEL_REGISTRY", new={}):
            block = render_available_models(registry)
        assert "### `legacy_shape_test_model`" in block

    def test_loss_entries_are_not_touched_by_model_filter(self):
        """Filter only applies to ``capability_type='model'``. A loss
        entry with a name that happens to match a phantom is unaffected
        by the model filter (the block only lists models anyway)."""
        registry = _StubRegistry(
            [
                _StubMeta("real_model", capability_type="model"),
                _StubMeta("real_model", capability_type="loss"),
            ]
        )
        with patch(
            "ml_models.models_sandbox.MODEL_REGISTRY",
            new={"real_model": object()},
        ):
            block = render_available_models(registry)
        assert "### `real_model`" in block
