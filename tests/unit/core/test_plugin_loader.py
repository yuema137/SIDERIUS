"""
Tests for core/plugin_loader.py

Verifies that agent-generated plugin models are correctly discovered, registered,
and callable in the same way as core models.

All tests use a temporary plugin written to a tmp_path directory — no real
agent_generated/ files are created or modified.
"""
import os
import textwrap
import importlib
import pytest
import torch

from core.plugin_loader import extend_registries, _load_plugin


# ---------------------------------------------------------------------------
# Shared plugin source used across tests
# ---------------------------------------------------------------------------

VALID_PLUGIN_SRC = textwrap.dedent("""\
    import torch
    import torch.nn as nn
    from pydantic import BaseModel, Field

    PLUGIN_MODEL_TYPE = "test_plugin_model"

    class TestPluginConfig(BaseModel):
        model_type: str = "test_plugin_model"
        segmentation_size: int = Field(default=1000, ge=100)
        batch_size: int = 1
        hidden: int = Field(default=32, ge=8)

    class TestPluginModel(nn.Module):
        def __init__(self, config):
            super().__init__()
            self.proj = nn.Linear(config.segmentation_size, config.segmentation_size)

        def forward(self, x):
            # Contract: [B, T] int → [B, 256, T] float
            out = self.proj(x.float())           # [B, T]
            return out.unsqueeze(1).expand(-1, 256, -1)  # [B, 256, T]

    PLUGIN_CONFIG_CLASS = TestPluginConfig
    PLUGIN_MODEL_CLASS  = TestPluginModel
""")


@pytest.fixture
def plugin_file(tmp_path):
    """Write the valid plugin source to a temp directory and return its path."""
    path = tmp_path / "test_plugin_model.py"
    path.write_text(VALID_PLUGIN_SRC)
    return str(path)


# ---------------------------------------------------------------------------
# _load_plugin
# ---------------------------------------------------------------------------

class TestLoadPlugin:

    def test_valid_plugin_returns_dict(self, plugin_file):
        result = _load_plugin(plugin_file)
        assert result is not None
        assert result["model_type"] == "test_plugin_model"
        assert result["config_class"] is not None
        assert result["model_class"] is not None

    def test_missing_model_type_returns_none(self, tmp_path):
        src = textwrap.dedent("""\
            import torch.nn as nn
            from pydantic import BaseModel
            class Cfg(BaseModel): pass
            class Mdl(nn.Module):
                def __init__(self, c): super().__init__()
                def forward(self, x): return x
            PLUGIN_CONFIG_CLASS = Cfg
            PLUGIN_MODEL_CLASS  = Mdl
        """)
        p = tmp_path / "bad.py"
        p.write_text(src)
        assert _load_plugin(str(p)) is None

    def test_missing_config_class_returns_none(self, tmp_path):
        src = textwrap.dedent("""\
            import torch.nn as nn
            PLUGIN_MODEL_TYPE = "x"
            class Mdl(nn.Module):
                def __init__(self, c): super().__init__()
                def forward(self, x): return x
            PLUGIN_MODEL_CLASS = Mdl
        """)
        p = tmp_path / "bad2.py"
        p.write_text(src)
        assert _load_plugin(str(p)) is None

    def test_syntax_error_returns_none(self, tmp_path):
        p = tmp_path / "broken.py"
        p.write_text("def (: pass\n")
        assert _load_plugin(str(p)) is None


# ---------------------------------------------------------------------------
# extend_registries
# ---------------------------------------------------------------------------

