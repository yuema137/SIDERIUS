"""runtime_environment_identity covers the generated-program supervision path (#1493, #1500).

A persisted generated program is reused only while ``runtime_environment_identity``
is unchanged. A behaviour change in any module on the supervisor's path must move
the identity, so each one must be hashed.

The path is derived from imports, not listed here, in two bounded steps:

1. Start at the module that defines ``AnalysisCodeSandbox`` and follow
   first-party imports transitively, but only inside the supervisor's own
   package (``agent/data_analysis/``) and the core process-supervision package
   that owns ``terminate_observed_group`` (``core/runtime_control/``). Today this
   gives ``analysis_code_sandbox.py``, ``process_termination.py`` and
   ``core/runtime_control/process_group.py``.
2. Add every other ``core/`` module that a step-1 module imports directly (one
   hop). Today: ``execution_deadline.py`` (allocation expiry, so the stop time),
   ``training_seeds.py`` (``NUMPY_SEED_MASK``), ``campaign_identity.py`` and
   ``durable_io.py``. Each must be hashed or listed in ``UNHASHED_CORE_IMPORTS``
   with a reason; an unclassified new import fails the test.

The hop is not followed further. A full import closure is not usable: through
the schemas and persistence it reaches about 40 modules from the sandbox (about
250 from all hashed files), including model and training code unrelated to
supervision. The direct core imports are the owners whose symbols the
supervisor calls; their own dependencies (for example ``core.seeding`` behind
``training_seeds``) serve other callers. A supervision helper moved into a
non-core package outside step 1 would not be followed.

Boundary: the walk starts only at ``analysis_code_sandbox.py``. Direct core
imports of the other hashed modules are intentionally not classified:
``executor.py`` imports ``core.subprocess_env``, which builds the skill-worker
environment and is not on the generated-program path; ``generated_programs.py``
imports ``core.generated_seed_scan``, which writes write-once seed-call
provenance, so a changed scan fails closed with a collision instead of
silently reusing a record. Their other core imports (``campaign_identity``,
``durable_io``, ``execution_deadline``) are already classified by step 2.
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
CORE_ROOT = SRC_ROOT / "core"

# Direct core imports that do not define what an accepted program computes or
# when it is stopped, so they stay out of the identity.
UNHASHED_CORE_IMPORTS = {
    # validate_path_component only rejects unsafe ids before launch.
    "core/campaign_identity.py": "path-component validation",
    # publish_bytes_write_once only makes request/output publication atomic.
    "core/durable_io.py": "atomic write-once publication",
}


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


def _direct_core_imports(path_modules: set[str]) -> set[str]:
    return {
        imported.relative_to(SRC_ROOT).as_posix()
        for module in path_modules
        for imported in _imported_files(SRC_ROOT / module)
        if imported.is_relative_to(CORE_ROOT)
    } - path_modules


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
    direct_core = _direct_core_imports(path)
    stale = sorted(set(UNHASHED_CORE_IMPORTS) - direct_core)
    assert not stale, f"exclusions no longer imported by the supervisor path: {stale}"
    required = (path | direct_core) - set(UNHASHED_CORE_IMPORTS)
    missing = sorted(required - _hashed_runtime_files(monkeypatch))
    assert not missing, f"runtime_environment_identity does not hash {missing}"
