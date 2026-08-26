"""
Tests for ml_models/plugin_loader.py

Verifies that agent-generated plugin models are correctly discovered, registered,
and callable in the same way as core models.

All tests use a temporary plugin written to a tmp_path directory — no real
agent_generated/ files are created or modified.
"""

import importlib
import os
import subprocess
import sys
import textwrap

import pytest
import torch

from ml_models.plugin_loader import (
    _PLUGIN_DIRS_ENV_VAR,
    _load_plugin,
    _resolve_plugin_dirs,
    extend_registries,
)

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

        model_reg = {}
        config_reg = {}

        # Patch the loader's AGENT_GENERATED_DIR to point at our tmp models dir
        import ml_models.plugin_loader as pl

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

        model_reg = {}
        config_reg = {}
        import ml_models.plugin_loader as pl

        original_dir = pl.AGENT_GENERATED_DIR
        pl.AGENT_GENERATED_DIR = str(models_dir)
        try:
            loaded = extend_registries(model_reg, config_reg)
        finally:
            pl.AGENT_GENERATED_DIR = original_dir

        assert loaded == []

    def test_missing_directory_returns_empty(self, tmp_path):
        model_reg = {}
        config_reg = {}
        import ml_models.plugin_loader as pl

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

        model_reg = {}
        config_reg = {}
        import ml_models.plugin_loader as pl

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
        batch = 2
        cfg = ConfigClass(segmentation_size=seg_size)
        model = ModelClass(cfg)
        model.eval()
        x = torch.randint(0, 256, (batch, seg_size))
        out = model(x)
        assert out.shape == (batch, 256, seg_size), (
            f"Expected ({batch}, 256, {seg_size}), got {tuple(out.shape)}"
        )

    def test_forward_output_is_float(self, loaded_plugin):
        ModelClass, ConfigClass = loaded_plugin
        cfg = ConfigClass(segmentation_size=500)
        model = ModelClass(cfg)
        x = torch.randint(0, 256, (1, 500))
        out = model(x)
        assert out.dtype == torch.float32

    def test_forward_no_nan(self, loaded_plugin):
        ModelClass, ConfigClass = loaded_plugin
        cfg = ConfigClass(segmentation_size=500)
        model = ModelClass(cfg)
        x = torch.randint(0, 256, (1, 500))
        out = model(x)
        assert not torch.isnan(out).any()


# ---------------------------------------------------------------------------
# _resolve_plugin_dirs — env var precedence and parsing
# ---------------------------------------------------------------------------


class TestResolvePluginDirs:
    """Phase 1 of docs/run_scoped_plugins.md — env var drives the scan list,
    with fallback to the global library when unset. These tests pin down the
    parsing contract so no caller can regress to the old single-dir scan.

    arXiv P1: the no-env fallback is the resolved generated-library models
    dir followed by the legacy checkout AGENT_GENERATED_DIR (read-only
    compatibility). Defect the two fallback tests catch: dropping either
    member — losing the resolved dir orphans every post-P1 promotion in
    env-less processes; losing the legacy dir orphans every pre-migration
    checkout library."""

    def test_env_unset_falls_back_to_library_dirs(self, tmp_path, monkeypatch):
        monkeypatch.delenv(_PLUGIN_DIRS_ENV_VAR, raising=False)
        monkeypatch.setenv("SIDERIUS_GENERATED_LIBRARY_DIR", str(tmp_path / "lib"))
        import ml_models.plugin_loader as pl

        assert _resolve_plugin_dirs() == [
            str(tmp_path / "lib" / "models"),
            pl.AGENT_GENERATED_DIR,
        ]

    def test_empty_env_falls_back_to_library_dirs(self, tmp_path, monkeypatch):
        """Empty and whitespace-only env var must behave identically to
        unset — otherwise a shell that exports the var without a value
        would silently disable plugin loading."""
        monkeypatch.setenv("SIDERIUS_GENERATED_LIBRARY_DIR", str(tmp_path / "lib"))
        expected = [str(tmp_path / "lib" / "models")]
        import ml_models.plugin_loader as pl

        expected.append(pl.AGENT_GENERATED_DIR)

        monkeypatch.setenv(_PLUGIN_DIRS_ENV_VAR, "")
        assert _resolve_plugin_dirs() == expected

        monkeypatch.setenv(_PLUGIN_DIRS_ENV_VAR, "   ")
        assert _resolve_plugin_dirs() == expected

    def test_single_dir(self, monkeypatch):
        monkeypatch.setenv(_PLUGIN_DIRS_ENV_VAR, "/tmp/dir_a")
        assert _resolve_plugin_dirs() == ["/tmp/dir_a"]

    def test_multiple_dirs_preserve_order(self, monkeypatch):
        """Order matters because the shadow-warning semantics depend on it
        (later directory wins when two plugins share a model_type)."""
        monkeypatch.setenv(
            _PLUGIN_DIRS_ENV_VAR,
            os.pathsep.join(["/tmp/dir_a", "/tmp/dir_b", "/tmp/dir_c"]),
        )
        assert _resolve_plugin_dirs() == ["/tmp/dir_a", "/tmp/dir_b", "/tmp/dir_c"]

    def test_empty_entries_filtered(self, monkeypatch):
        """Leading/trailing/duplicate separators produce empty segments in
        shell-composed path vars. Must be dropped, not passed through as
        empty strings (which would later crash os.path.isdir)."""
        sep = os.pathsep
        monkeypatch.setenv(
            _PLUGIN_DIRS_ENV_VAR,
            f"{sep}/tmp/dir_a{sep}{sep}/tmp/dir_b{sep}",
        )
        assert _resolve_plugin_dirs() == ["/tmp/dir_a", "/tmp/dir_b"]


