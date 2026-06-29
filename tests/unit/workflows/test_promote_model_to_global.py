"""
Unit tests for ``workflows.model_exploration._promote_model_to_global``.

Symmetric to L6c ``_promote_loss_to_global``: after the implementor
writes a freshly-generated model plugin into the workspace-scoped
``plugin_dir`` and registers it in the capability index, the workflow
copies the .py into the global ``agent_generated/models/`` and rewrites
the registry entry's ``file_path`` so future iters / parallel chains
see the model via the global path.

Covers criterion #8 of the V16 symmetric-model-registry plan: idempotency,
Branch-B no-op (source already at global path), missing-source no-op,
and SHA256 content-hash dedup.
"""

from __future__ import annotations

import os
import textwrap

import pytest

_MODEL_PLUGIN_SRC_ALPHA = textwrap.dedent("""\
    import torch
    import torch.nn as nn
    from pydantic import BaseModel, Field

    PLUGIN_MODEL_TYPE = "promo_model_alpha"

    class _Cfg(BaseModel):
        model_type: str = "promo_model_alpha"
        segmentation_size: int = Field(default=1000, ge=100)
        batch_size: int = 1

    class _Mdl(nn.Module):
        def __init__(self, config):
            super().__init__()
        def forward(self, x):
            return x.float().unsqueeze(1).expand(-1, 256, -1)

    PLUGIN_CONFIG_CLASS = _Cfg
    PLUGIN_MODEL_CLASS  = _Mdl
""")


class _FakeImplOutput:
    """Minimal duck-typed ``ImplementorOutput`` stand-in. The helper only
    reads ``model_file_path``, ``model_type``, and ``description_file_path``
    via ``getattr``, so a plain object suffices and avoids dragging in the
    full Pydantic schema (and its many required fields)."""

    def __init__(self, *, model_type: str, model_file_path: str, description_file_path: str = ""):
        self.model_type = model_type
        self.model_file_path = model_file_path
        self.description_file_path = description_file_path


@pytest.fixture
def global_models_dir(tmp_path, monkeypatch):
    """Redirect ``AGENT_GENERATED_DIR`` (the model loader's global dir)
    to a tmp directory so these tests don't touch the canonical
    ``agent_generated/models/``."""
    from ml_models import plugin_loader

    target = tmp_path / "global_models"
    target.mkdir()
    monkeypatch.setattr(plugin_loader, "AGENT_GENERATED_DIR", str(target))
    return target


@pytest.fixture
def tmp_registry(tmp_path, monkeypatch):
    """Use a tmp capability-index for the duration of the test so
    promotion's ``registry.replace()`` doesn't pollute the real index."""
    from agent_generated import _registry as registry_module

    idx = tmp_path / "_capability_index.json"
    monkeypatch.setattr(registry_module, "_DEFAULT_INDEX_PATH", str(idx))
    return idx


def _register_pre_promotion(name, workspace_path, tmp_registry, math_def="x"):
    from agent_generated._registry import CapabilityMetadata, CapabilityRegistry

    registry = CapabilityRegistry()
    registry.register(
        CapabilityMetadata(
            name=name,
            capability_type="model",
            file_path=workspace_path,
            created_at="2026-06-25T00:00:00+00:00",
            source_iteration="iter_001",
            description="alpha test plugin",
            mathematical_definition=math_def,
        )
    )
    return registry