class TestExtendRegistries:

    def test_plugin_added_to_both_registries(self, tmp_path, plugin_file):
        # Rename so it lives inside tmp_path/models/
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        dst = models_dir / "test_plugin_model.py"
        dst.write_text(VALID_PLUGIN_SRC)

        model_reg  = {}
        config_reg = {}

        # Patch the loader's AGENT_GENERATED_DIR to point at our tmp models dir
        import core.plugin_loader as pl
        original_dir = pl.AGENT_GENERATED_DIR
        pl.AGENT_GENERATED_DIR = str(models_dir)
        try:
            loaded = extend_registries(model_reg, config_reg)
        finally:
            pl.AGENT_GENERATED_DIR = original_dir

        assert "test_plugin_model" in loaded
        assert "test_plugin_model" in model_reg
        assert "test_plugin_model" in config_reg

    def test_underscore_files_are_skipped(self, tmp_path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "__init__.py").write_text("")
        (models_dir / "_private.py").write_text(VALID_PLUGIN_SRC)

        model_reg  = {}
        config_reg = {}
        import core.plugin_loader as pl
        original_dir = pl.AGENT_GENERATED_DIR
        pl.AGENT_GENERATED_DIR = str(models_dir)
        try:
            loaded = extend_registries(model_reg, config_reg)
        finally:
            pl.AGENT_GENERATED_DIR = original_dir

        assert loaded == []

    def test_missing_directory_returns_empty(self, tmp_path):
        model_reg  = {}
        config_reg = {}
        import core.plugin_loader as pl
        original_dir = pl.AGENT_GENERATED_DIR
        pl.AGENT_GENERATED_DIR = str(tmp_path / "nonexistent")
        try:
            loaded = extend_registries(model_reg, config_reg)
        finally:
            pl.AGENT_GENERATED_DIR = original_dir

        assert loaded == []
        assert model_reg == {}


# ---------------------------------------------------------------------------
# End-to-end: plugin model is callable like a core model
# ---------------------------------------------------------------------------

class TestPluginModelCallable:

    @pytest.fixture
    def loaded_plugin(self, tmp_path):
        """Load the valid plugin and return (model_class, config_class)."""
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "test_plugin_model.py").write_text(VALID_PLUGIN_SRC)

        model_reg  = {}
        config_reg = {}
        import core.plugin_loader as pl
        original_dir = pl.AGENT_GENERATED_DIR
        pl.AGENT_GENERATED_DIR = str(models_dir)
        try:
            extend_registries(model_reg, config_reg)
        finally:
            pl.AGENT_GENERATED_DIR = original_dir

        return model_reg["test_plugin_model"], config_reg["test_plugin_model"]

    def test_config_instantiates(self, loaded_plugin):
        _, ConfigClass = loaded_plugin
        cfg = ConfigClass(segmentation_size=1000)
        assert cfg.segmentation_size == 1000

    def test_model_instantiates(self, loaded_plugin):
        ModelClass, ConfigClass = loaded_plugin
        cfg = ConfigClass(segmentation_size=1000)
        model = ModelClass(cfg)
        assert isinstance(model, torch.nn.Module)

    def test_forward_output_shape_matches_core_contract(self, loaded_plugin):
        """Plugin forward must return [B, 256, T] — same contract as core models."""
        ModelClass, ConfigClass = loaded_plugin
        seg_size = 1000
        batch    = 2
        cfg   = ConfigClass(segmentation_size=seg_size)
        model = ModelClass(cfg)
        model.eval()
        x   = torch.randint(0, 256, (batch, seg_size))
        out = model(x)
        assert out.shape == (batch, 256, seg_size), (
            f"Expected ({batch}, 256, {seg_size}), got {tuple(out.shape)}"
        )

    def test_forward_output_is_float(self, loaded_plugin):
        ModelClass, ConfigClass = loaded_plugin
        cfg = ConfigClass(segmentation_size=500)
        model = ModelClass(cfg)
        x   = torch.randint(0, 256, (1, 500))
        out = model(x)
        assert out.dtype == torch.float32

    def test_forward_no_nan(self, loaded_plugin):
        ModelClass, ConfigClass = loaded_plugin
        cfg = ConfigClass(segmentation_size=500)
        model = ModelClass(cfg)
        x   = torch.randint(0, 256, (1, 500))
        out = model(x)
        assert not torch.isnan(out).any()
