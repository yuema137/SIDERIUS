"""The task-composition reference must list exactly the prompt boundaries in source.

A prompt-rendering profile (``prompt_renderer:``) must declare every boundary
its run reaches, or the run raises when it gets there. Authors learn the set,
the owner functions and the callback signatures from
``docs/reference/task-composition.md``. That list was hand-maintained and
fell five boundaries behind source (#1539).

The census is read from the AST, without importing anything: every function
decorated with ``@prompt_boundary("<literal>")`` under ``src/``. It fails
closed: any other spelling that could declare a boundary invisibly (an
aliased import, ``module.prompt_boundary``, a call that is not a function
decorator, a non-literal name) is refused rather than skipped.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "src"
REFERENCE = REPO_ROOT / "docs" / "reference" / "task-composition.md"
_ENTRY = re.compile(r"^- `([a-z_]+\.[a-z_]+)`: `(src/[^`]+)`$", re.MULTILINE)
_DECLARE = 'declare boundaries as @prompt_boundary("<literal>")'


def _is_boundary_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and getattr(node.func, "id", None) == "prompt_boundary"


def _boundaries_in(path: Path, tree: ast.Module) -> dict[str, str]:
    """Boundary name -> ``src/<path>::<function>(<args>) -> <return>`` for one module."""
    rel = path.relative_to(REPO_ROOT)
    decorators: set[int] = set()
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not (isinstance(decorator, ast.Call) and _is_boundary_call(decorator)):
                continue
            decorators.add(id(decorator))
            name = decorator.args[0] if decorator.args else None
            assert isinstance(name, ast.Constant) and isinstance(name.value, str), (
                f"{rel}:{node.lineno}: non-literal boundary name; {_DECLARE}"
            )
            assert name.value not in found, f"{rel}:{node.lineno}: {name.value!r} declared twice"
            returns = ast.unparse(node.returns) if node.returns else "None"
            found[name.value] = f"{rel}::{node.name}({ast.unparse(node.args)}) -> {returns}"
    for node in ast.walk(tree):
        where = f"{rel}:{getattr(node, 'lineno', '?')}"
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                assert not (alias.name == "prompt_boundary" and alias.asname), (
                    f"{where}: prompt_boundary imported as {alias.asname!r}; {_DECLARE}"
                )
        elif isinstance(node, ast.Attribute) and node.attr == "prompt_boundary":
            raise AssertionError(f"{where}: prompt_boundary used as an attribute; {_DECLARE}")
        elif _is_boundary_call(node) and id(node) not in decorators:
            raise AssertionError(f"{where}: prompt_boundary called outside a decorator; {_DECLARE}")
    return found


def _decorated_boundaries() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in sorted(SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        # Cheap pre-filter on the bare word; the AST checks decide.
        if "prompt_boundary" not in text:
            continue
        for name, owner in _boundaries_in(path, ast.parse(text, filename=str(path))).items():
            assert name not in found, f"{owner}: boundary {name!r} also declared at {found[name]}"
            found[name] = owner
    return found


def test_the_reference_lists_every_prompt_boundary_with_its_owner_and_signature() -> None:
    """Defects caught (#1539): a boundary added, renamed, moved to another
    function or re-typed in source without the reference list following; a
    documented boundary that no longer exists; a duplicated list line; and a
    boundary declared in a spelling the census cannot see. The failure prints
    the exact list entries to paste."""
    source = _decorated_boundaries()
    assert source, "no prompt_boundary declarations found; the census is broken"
    entries = _ENTRY.findall(REFERENCE.read_text(encoding="utf-8"))
    documented = dict(entries)
    assert len(entries) == len(documented), "the reference lists a prompt boundary twice"
    expected = "\n".join(f"- `{name}`: `{owner}`" for name, owner in sorted(source.items()))
    assert documented == source, (
        "docs/reference/task-composition.md prompt-boundary list differs from source; "
        f"replace it with:\n{expected}"
    )