# ---------------------------------------------------------------------------
# extend_registries — multi-directory scanning (Phase 1)
# ---------------------------------------------------------------------------


def _make_plugin_src(model_type: str) -> str:
    """Return VALID_PLUGIN_SRC rewritten for a different PLUGIN_MODEL_TYPE.

    Lets us fabricate two distinct plugins without duplicating the whole
    template. We substitute the literal "test_plugin_model" token — the
    class names stay the same (harmless for these tests) but the registered
    model_type differs, so both plugins coexist in the registry."""
    return VALID_PLUGIN_SRC.replace("test_plugin_model", model_type)


class TestExtendRegistriesMultiDir:
    def test_env_var_overrides_legacy_dir(self, tmp_path, monkeypatch):
        """When SIDERIUS_PLUGIN_DIRS is set, the loader must scan ONLY that
        dir — not AGENT_GENERATED_DIR. We prove this by pointing
        AGENT_GENERATED_DIR at a directory holding a plugin that must NOT
        appear in the registry."""
        # Legacy global dir — should be ignored when env var is set.
        legacy_dir = tmp_path / "legacy"
        legacy_dir.mkdir()
        (legacy_dir / "legacy_plugin.py").write_text(_make_plugin_src("legacy_plugin"))

        # Run-scoped dir — the only one that should be scanned.
        run_dir = tmp_path / "run_models"
        run_dir.mkdir()
        (run_dir / "run_plugin.py").write_text(_make_plugin_src("run_plugin"))

        import ml_models.plugin_loader as pl

        monkeypatch.setattr(pl, "AGENT_GENERATED_DIR", str(legacy_dir))
        monkeypatch.setenv(_PLUGIN_DIRS_ENV_VAR, str(run_dir))

        model_reg, config_reg = {}, {}
        loaded = extend_registries(model_reg, config_reg)

        assert "run_plugin" in loaded
        assert "legacy_plugin" not in loaded, (
            "legacy dir must be skipped when SIDERIUS_PLUGIN_DIRS is set"
        )
        assert "run_plugin" in model_reg
        assert "legacy_plugin" not in model_reg

    def test_two_dirs_both_loaded(self, tmp_path, monkeypatch):
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        (dir_a / "plugin_a.py").write_text(_make_plugin_src("plugin_a"))
        (dir_b / "plugin_b.py").write_text(_make_plugin_src("plugin_b"))

        monkeypatch.setenv(
            _PLUGIN_DIRS_ENV_VAR,
            os.pathsep.join([str(dir_a), str(dir_b)]),
        )
        model_reg, config_reg = {}, {}
        loaded = extend_registries(model_reg, config_reg)

        assert "plugin_a" in loaded and "plugin_b" in loaded
        assert "plugin_a" in model_reg and "plugin_b" in model_reg

    def test_missing_legacy_dir_ok_when_env_set(self, tmp_path, monkeypatch):
        """AGENT_GENERATED_DIR not existing must not break the env-var path
        — this is the production scenario when the global dir has been
        cleaned out."""
        run_dir = tmp_path / "run_models"
        run_dir.mkdir()
        (run_dir / "run_plugin.py").write_text(_make_plugin_src("run_only_plugin"))

        import ml_models.plugin_loader as pl

        monkeypatch.setattr(pl, "AGENT_GENERATED_DIR", str(tmp_path / "does_not_exist"))
        monkeypatch.setenv(_PLUGIN_DIRS_ENV_VAR, str(run_dir))

        model_reg, config_reg = {}, {}
        loaded = extend_registries(model_reg, config_reg)

        assert loaded == ["run_only_plugin"]

    def test_missing_env_dir_silently_skipped(self, tmp_path, monkeypatch):
        """A non-existent dir in the env var must not raise — the loader
        should skip it. This matches the existing ``os.path.isdir`` guard
        for the legacy dir."""
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        (real_dir / "p.py").write_text(_make_plugin_src("real_plugin"))
        missing = tmp_path / "missing"

        monkeypatch.setenv(
            _PLUGIN_DIRS_ENV_VAR,
            os.pathsep.join([str(missing), str(real_dir)]),
        )
        model_reg, config_reg = {}, {}
        loaded = extend_registries(model_reg, config_reg)

        assert loaded == ["real_plugin"]


