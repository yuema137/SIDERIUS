"""runtime_environment_identity covers the generated-program supervision path (#1493).

A persisted generated program is reused only while ``runtime_environment_identity``
is unchanged. The supervisor ``AnalysisCodeSandbox`` stops a program through
``process_termination.terminate_process_group``, which delegates signalling and
reaping to core ``core.runtime_control.process_group``. A behaviour change in
any module on that path must move the identity, so each one must be hashed.

The path is derived from imports, not listed here: start at the module that
defines ``AnalysisCodeSandbox`` and follow first-party imports that stay in the
supervisor's own package or in the core process-supervision package that owns
``terminate_observed_group``. A full import closure is not usable: through the
schemas and persistence it reaches about 250 modules, including model and
training code that has nothing to do with supervision. A supervision helper
moved into another core package would not be followed; this rule covers moves
within the two owning packages.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent.data_analysis import generated_programs, process_termination
from agent.data_analysis.analysis_code_sandbox import AnalysisCodeSandbox

SRC_ROOT = Path(generated_programs.__file__).resolve().parents[2]


def _source(obj: type | Callable[..., object]) -> Path:
    path = inspect.getsourcefile(obj)
    assert path is not None
    return Path(path).resolve()


SUPERVISOR = _source(AnalysisCodeSandbox)
SIGNALLING_OWNER = _source(process_termination.terminate_observed_group)
SUPERVISION_PACKAGES = (SUPERVISOR.parent, SIGNALLING_OWNER.parent)


def _module_file(dotted: str) -> Path | None:
    stem = SRC_ROOT.joinpath(*dotted.split("."))
    for candidate in (stem.with_suffix(".py"), stem / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _imported_files(path: Path) -> set[Path]:
    package = path.relative_to(SRC_ROOT).parent.parts
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else ()
            module = ".".join((*base, *([node.module] if node.module else [])))
            names.add(module)
            names.update(f"{module}.{alias.name}" for alias in node.names)
    return {file for name in names if (file := _module_file(name)) is not None}


def _supervision_path() -> set[str]:
    seen: set[Path] = set()
    pending = [SUPERVISOR]
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        pending.extend(
            imported
            for imported in _imported_files(path)
            if any(imported.is_relative_to(package) for package in SUPERVISION_PACKAGES)
        )
    return {path.relative_to(SRC_ROOT).as_posix() for path in seen}


def _hashed_runtime_files(monkeypatch: pytest.MonkeyPatch) -> set[str]:
    captured: list[dict[str, Any]] = []
    real = generated_programs.canonical_sha256

    def recording(value: Any) -> str:
        captured.append(value)
        return real(value)

    monkeypatch.setattr(generated_programs, "canonical_sha256", recording)
    generated_programs.runtime_environment_identity()
    (payload,) = captured
    return set(payload["sandbox_runtime_files"])


def test_runtime_identity_hashes_every_supervision_path_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _supervision_path()
    # The derivation must reach the module that actually signals the group.
    assert SIGNALLING_OWNER.relative_to(SRC_ROOT).as_posix() in path, sorted(path)
    missing = sorted(path - _hashed_runtime_files(monkeypatch))
    assert not missing, f"runtime_environment_identity does not hash {missing}"
