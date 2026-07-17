"""
Change 3 verification — startup cleanup of phantom registry entries.

At workflow startup the global ``_capability_index.json`` can carry
entries whose ``file_path`` is stale (workspace cleaned, pytest tmp dir
garbage collected, or the entry was written pre-validation and the
validator later failed). The v16 iter_015 ``gated_dilated_tcn`` failure
is the reproducer: the global index still holds a
``/tmp/pytest-of-...`` file_path that no longer exists.

``_cleanup_stale_registry_entries`` sweeps the index once at startup and
removes every entry whose ``file_path`` fails ``os.path.isfile``. This
test file pins:

1. Phantom entries (file_path missing) are removed.
2. Real entries (file_path resolves) are kept.
3. A clean index is a no-op — returns ``(0, [])``.
4. Both model and loss surfaces are swept (the helper is capability-
   type-agnostic).
"""

from __future__ import annotations

import json

from agent_generated._registry import CapabilityMetadata, CapabilityRegistry
from workflows.model_exploration import _cleanup_stale_registry_entries


def _make_registry(tmp_path, entries):
    idx = tmp_path / "_capability_index.json"
    idx.write_text(json.dumps([e.model_dump() for e in entries]))
    return CapabilityRegistry(index_path=str(idx)), idx


class TestStaleRegistryCleanup:
    def test_removes_entry_with_missing_file_path(self, tmp_path):
        """The v16 ``gated_dilated_tcn`` reproducer."""
        phantom = CapabilityMetadata(
            name="gated_dilated_tcn",
            capability_type="model",
            file_path="/tmp/pytest-of-yuema137/pytest-138/test_impl/models/gated_dilated_tcn.py",
            created_at="2026-06-30T00:00:00+00:00",
            source_iteration="iter_009",
            description="phantom",
            mathematical_definition="",
        )
        registry, idx = _make_registry(tmp_path, [phantom])
        assert len(registry.list()) == 1

        n_pruned, names = _cleanup_stale_registry_entries(registry)

        assert n_pruned == 1
        assert names == ["gated_dilated_tcn (model)"]
        assert registry.list() == []
        # On-disk sync check — the change must be persisted, not held in memory.
        with open(idx) as f:
            assert json.load(f) == []

    def test_keeps_entry_with_existing_file_path(self, tmp_path):
        """Real entries are untouched."""
        plugin_path = tmp_path / "real_plugin.py"
        plugin_path.write_text("PLUGIN_MODEL_TYPE = 'real'\n")
        real = CapabilityMetadata(
            name="real_model",
            capability_type="model",
            file_path=str(plugin_path),
            created_at="2026-06-30T00:00:00+00:00",
            source_iteration="iter_002",
            description="real",
            mathematical_definition="",
        )
        registry, _ = _make_registry(tmp_path, [real])

        n_pruned, names = _cleanup_stale_registry_entries(registry)

        assert n_pruned == 0
        assert names == []
        assert len(registry.list()) == 1
        assert registry.list()[0].name == "real_model"

    def test_mixed_registry_prunes_only_phantoms(self, tmp_path):
        """Real + phantom entries mixed — only phantoms are removed."""
        real_path = tmp_path / "real_plugin.py"
        real_path.write_text("PLUGIN_MODEL_TYPE = 'real'\n")
        real = CapabilityMetadata(
            name="real_model",
            capability_type="model",
            file_path=str(real_path),
            created_at="2026-06-30T00:00:00+00:00",
            source_iteration="iter_002",
            description="real",
            mathematical_definition="",
        )
        phantom = CapabilityMetadata(
            name="phantom_model",
            capability_type="model",
            file_path="/nonexistent/phantom.py",
            created_at="2026-06-30T00:00:00+00:00",
            source_iteration="iter_009",
            description="phantom",
            mathematical_definition="",
        )
        registry, _ = _make_registry(tmp_path, [real, phantom])

        n_pruned, names = _cleanup_stale_registry_entries(registry)

        assert n_pruned == 1
        assert names == ["phantom_model (model)"]
        remaining = [m.name for m in registry.list()]
        assert remaining == ["real_model"]

    def test_clean_registry_is_noop(self, tmp_path):
        """No phantoms, no writes, no complaints."""
        registry, _ = _make_registry(tmp_path, [])

        n_pruned, names = _cleanup_stale_registry_entries(registry)

        assert n_pruned == 0
        assert names == []

    def test_sweeps_both_model_and_loss_surfaces(self, tmp_path):
        """The helper is capability-type-agnostic — a stale loss entry is
        also pruned. Same failure mode, different plugin surface."""
        phantom_model = CapabilityMetadata(
            name="phantom_model",
            capability_type="model",
            file_path="/nonexistent/phantom_model.py",
            created_at="2026-06-30T00:00:00+00:00",
            source_iteration="iter_009",
            description="",
            mathematical_definition="",
        )
        phantom_loss = CapabilityMetadata(
            name="phantom_loss",
            capability_type="loss",
            file_path="/nonexistent/phantom_loss.py",
            created_at="2026-06-30T00:00:00+00:00",
            source_iteration="iter_003",
            description="",
            mathematical_definition="",
        )
        registry, _ = _make_registry(tmp_path, [phantom_model, phantom_loss])

        n_pruned, names = _cleanup_stale_registry_entries(registry)

        assert n_pruned == 2
        assert "phantom_model (model)" in names
        assert "phantom_loss (loss)" in names
        assert registry.list() == []
