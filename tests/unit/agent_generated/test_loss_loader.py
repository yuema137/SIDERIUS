"""
Unit tests for ``ml_models.loss_plugin_loader`` — loss plugin discovery + load.

Coverage:
  * Stub template loads cleanly when copied (without ``_`` prefix) to ``losses/``
  * Missing each of the 3 required attrs → loader rejects with explicit message
  * ``_``-prefixed files are skipped (the template itself stays dormant)
  * ``sys.modules`` rebind allows ``inspect.getsource`` to resolve the file
  * ``SIDERIUS_LOSS_DIRS`` env var: when set to a dir with a valid loss plugin,
    loader finds it; when set to a dir with only model ``.py`` files (no
    loss attrs), loader skips cleanly without spurious errors
  * ``load_loss_plugin(name)`` convenience wrapper: finds plugin by name; returns
    None on miss

See ``docs/design/enable_loss_inventory.md`` § Commit L1.
"""

from __future__ import annotations

import inspect
import os
import shutil
import sys
from pathlib import Path

import pytest

from ml_models import loss_plugin_loader as _loss_loader
from ml_models.loss_plugin_loader import (
    _MODULE_NAME_PREFIX,
    _load_loss_plugin,
    _resolve_loss_dirs,
    load_loss_plugin,
)

# Source path to the stub template — copied (without the leading ``_``) into
# tmp_path/losses for tests that exercise the load path.
_STUB_TEMPLATE = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "generated_capabilities"
    / "stub_loss_template.py"
)