class TestPromoteModelToGlobal:
    def test_promotes_generated_plugin(self, tmp_path, global_models_dir, tmp_registry):
        """Happy path — source under workspace plugin_dir is copied to
        the global models dir and the registry entry's ``file_path`` is
        rewritten to the global path."""
        from workflows.model_exploration import _promote_model_to_global

        ws_plugin = tmp_path / "ws" / "plugins" / "promo_model_alpha.py"
        ws_plugin.parent.mkdir(parents=True)
        ws_plugin.write_text(_MODEL_PLUGIN_SRC_ALPHA)

        registry = _register_pre_promotion("promo_model_alpha", str(ws_plugin), tmp_registry)

        impl = _FakeImplOutput(
            model_type="promo_model_alpha",
            model_file_path=str(ws_plugin),
        )
        _promote_model_to_global(impl)

        global_dest = global_models_dir / "promo_model_alpha.py"
        assert global_dest.is_file()

        entries = registry.list(capability_type="model")
        assert len(entries) == 1
        assert os.path.abspath(entries[0].file_path) == os.path.abspath(str(global_dest))

    def test_idempotent_when_dest_exists(self, tmp_path, global_models_dir, tmp_registry, capsys):
        """Calling promote twice for the same model only writes once and
        the second call logs 'idempotent skip' (or 'already at global path')."""
        from workflows.model_exploration import _promote_model_to_global

        ws_plugin = tmp_path / "ws" / "plugins" / "promo_model_alpha.py"
        ws_plugin.parent.mkdir(parents=True)
        ws_plugin.write_text(_MODEL_PLUGIN_SRC_ALPHA)

        _register_pre_promotion("promo_model_alpha", str(ws_plugin), tmp_registry)
        impl = _FakeImplOutput(
            model_type="promo_model_alpha",
            model_file_path=str(ws_plugin),
        )
        _promote_model_to_global(impl)
        capsys.readouterr()  # drain first-call output
        _promote_model_to_global(impl)
        captured = capsys.readouterr().out.lower()
        assert "idempotent skip" in captured or "already at global path" in captured

    def test_branch_b_no_op_when_source_already_global(
        self, tmp_path, global_models_dir, tmp_registry
    ):
        """Branch B reuse path: the implementor's short-circuit returns
        ImplementorOutput.model_file_path = registry's global path. The
        promoter must detect this (dirname == MODELS_DIR) and no-op
        without re-copying or re-registering."""
        from workflows.model_exploration import _promote_model_to_global

        global_path = global_models_dir / "promo_model_alpha.py"
        global_path.write_text(_MODEL_PLUGIN_SRC_ALPHA)

        registry = _register_pre_promotion("promo_model_alpha", str(global_path), tmp_registry)
        original_mtime = global_path.stat().st_mtime

        impl = _FakeImplOutput(
            model_type="promo_model_alpha",
            model_file_path=str(global_path),
        )
        _promote_model_to_global(impl)

        # File untouched (mtime unchanged), registry untouched.
        assert global_path.stat().st_mtime == original_mtime
        entries = registry.list(capability_type="model")
        assert os.path.abspath(entries[0].file_path) == os.path.abspath(str(global_path))

    def test_no_op_when_model_file_missing(self, tmp_path, global_models_dir, tmp_registry):
        """Missing source file (e.g. Branch A built-in path that never
        wrote a generated plugin) is a no-op — nothing copied, nothing
        raised."""
        from workflows.model_exploration import _promote_model_to_global

        impl = _FakeImplOutput(
            model_type="ghost",
            model_file_path=str(tmp_path / "nonexistent.py"),
        )
        _promote_model_to_global(impl)  # must not raise
        assert list(global_models_dir.iterdir()) == []

    def test_promote_skips_identical_content(
        self, tmp_path, global_models_dir, tmp_registry, capsys
    ):
        """SHA256 content-hash dedup: if a file with the same content
        already exists under a different name in the global dir, promotion
        skips with a warning naming the existing duplicate."""
        from workflows.model_exploration import _promote_model_to_global

        # Pre-seed the global library with the same content under a different filename.
        global_existing = global_models_dir / "promo_model_beta.py"
        global_existing.write_text(_MODEL_PLUGIN_SRC_ALPHA)

        ws_plugin = tmp_path / "ws" / "plugins" / "promo_model_alpha.py"
        ws_plugin.parent.mkdir(parents=True)
        ws_plugin.write_text(_MODEL_PLUGIN_SRC_ALPHA)
        _register_pre_promotion("promo_model_alpha", str(ws_plugin), tmp_registry)

        impl = _FakeImplOutput(
            model_type="promo_model_alpha",
            model_file_path=str(ws_plugin),
        )
        _promote_model_to_global(impl)
        captured = capsys.readouterr().out.lower()
        assert "identical content already exists" in captured
        assert "promo_model_beta" in captured
        # The new-name file MUST NOT have been copied.
        assert not (global_models_dir / "promo_model_alpha.py").exists()