# ---------------------------------------------------------------------------
# Single-identity invariant — regression guard for the package refactor
# ---------------------------------------------------------------------------

_NO_BARE_IDENTITY_SCRIPT = textwrap.dedent("""\
    import sys
    import ml_models.plugin_loader as pl

    # Redirect the loader at the tmp plugin dir BEFORE triggering bootstrap.
    pl.AGENT_GENERATED_DIR = sys.argv[1]

    # Triggers the plugin bootstrap inside ml_models/models_sandbox.py.
    # After the package refactor, every internal import uses the qualified
    # form ``from ml_models.models_format_sandbox import ...``, so the bare
    # ``models_format_sandbox`` identity must never be created — even when
    # ``ml_models/`` is on PYTHONPATH (which historically triggered the
    # duplicate-module bug fixed on 2026-04-17 and structurally eliminated
    # by the 2026-05 package migration).
    import ml_models.models_sandbox  # noqa: F401

    bare = sys.modules.get('models_format_sandbox')
    pkg  = sys.modules.get('ml_models.models_format_sandbox')

    assert pkg is not None, "packaged ml_models.models_format_sandbox was not loaded"
    assert bare is None, (
        "package refactor invariant violated: the bare 'models_format_sandbox' "
        "module identity was created. Some flat 'from models_format_sandbox "
        "import ...' has been reintroduced; every import must use the "
        "qualified 'from ml_models.models_format_sandbox import ...' form. "
        f"sys.modules['models_format_sandbox'] = {bare!r}"
    )

    assert "test_plugin_model" in pkg.PLUGIN_CONFIG_REGISTRY, (
        "plugin missing from packaged registry: "
        + str(list(pkg.PLUGIN_CONFIG_REGISTRY.keys()))
    )
    cls = pkg.get_config_class("test_plugin_model")
    assert cls is not None, (
        "pkg.get_config_class('test_plugin_model') returned None — the "
        "plugin bootstrap failed to populate the canonical registry"
    )

    print("OK")
""")


class TestNoBareModuleIdentity:
    """Regression guard for the 2026-05 package refactor invariant.

    After the migration to a fully-installable setuptools package, every
    internal import resolves through the qualified ``ml_models.*`` path.
    The bare ``models_format_sandbox`` / ``models_sandbox`` /
    ``loss_models_sandbox`` module identities — which previously coexisted
    with their packaged counterparts when ``ml_models/`` was on sys.path
    and produced the duplicate-module bug fixed on 2026-04-17 — must no
    longer be created at all. This guard freezes that invariant.

    Runs in a subprocess with a composite PYTHONPATH that puts BOTH the
    project root and ``ml_models/`` on the search path. Pre-refactor this
    setup loaded the bare identity; post-refactor it must not, because no
    code in the import chain references the bare names anymore.
    """

    def test_bare_module_identity_never_created(self, tmp_path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "test_plugin_model.py").write_text(VALID_PLUGIN_SRC)

        import ml_models.plugin_loader as pl

        ml_models_dir = os.path.dirname(os.path.abspath(pl.__file__))
        project_root = os.path.dirname(ml_models_dir)

        # Composite PYTHONPATH that historically triggered the dual-identity
        # bug. The invariant is that it no longer does.
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join([project_root, ml_models_dir])

        result = subprocess.run(
            [sys.executable, "-c", _NO_BARE_IDENTITY_SCRIPT, str(models_dir)],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"subprocess failed (returncode={result.returncode})\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
        assert "OK" in result.stdout, f"missing OK marker; stdout={result.stdout!r}"