@pytest.fixture
def loss_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set up a fresh tmp loss directory and point ``SIDERIUS_LOSS_DIRS`` at it.

    Also clears any pre-existing ``siderius_loss_plugin_*`` entries from
    ``sys.modules`` so a previous test run's stub doesn't shadow this one.
    """
    d = tmp_path / "losses"
    d.mkdir()
    monkeypatch.setenv("SIDERIUS_LOSS_DIRS", str(d))
    for k in list(sys.modules):
        if k.startswith(_MODULE_NAME_PREFIX):
            sys.modules.pop(k, None)
    return d


def _copy_stub(dest_dir: Path, filename: str = "my_loss.py") -> Path:
    """Copy the stub template to ``dest_dir/filename`` (no ``_`` prefix so the
    loader picks it up)."""
    dest = dest_dir / filename
    shutil.copy2(_STUB_TEMPLATE, dest)
    return dest


# ---------------------------------------------------------------------------
# Stub loads cleanly
# ---------------------------------------------------------------------------


class TestStubLoads:
    def test_stub_template_loads_cleanly(self, loss_dir: Path):
        path = _copy_stub(loss_dir)
        plugin = _load_loss_plugin(str(path))
        assert plugin is not None
        assert plugin["loss_type"] == "stub_ce"
        # The config and loss class must be importable types.
        assert plugin["config_class"].__name__ == "StubCEConfig"
        assert plugin["loss_class"].__name__ == "StubCE"

    def test_loaded_classes_have_resolvable_source(self, loss_dir: Path):
        """sys.modules rebind allows inspect.getsource to find the file."""
        path = _copy_stub(loss_dir, "my_loss.py")
        plugin = _load_loss_plugin(str(path))
        assert plugin is not None
        # If the sys.modules rebind didn't happen, inspect.getsource raises
        # OSError because the class appears as a built-in.
        src = inspect.getsource(plugin["loss_class"])
        assert "class StubCE" in src
        assert "F.cross_entropy" in src


# ---------------------------------------------------------------------------
# Missing required attrs → rejected
# ---------------------------------------------------------------------------


class TestMissingAttrsRejected:
    @pytest.mark.parametrize(
        "missing_attr",
        ["PLUGIN_LOSS_TYPE", "PLUGIN_LOSS_CONFIG_CLASS", "PLUGIN_LOSS_CLASS"],
    )
    def test_missing_required_attr_returns_none(
        self, loss_dir: Path, missing_attr: str, capsys: pytest.CaptureFixture
    ):
        # Start from the stub and remove the named attribute.
        stub_src = _STUB_TEMPLATE.read_text(encoding="utf-8")
        # Replace the line that defines the missing attribute with a comment.
        broken = stub_src.replace(f"{missing_attr} = ", f"# REMOVED FOR TEST: {missing_attr} = ", 1)
        # Also have to handle the class-assignment lines for the two class
        # attrs (the assignment is via the class name, not the PLUGIN_* alias).
        if missing_attr == "PLUGIN_LOSS_CONFIG_CLASS":
            broken = broken.replace(
                "PLUGIN_LOSS_CONFIG_CLASS = StubCEConfig",
                "# REMOVED FOR TEST: PLUGIN_LOSS_CONFIG_CLASS",
            )
        elif missing_attr == "PLUGIN_LOSS_CLASS":
            broken = broken.replace(
                "PLUGIN_LOSS_CLASS = StubCE", "# REMOVED FOR TEST: PLUGIN_LOSS_CLASS"
            )
        elif missing_attr == "PLUGIN_LOSS_TYPE":
            broken = broken.replace(
                'PLUGIN_LOSS_TYPE = "stub_ce"', "# REMOVED FOR TEST: PLUGIN_LOSS_TYPE"
            )
        path = loss_dir / "broken_loss.py"
        path.write_text(broken, encoding="utf-8")

        plugin = _load_loss_plugin(str(path))
        assert plugin is None
        captured = capsys.readouterr()
        assert missing_attr in captured.out
        assert "Skipping" in captured.out

    def test_unloadable_python_returns_none(self, loss_dir: Path, capsys: pytest.CaptureFixture):
        path = loss_dir / "syntax_error.py"
        path.write_text("this is not valid python <<<", encoding="utf-8")
        plugin = _load_loss_plugin(str(path))
        assert plugin is None
        captured = capsys.readouterr()
        assert "Failed to load" in captured.out


# ---------------------------------------------------------------------------
# Underscore-prefixed files are skipped (load_loss_plugin scan path)
# ---------------------------------------------------------------------------


class TestUnderscorePrefixSkipped:
    def test_underscore_file_skipped_by_scan(self, loss_dir: Path):
        # Copy the stub with its original ``_``-prefixed name. The
        # convenience scanner ``load_loss_plugin`` should NOT find it.
        _copy_stub(loss_dir, "_stub_loss_template.py")
        # Even with a matching name, the underscore-prefix skip wins.
        result = load_loss_plugin("stub_ce")
        assert result is None

    def test_non_underscore_file_found_by_scan(self, loss_dir: Path):
        _copy_stub(loss_dir, "stub_ce.py")
        result = load_loss_plugin("stub_ce")
        assert result is not None
        assert result["loss_type"] == "stub_ce"


# ---------------------------------------------------------------------------
# load_loss_plugin: name lookup
# ---------------------------------------------------------------------------


class TestLoadLossPluginByName:
    def test_lookup_hit_returns_plugin(self, loss_dir: Path):
        _copy_stub(loss_dir, "stub_ce.py")
        result = load_loss_plugin("stub_ce")
        assert result is not None
        assert result["loss_class"].__name__ == "StubCE"

    def test_lookup_miss_returns_none(self, loss_dir: Path):
        _copy_stub(loss_dir, "stub_ce.py")
        # Plugin exists at "stub_ce" — looking up a different name returns None.
        assert load_loss_plugin("nonexistent_loss") is None

    def test_lookup_with_no_loss_dir_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        # Point env var at a directory that doesn't exist.
        monkeypatch.setenv("SIDERIUS_LOSS_DIRS", str(tmp_path / "nope"))
        assert load_loss_plugin("anything") is None


# ---------------------------------------------------------------------------
# SIDERIUS_LOSS_DIRS env var semantics
# ---------------------------------------------------------------------------


class TestEnvVarResolution:
    @pytest.fixture
    def library_losses(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
        """Pin the resolved generated library (arXiv P1) to a tmp root so the
        union assertions don't depend on this developer's ~/.siderius."""
        monkeypatch.setenv("SIDERIUS_GENERATED_LIBRARY_DIR", str(tmp_path / "lib"))
        return str(tmp_path / "lib" / "losses")

    def test_env_var_set_unions_with_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, library_losses: str
    ):
        """L6c — union mode; arXiv P1 adds the resolved library dir. Env-var
        dirs come FIRST, then the resolved generated-library losses dir, then
        the legacy checkout LOSSES_DIR LAST. Defect caught: any reordering —
        a workspace loss losing to a promoted one, or a legacy checkout loss
        shadowing the resolved-library copy of the same name (the walk is
        first-match-wins)."""
        target = tmp_path / "alt_losses"
        target.mkdir()
        monkeypatch.setenv("SIDERIUS_LOSS_DIRS", str(target))
        dirs = _resolve_loss_dirs()
        assert dirs == [str(target), library_losses, _loss_loader.LOSSES_DIR]

    def test_workspace_binding_excludes_checkout_fallback(self, tmp_path, monkeypatch):
        from core.generated_library import bind_generated_library_to_workspace

        env: dict[str, str] = {}
        bind_generated_library_to_workspace(str(tmp_path / "workspace"), environ=env)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        monkeypatch.delenv("SIDERIUS_LOSS_DIRS", raising=False)

        assert _resolve_loss_dirs() == [str(tmp_path / "workspace/generated_library/losses")]

    def test_env_var_unset_falls_back_to_library_dirs(
        self, monkeypatch: pytest.MonkeyPatch, library_losses: str
    ):
        """Defect caught: the no-env branch dropping either library member —
        losing the resolved dir breaks every post-P1 promotion read; losing
        the legacy dir breaks pre-migration checkouts (compatibility READ)."""
        monkeypatch.delenv("SIDERIUS_LOSS_DIRS", raising=False)
        dirs = _resolve_loss_dirs()
        assert dirs == [library_losses, _loss_loader.LOSSES_DIR]

    def test_env_var_empty_string_falls_back_to_library_dirs(
        self, monkeypatch: pytest.MonkeyPatch, library_losses: str
    ):
        monkeypatch.setenv("SIDERIUS_LOSS_DIRS", "")
        dirs = _resolve_loss_dirs()
        assert dirs == [library_losses, _loss_loader.LOSSES_DIR]

    def test_env_var_pathsep_separated_list_parses_correctly(
        self, monkeypatch: pytest.MonkeyPatch, library_losses: str
    ):
        """L6c union mode: env-var dirs (parsed) FIRST, library dirs LAST."""
        joined = os.pathsep.join(["/a", "/b", "/c"])
        monkeypatch.setenv("SIDERIUS_LOSS_DIRS", joined)
        assert _resolve_loss_dirs() == [
            "/a",
            "/b",
            "/c",
            library_losses,
            _loss_loader.LOSSES_DIR,
        ]

    def test_env_var_with_empty_entries_filters_them(
        self, monkeypatch: pytest.MonkeyPatch, library_losses: str
    ):
        """Shell-composed paths like ``:/a:/b:`` produce ["/a", "/b"] for the
        env portion, then the library dirs are appended (L6c union)."""
        monkeypatch.setenv("SIDERIUS_LOSS_DIRS", os.pathsep.join(["", "/a", "", "/b", ""]))
        assert _resolve_loss_dirs() == ["/a", "/b", library_losses, _loss_loader.LOSSES_DIR]

    def test_legacy_checkout_dir_is_scanned_last_and_still_resolves(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """arXiv P1 compatibility READ (matrix F): a loss present ONLY in the
        legacy checkout location must still resolve by name — and a same-named
        loss in the resolved library must win over it. Defect caught: dropping
        the legacy member (pre-migration promotions vanish) or scanning it
        before the resolved dir (stale legacy bytes shadow the current
        promotion)."""
        legacy = tmp_path / "legacy_losses"
        legacy.mkdir()
        monkeypatch.setattr(_loss_loader, "LOSSES_DIR", str(legacy))
        lib = tmp_path / "lib"
        monkeypatch.setenv("SIDERIUS_GENERATED_LIBRARY_DIR", str(lib))
        monkeypatch.delenv("SIDERIUS_LOSS_DIRS", raising=False)

        # Legacy-only loss resolves through the fallback member.
        _copy_stub(legacy, "stub_ce.py")
        result = load_loss_plugin("stub_ce")
        assert result is not None
        assert result["target_dtype"] == "long"

        # Same-named resolved-library copy wins (first-match-wins walk). The
        # library variant is distinguishable by its declared target dtype.
        lib_losses = lib / "losses"
        lib_losses.mkdir(parents=True)
        variant = (
            (legacy / "stub_ce.py")
            .read_text()
            .replace('PLUGIN_LOSS_TARGET_DTYPE = "long"', 'PLUGIN_LOSS_TARGET_DTYPE = "float"')
        )
        (lib_losses / "stub_ce.py").write_text(variant)
        result2 = load_loss_plugin("stub_ce")
        assert result2 is not None
        assert result2["target_dtype"] == "float"

    def test_loader_isolates_model_dir_misuse(self, loss_dir: Path, capsys: pytest.CaptureFixture):
        """When SIDERIUS_LOSS_DIRS points at a dir containing MODEL ``.py``
        files (not loss plugins), the loader skips them cleanly without
        treating their missing PLUGIN_LOSS_* attrs as catastrophic failures."""
        # Drop a fake model plugin (no PLUGIN_LOSS_* attrs).
        fake_model = loss_dir / "fake_model.py"
        fake_model.write_text(
            "PLUGIN_MODEL_TYPE = 'fake'\n"
            "import torch.nn as nn\n"
            "class FakeModel(nn.Module): pass\n"
            "PLUGIN_MODEL_CLASS = FakeModel\n",
            encoding="utf-8",
        )
        # The convenience scan should NOT find any loss; it should also not
        # raise.
        assert load_loss_plugin("anything") is None
        captured = capsys.readouterr()
        # The loader prints one "Skipping ... missing 'PLUGIN_LOSS_TYPE'" line
        # — that's the documented behavior on a misnamed file.
        assert "Skipping" in captured.out


# ---------------------------------------------------------------------------
# I13 — PLUGIN_LOSS_TARGET_DTYPE declaration + LOSS_TARGET_DTYPE_REGISTRY
# ---------------------------------------------------------------------------

_PLUGIN_HEAD = """\
import torch
import torch.nn as nn
from pydantic import BaseModel
PLUGIN_LOSS_TYPE = "{name}"
{dtype_line}

