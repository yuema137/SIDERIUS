"""The task-composition reference must list exactly the prompt boundaries in source.

A prompt-rendering profile (``prompt_renderer:``) must declare every boundary
its run reaches, or the run raises when it gets there. Authors learn the set,
the owner functions and the callback signatures from
``docs/reference/task-composition.md``. That list was hand-maintained and
fell five boundaries behind source (#1539).

The census is read from the AST, without importing anything: every function
decorated with ``prompt_boundary("<name>", ...)`` under ``src/``. A decorator
spelt any other way (an alias, ``module.prompt_boundary``) is not seen; the
rendering module defines the decorator once and every owner imports it by name.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "src"
REFERENCE = REPO_ROOT / "docs" / "reference" / "task-composition.md"
_ENTRY = re.compile(r"^- `([a-z_]+\.[a-z_]+)`: `(src/[^`]+)`$", re.MULTILINE)


def _decorated_boundaries() -> dict[str, str]:
    """Boundary name -> ``src/<path>::<function>(<args>) -> <return>``."""
    found: dict[str, str] = {}
    for path in sorted(SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "prompt_boundary(" not in text:  # cheap pre-filter; the AST decides
            continue
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not (
                    isinstance(decorator, ast.Call)
                    and getattr(decorator.func, "id", None) == "prompt_boundary"
                ):
                    continue
                name = decorator.args[0] if decorator.args else None
                where = f"{path.relative_to(REPO_ROOT)}:{node.lineno}"
                assert isinstance(name, ast.Constant) and isinstance(name.value, str), (
                    f"{where}: prompt_boundary needs a literal name so it can be documented"
                )
                assert name.value not in found, f"{where}: boundary {name.value!r} declared twice"
                returns = ast.unparse(node.returns) if node.returns else "None"
                found[name.value] = (
                    f"{path.relative_to(REPO_ROOT)}::{node.name}({ast.unparse(node.args)}) -> {returns}"
                )
    return found


def test_the_reference_lists_every_prompt_boundary_with_its_owner_and_signature() -> None:
    """Defects caught (#1539): a boundary added, renamed, moved to another
    function or re-typed in source without the reference list following,
    and a documented boundary that no longer exists. The failure prints the
    exact list entries to paste."""
    source = _decorated_boundaries()
    assert source, "no prompt_boundary declarations found; the census is broken"
    documented = dict(_ENTRY.findall(REFERENCE.read_text(encoding="utf-8")))
    expected = "\n".join(f"- `{name}`: `{owner}`" for name, owner in sorted(source.items()))
    assert documented == source, (
        "docs/reference/task-composition.md prompt-boundary list differs from source; "
        f"replace it with:\n{expected}"
    )
