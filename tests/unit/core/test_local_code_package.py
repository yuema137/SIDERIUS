"""Finite-import semantics: each case names an observable non-schema defect."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from core.local_code import (
    CodePackageDeclaration,
    LocalCodeError,
    acquire_module,
    active_package,
    bind_code_package,
    capture_package,
    module_identity,
    scan_candidate_allowed,
)


def package(root: Path, sources: dict[str, str], *, listed: tuple[str, ...] | None = None):
    for name, source in sources.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    return capture_package(
        CodePackageDeclaration(root=str(root), files=listed or tuple(sources)), root.parent
    )


@pytest.mark.parametrize(
    "order", [("runtime/data.py", "plugins/metric.py"), ("plugins/metric.py", "runtime/data.py")]
)
def test_shared_helper_class_across_entries_and_load_order(tmp_path, order):
    """Per-entry namespaces fail the real isinstance check, in either order."""
    sources = {
        "runtime/scope.py": "class Scope: pass\n",
        "runtime/data.py": "from .scope import Scope\ndef create(): return Scope()\n",
        "plugins/metric.py": "from ..runtime.scope import Scope\ndef accepts(value): return isinstance(value, Scope)\n",
    }
    captured = package(tmp_path, sources)
    loaded = {}
    with bind_code_package(captured):
        for name in order:
            with acquire_module(tmp_path / name) as module:
                loaded[name] = module
        data, metric = loaded["runtime/data.py"], loaded["plugins/metric.py"]
        assert metric.accepts(data.create())
        assert data.Scope is metric.Scope
        identity = module_identity(sys.modules[data.Scope.__module__])
        assert identity.member == "runtime/scope.py"
        assert len(identity.package.members) == 3
        with acquire_module(tmp_path / "runtime/data.py") as again:
            assert again is data


def test_relocation_identity_but_distinct_runtime_paths_and_helper_drift(tmp_path):
    """Location must not enter identity or make __file__ point at another root."""
    sources = {"entry.py": "from .helper import VALUE\n", "helper.py": "VALUE = 7\n"}
    first = package(tmp_path / "first", sources)
    second = package(tmp_path / "second", dict(reversed(list(sources.items()))))
    assert first.identity == second.identity
    modules = []
    for captured in (first, second):
        with bind_code_package(captured), acquire_module(captured.root / "entry.py") as module:
            modules.append(module)
            assert Path(module.__file__).parent == captured.root
    assert modules[0] is not modules[1]
    changed = package(first.root, {**sources, "helper.py": "VALUE = 8\n"})
    assert changed.identity.digest != first.identity.digest


def test_late_import_uses_capture_not_changed_disk_or_pyc(tmp_path):
    """Delayed execution and entry hashes must describe the same captured bytes."""
    captured = package(
        tmp_path,
        {
            "entry.py": "def read():\n from .helper import VALUE\n return VALUE\n",
            "helper.py": "VALUE = 7\n",
        },
    )
    with bind_code_package(captured), acquire_module(tmp_path / "entry.py") as module:
        (tmp_path / "helper.py").write_text("VALUE = 9\n")
        assert module.read() == 7


def test_unlisted_initializers_never_execute_and_missing_relative_refuses(tmp_path):
    """A real directory __path__ would execute either poison file."""
    captured = package(
        tmp_path,
        {
            "sub/entry.py": "from . import hidden\n",
            "sub/__init__.py": "raise AssertionError('unlisted initializer')\n",
            "sub/hidden.py": "raise AssertionError('unlisted helper')\n",
        },
        listed=("sub/entry.py",),
    )
    with bind_code_package(captured):
        assert not scan_candidate_allowed(tmp_path / "sub/hidden.py")
        with pytest.raises(LocalCodeError, match="undeclared member"):
            with acquire_module(tmp_path / "sub/hidden.py"):
                pass
        with pytest.raises(LocalCodeError, match="undeclared relative import"):
            with acquire_module(tmp_path / "sub/entry.py"):
                pass


def test_explicit_initializers_and_parent_relative_import(tmp_path):
    """Listed initializers execute and nested parent-relative helpers resolve."""
    captured = package(
        tmp_path,
        {
            "__init__.py": "VALUE = 4\n",
            "sub/__init__.py": "from .. import VALUE\nVALUE += 3\n",
            "sub/entry.py": "from . import VALUE\n",
        },
    )
    with bind_code_package(captured), acquire_module(tmp_path / "sub/entry.py") as module:
        assert module.VALUE == 7


def test_failed_family_check_removes_new_modules_and_parent_attributes_only(tmp_path):
    """A failed requested-symbol check must not leave helper state for a retry."""
    captured = package(
        tmp_path,
        {
            "good.py": "class Kept: pass\n",
            "helper.py": "class Fresh: pass\n",
            "entry.py": "from .helper import Fresh\n",
        },
    )
    with bind_code_package(captured):
        with acquire_module(tmp_path / "good.py") as good:
            parent = sys.modules[good.__package__]
        with pytest.raises(AttributeError):
            with acquire_module(tmp_path / "entry.py") as entry:
                old_class = entry.Fresh
                assert entry.Missing
        assert not hasattr(parent, "helper")
        assert not hasattr(parent, "entry")
        assert parent.good is good
        with acquire_module(tmp_path / "entry.py") as entry:
            assert entry.Fresh is not old_class


@pytest.mark.parametrize(
    "files",
    [
        ("a.py", "a.py"),
        ("a.py", "a/__init__.py"),
        ("a.py", "a/b.py"),
        ("my__init__.py", "my__init__/child.py"),
        ("../escape.py",),
        ("/absolute.py",),
        ("a//b.py",),
        ("a/./b.py",),
        ("a-b.py",),
        ("a\\b.py",),
    ],
)
def test_ambiguous_or_escaping_module_layout_refuses(files):
    """Finite-name mapping cannot normalize two meanings into one module."""
    with pytest.raises(ValueError):
        CodePackageDeclaration(root=".", files=files)


def test_symlink_escape_and_missing_member_refuse_before_execution(tmp_path):
    outside = tmp_path / "outside.py"
    outside.write_text("raise AssertionError('must never run')")
    root = tmp_path / "code"
    root.mkdir()
    (root / "entry.py").symlink_to(outside)
    declaration = CodePackageDeclaration(root="code", files=("entry.py",))
    with pytest.raises(LocalCodeError, match="escapes root"):
        capture_package(declaration, tmp_path)
    (root / "entry.py").unlink()
    with pytest.raises(LocalCodeError, match="missing/unreadable"):
        capture_package(declaration, tmp_path)


def test_binding_restores_outer_decision_and_unrelated_files_fall_back(tmp_path):
    captured = package(tmp_path / "code", {"entry.py": "VALUE = 7\n"})
    with bind_code_package(captured):
        with bind_code_package(None), acquire_module(captured.root / "entry.py") as absent:
            assert absent is None
        assert active_package() is captured
        with acquire_module(tmp_path / "generated.py") as unrelated:
            assert unrelated is None


def test_metadata_precedes_execution_and_lazy_failure_rolls_back_dependencies(tmp_path):
    """Import-time registration can read metadata; failed lazy trees leave no helpers."""
    captured = package(
        tmp_path,
        {
            "entry.py": "PIN = __siderius_local_code__.member\ndef load():\n from . import broken\n",
            "broken.py": "from . import helper\nraise RuntimeError('broken')\n",
            "helper.py": "VALUE = 7\n",
        },
    )
    with bind_code_package(captured), acquire_module(tmp_path / "entry.py") as module:
        pass
    assert module.PIN == "entry.py"
    with pytest.raises(RuntimeError, match="broken"):
        module.load()
    parent = sys.modules[module.__package__]
    assert not hasattr(parent, "helper")
    assert not hasattr(parent, "broken")


def test_root_alias_never_falls_back_and_capture_survives_alias_retarget(tmp_path):
    """An alias outside realroot must still load relative helpers from the capture."""
    real = tmp_path / "real"
    package(real, {"entry.py": "from .helper import VALUE\n", "helper.py": "VALUE = 7\n"})
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    captured = capture_package(
        CodePackageDeclaration(root="alias", files=("entry.py", "helper.py")), tmp_path
    )
    with bind_code_package(captured), acquire_module(alias / "entry.py") as module:
        assert module.VALUE == 7
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    alias.unlink()
    alias.symlink_to(elsewhere, target_is_directory=True)
    with bind_code_package(captured), acquire_module(alias / "entry.py") as again:
        assert again is module