class _Cfg(BaseModel):
    pass

PLUGIN_LOSS_CONFIG_CLASS = _Cfg

class _Loss(nn.Module):
    def __init__(self, cfg):
        super().__init__()
    def forward(self, inputs, targets):
        return inputs.mean()

PLUGIN_LOSS_CLASS = _Loss
"""


def _write_plugin(loss_dir: Path, name: str, dtype_line: str) -> Path:
    """Write a minimal valid plugin with the given PLUGIN_LOSS_TARGET_DTYPE line.

    Pass dtype_line=='' to omit the declaration entirely (back-compat test).
    """
    plugin_path = loss_dir / f"{name}.py"
    plugin_path.write_text(_PLUGIN_HEAD.format(name=name, dtype_line=dtype_line))
    return plugin_path


class TestI13TargetDtypeDeclaration:
    """I13 — verify ``_load_loss_plugin`` reads the optional
    ``PLUGIN_LOSS_TARGET_DTYPE`` field and that ``get_loss_target_dtype``
    returns the right value from ``LOSS_TARGET_DTYPE_REGISTRY``.
    """

    def test_explicit_long_declaration_registered(self, loss_dir: Path):
        """Plugin declaring ``PLUGIN_LOSS_TARGET_DTYPE = "long"`` is
        loaded with ``target_dtype == 'long'`` in the returned dict."""
        from ml_models.loss_plugin_loader import load_loss_plugin_from_path

        plugin_path = _write_plugin(loss_dir, "long_loss", 'PLUGIN_LOSS_TARGET_DTYPE = "long"')
        result = load_loss_plugin_from_path(str(plugin_path))
        assert result is not None
        assert result["target_dtype"] == "long"

    def test_explicit_float_declaration_registered(self, loss_dir: Path):
        """Plugin declaring ``PLUGIN_LOSS_TARGET_DTYPE = "float"`` is
        loaded with ``target_dtype == 'float'``."""
        from ml_models.loss_plugin_loader import load_loss_plugin_from_path

        plugin_path = _write_plugin(loss_dir, "float_loss", 'PLUGIN_LOSS_TARGET_DTYPE = "float"')
        result = load_loss_plugin_from_path(str(plugin_path))
        assert result is not None
        assert result["target_dtype"] == "float"

    def test_missing_declaration_defaults_to_long(self, loss_dir: Path):
        """Back-compat — a plugin generated before I13 (no
        ``PLUGIN_LOSS_TARGET_DTYPE`` declaration) defaults to ``'long'``
        so it keeps receiving int64 targets per the classifier contract."""
        from ml_models.loss_plugin_loader import load_loss_plugin_from_path

        plugin_path = _write_plugin(loss_dir, "no_decl_loss", dtype_line="")
        result = load_loss_plugin_from_path(str(plugin_path))
        assert result is not None
        assert result["target_dtype"] == "long"

    def test_invalid_declaration_warns_and_defaults(
        self, loss_dir: Path, capsys: pytest.CaptureFixture
    ):
        """Plugin with an invalid value (e.g. typo'd ``'int64'`` or
        ``'i64'``) — loader warns to stdout and clamps to ``'long'``."""
        from ml_models.loss_plugin_loader import load_loss_plugin_from_path

        plugin_path = _write_plugin(loss_dir, "bad_decl_loss", 'PLUGIN_LOSS_TARGET_DTYPE = "int64"')
        result = load_loss_plugin_from_path(str(plugin_path))
        assert result is not None
        assert result["target_dtype"] == "long"
        out = capsys.readouterr().out
        assert "PLUGIN_LOSS_TARGET_DTYPE" in out
        assert "defaulting to 'long'" in out

    def test_get_loss_target_dtype_helper_default(self):
        """``get_loss_target_dtype(unknown_name)`` returns ``'long'`` —
        the documented fallback for unregistered loss names."""
        from ml_models.loss_plugin_loader import get_loss_target_dtype

        # Pick a name that cannot collide with any registered plugin.
        assert get_loss_target_dtype("__unknown_loss_for_i13_test__") == "long"

    def test_get_loss_target_dtype_helper_reads_registry(self):
        """When a plugin is registered with ``register_loss_in_memory``
        (which populates LOSS_TARGET_DTYPE_REGISTRY), the helper returns
        the declared value."""
        from ml_models.loss_plugin_loader import (
            LOSS_TARGET_DTYPE_REGISTRY,
            get_loss_target_dtype,
        )

        # Insert directly to test the helper's contract independently of the
        # register_loss_in_memory plumbing (which has its own coverage).
        LOSS_TARGET_DTYPE_REGISTRY["__i13_float_test__"] = "float"
        try:
            assert get_loss_target_dtype("__i13_float_test__") == "float"
        finally:
            LOSS_TARGET_DTYPE_REGISTRY.pop("__i13_float_test__", None)


class TestI13StubTemplateDeclaresDtype:
    """Regression guard — the stub template (used by the L1 unit tests and
    by the L4 implementor as the assembly template) MUST declare
    ``PLUGIN_LOSS_TARGET_DTYPE``. If a future refactor strips the line,
    every generated loss plugin would silently fall back to ``'long'``
    by default — which is correct today but masks intent and breaks the
    moment we want a regressor-style custom loss."""

    def test_stub_template_declares_target_dtype(self):
        from ml_models.loss_plugin_loader import LOSSES_DIR

        template_path = (
            Path(__file__).resolve().parents[3]
            / "tests"
            / "fixtures"
            / "generated_capabilities"
            / "stub_loss_template.py"
        )
        text = template_path.read_text()
        assert 'PLUGIN_LOSS_TARGET_DTYPE = "long"' in text, (
            "stub_loss_template.py is missing the I13 declaration "
            "PLUGIN_LOSS_TARGET_DTYPE = 'long'. Without it, the L4 implementor's "
            "assembled plugins would silently default to 'long' — which is the "
            "correct value today but hides intent. Restore the declaration."
        )


def test_selected_loss_reports_declaration_path_for_reexported_class(loss_dir, monkeypatch):
    from pydantic import BaseModel
    from torch.nn import MSELoss

    declaration = loss_dir / "reexport.py"
    declaration.write_text(
        "from pydantic import BaseModel\nfrom torch.nn import MSELoss\n"
        'PLUGIN_LOSS_TYPE="reexported"\nPLUGIN_LOSS_CONFIG_CLASS=BaseModel\n'
        'PLUGIN_LOSS_CLASS=MSELoss\nPLUGIN_LOSS_TARGET_DTYPE="float"\n'
    )
    monkeypatch.setattr(_loss_loader, "_resolve_loss_dirs", lambda: [str(loss_dir)])
    result = load_loss_plugin("reexported")
    assert result is not None
    assert result["loss_class"] is MSELoss
    assert result["config_class"] is BaseModel
    assert result["plugin_path"] == str(declaration)
    assert Path(inspect.getfile(result["loss_class"])) != declaration


def test_captured_loss_reports_its_declared_member_path(tmp_path):
    from core.local_code import CodePackageDeclaration, bind_code_package, capture_package

    declaration = _copy_stub(tmp_path)
    package = capture_package(CodePackageDeclaration(root=".", files=(declaration.name,)), tmp_path)
    with bind_code_package(package):
        result = _loss_loader.load_loss_plugin_from_path(str(declaration))
    assert result is not None
    assert result["plugin_path"] == str(declaration)
