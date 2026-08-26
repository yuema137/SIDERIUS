"""
Unit tests for ``ml_models.plugin_loader.preload_global_models``.

Symmetric to ``ml_models.loss_models_sandbox.preload_global_losses``:
on workflow startup we want every previously-promoted model plugin
(in ``agent_generated/models/``) to be registered into the in-memory
``MODEL_REGISTRY`` / ``PLUGIN_CONFIG_REGISTRY`` so cross-process
Branch B reuse (e.g. chain resume after restart, parallel chains
hitting the same registry) works without needing
``SIDERIUS_PLUGIN_DIRS``.

This file covers criterion #5 of the V16 symmetric-model-registry plan
plus the back-compat no-op when ``AGENT_GENERATED_DIR`` does not exist.
"""

from __future__ import annotations

import textwrap

_VALID_MODEL_PLUGIN_SRC_TEMPLATE = textwrap.dedent("""\
    import torch
    import torch.nn as nn
    from pydantic import BaseModel, Field

    PLUGIN_MODEL_TYPE = "{model_type}"

    class _Cfg(BaseModel):
        model_type: str = "{model_type}"
        segmentation_size: int = Field(default=1000, ge=100)
        batch_size: int = 1

    class _Mdl(nn.Module):
        def __init__(self, config):
            super().__init__()
            self.proj = nn.Linear(config.segmentation_size, config.segmentation_size)

        def forward(self, x):
            out = self.proj(x.float())
            return out.unsqueeze(1).expand(-1, 256, -1)

    PLUGIN_CONFIG_CLASS = _Cfg
    PLUGIN_MODEL_CLASS  = _Mdl
""")


def _write_plugin(tmp_dir, model_type: str) -> None:
    (tmp_dir / f"{model_type}.py").write_text(
        _VALID_MODEL_PLUGIN_SRC_TEMPLATE.format(model_type=model_type)
    )


class TestPreloadGlobalModels:
    def test_preload_loads_all_plugins(self, tmp_path, monkeypatch):
        """preload_global_models scans the resolved library models dir
        (pinned to a tmp root) and registers every valid .py.

        The model-side preload mirrors preload_global_losses: skip files
        prefixed with ``_``, return the loaded model_type list, and
        update all three registries (MODEL_REGISTRY, PLUGIN_CONFIG_REGISTRY,
        PLUGIN_OUTPUT_TYPE_REGISTRY)."""
        from ml_models import plugin_loader
        from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
        from ml_models.models_sandbox import MODEL_REGISTRY
        from ml_models.plugin_loader import (
            PLUGIN_OUTPUT_TYPE_REGISTRY,
            preload_global_models,
        )

        lib_models = tmp_path / "lib" / "models"
        lib_models.mkdir(parents=True)
        monkeypatch.setenv("SIDERIUS_GENERATED_LIBRARY_DIR", str(tmp_path / "lib"))
        monkeypatch.setattr(plugin_loader, "AGENT_GENERATED_DIR", str(tmp_path / "legacy_empty"))

        _write_plugin(lib_models, "preload_alpha_v16")
        _write_plugin(lib_models, "preload_beta_v16")
        (lib_models / "_template_model.py").write_text("# should be skipped\n")

        try:
            loaded = preload_global_models()
            assert sorted(loaded) == ["preload_alpha_v16", "preload_beta_v16"]
            assert "preload_alpha_v16" in MODEL_REGISTRY
            assert "preload_beta_v16" in MODEL_REGISTRY
            assert "preload_alpha_v16" in PLUGIN_CONFIG_REGISTRY
            assert "preload_beta_v16" in PLUGIN_CONFIG_REGISTRY
            assert PLUGIN_OUTPUT_TYPE_REGISTRY.get("preload_alpha_v16") == "classifier"
        finally:
            # Clean up — these tests share global module-level dicts with
            # the rest of the suite.
            for name in ("preload_alpha_v16", "preload_beta_v16"):
                MODEL_REGISTRY.pop(name, None)
                PLUGIN_CONFIG_REGISTRY.pop(name, None)
                PLUGIN_OUTPUT_TYPE_REGISTRY.pop(name, None)

    def test_preload_scans_legacy_checkout_and_library_shadows_same_basename(
        self, tmp_path, monkeypatch
    ):
        """arXiv P1 compatibility READ (matrix F): a model promoted into the
        LEGACY checkout dir before the migration still preloads; a
        same-basename file in the resolved library SHADOWS the legacy one
        entirely. Defect caught: dropping the legacy scan (pre-migration
        promotions vanish from Branch-B reuse) or registering the legacy
        copy after the library one (stale legacy bytes would win
        register_model_in_memory's most-recent rule)."""
        from ml_models import plugin_loader
        from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
        from ml_models.models_sandbox import MODEL_REGISTRY
        from ml_models.plugin_loader import (
            PLUGIN_OUTPUT_TYPE_REGISTRY,
            preload_global_models,
        )

        lib_models = tmp_path / "lib" / "models"
        lib_models.mkdir(parents=True)
        legacy = tmp_path / "legacy_models"
        legacy.mkdir()
        monkeypatch.setenv("SIDERIUS_GENERATED_LIBRARY_DIR", str(tmp_path / "lib"))
        monkeypatch.setattr(plugin_loader, "AGENT_GENERATED_DIR", str(legacy))

        # Legacy-only model: must preload through the compatibility scan.
        _write_plugin(legacy, "preload_alpha_v16")
        # Same-basename pair: the legacy copy is a loadable decoy declaring a
        # DIFFERENT output contract, so whichever registration wins is provable.
        _write_plugin(lib_models, "preload_beta_v16")
        (legacy / "preload_beta_v16.py").write_text(
            _VALID_MODEL_PLUGIN_SRC_TEMPLATE.format(model_type="preload_beta_v16")
            + '\nPLUGIN_OUTPUT_TYPE = "regressor"\n'
        )

        try:
            loaded = preload_global_models()
            assert sorted(loaded) == ["preload_alpha_v16", "preload_beta_v16"]
            # The library copy (legacy-omitted contract -> "classifier") won;
            # the legacy decoy ("regressor") was shadowed by basename.
            assert PLUGIN_OUTPUT_TYPE_REGISTRY.get("preload_beta_v16") == "classifier"
        finally:
            for name in ("preload_alpha_v16", "preload_beta_v16"):
                MODEL_REGISTRY.pop(name, None)
                PLUGIN_CONFIG_REGISTRY.pop(name, None)
                PLUGIN_OUTPUT_TYPE_REGISTRY.pop(name, None)

    def test_preload_returns_empty_when_dirs_missing(self, tmp_path, monkeypatch):
        """preload_global_models is safe when neither library location
        exists — first-run / fresh-host case."""
        from ml_models import plugin_loader
        from ml_models.plugin_loader import preload_global_models

        monkeypatch.setenv("SIDERIUS_GENERATED_LIBRARY_DIR", str(tmp_path / "no_lib"))
        monkeypatch.setattr(plugin_loader, "AGENT_GENERATED_DIR", str(tmp_path / "does_not_exist"))
        assert preload_global_models() == []
