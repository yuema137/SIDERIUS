"""Every node has exactly ONE public interface: ``<node>.py`` + ``<node>.md``.

Operator architecture rule (2026-08-16), made executable rather than left as a
convention. It has two halves, and both are load-bearing:

```text
nodes/<node>/
    <node>.py     PUBLIC  — the class, run(), the CLI entrypoint, the lifecycle
    <node>.md     PUBLIC  — what the node promises its callers
    *.py          PRIVATE — implementation detail, serving <node>.py only
```

**Outward**: production code outside a node must not import that node's private
submodules. If it does, the decomposition has leaked — the node can no longer
be restructured without breaking callers, which is precisely what the main
file's stability is supposed to buy.

**Inward**: a private submodule must not import its own node's main module.
That direction is a cycle, and it is how "implementation detail" quietly turns
into a second orchestrator.

The defect this catches is not hypothetical: Step 07 PR 07b's C7 decomposition
moved ~4,300 lines out of the tuner's main file, and the first cut of the
ownership boundaries produced a genuine ``records`` <-> ``runtime`` cycle.
Nothing but a test keeps that from reappearing the next time a node is split.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
NODES_DIR = REPO_ROOT / "src/nodes"

#: Directories holding PRODUCTION code. Tests are deliberately excluded: a
#: structural or reachability test may legitimately import an internal module
#: to assert something about it.
PRODUCTION_DIRS = (
    "src/nodes",
    "src/agent",
    "src/core",
    "src/execute_tools",
    "src/workflows",
    "scripts",
    "src/dashboard",
)


def _node_packages() -> list[Path]:
    """Every node laid out as ``nodes/<name>/<name>.py``."""
    return sorted(
        d
        for d in NODES_DIR.iterdir()
        if d.is_dir() and (d / f"{d.name}.py").exists() and not d.name.startswith("_")
    )


def _private_modules(node: Path) -> list[Path]:
    return sorted(
        p
        for p in node.glob("*.py")
        if p.name not in (f"{node.name}.py", "__init__.py") and not p.name.startswith("_")
    )


def _imported_modules(path: Path) -> set[str]:
    """Dotted module names this file imports (absolute imports only)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            found.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            found.add(n.module)
    return found


def _production_files() -> list[Path]:
    out: list[Path] = []
    for d in PRODUCTION_DIRS:
        sources = sorted((REPO_ROOT / d).rglob("*.py"))
        assert sources, f"missing production scan subject: {d}"
        out.extend(sources)
    return out


def test_at_least_one_node_is_decomposed_so_this_module_is_not_vacuous():
    """Guard against the whole file silently testing nothing."""
    assert any(_private_modules(n) for n in _node_packages())


@pytest.mark.parametrize("node", _node_packages(), ids=lambda p: p.name)
def test_every_node_publishes_a_same_named_markdown_contract(node: Path):
    """``<node>.md`` is half the public interface — the half that says what the
    node promises. A node without one has no stated contract to hold it to."""
    assert (node / f"{node.name}.md").exists(), (
        f"{node.name} has no {node.name}.md; the node's behavioural contract is "
        f"part of its public interface, not optional documentation"
    )


def test_no_production_code_outside_a_node_imports_that_nodes_private_modules():
    """MUTATION TARGET: ``from nodes.foo.runtime import _helper`` in a workflow.

    It would work, and it would quietly make an implementation detail part of
    the node's contract — so the next restructure breaks a caller that never
    should have been able to see it.
    """
    offenders: dict[str, list[str]] = {}
    for node in _node_packages():
        private = {f"nodes.{node.name}.{p.stem}" for p in _private_modules(node)}
        if not private:
            continue
        for f in _production_files():
            if f.is_relative_to(node):  # the node may import its own internals
                continue
            hits = sorted(private & _imported_modules(f))
            if hits:
                offenders.setdefault(f.relative_to(REPO_ROOT).as_posix(), []).extend(hits)
    assert offenders == {}, (
        "production code outside a node imported that node's private modules; "
        f"import the node's public interface instead: {offenders}"
    )


@pytest.mark.parametrize("node", _node_packages(), ids=lambda p: p.name)
def test_no_private_module_imports_its_own_nodes_main_module(node: Path):
    """The dependency runs one way: main -> private, never back.

    A private module importing the main module is a cycle, and it means the
    submodule has started to orchestrate rather than implement.
    """
    main_mod = f"nodes.{node.name}.{node.name}"
    offenders = {
        p.name: sorted(m for m in _imported_modules(p) if m == main_mod)
        for p in _private_modules(node)
    }
    offenders = {k: v for k, v in offenders.items() if v}
    assert offenders == {}, f"{node.name}: private modules imported the main module: {offenders}"


def _decomposed_nodes() -> list[Path]:
    """Every node that actually HAS private modules.

    Step 09a C1b: the two halves below were hardcoded to the tuner, the only
    decomposed node at the time. The interpreter is the second, and a rule that
    only ever examines one node is not a rule — so they are parametrized over
    whichever nodes are decomposed, and the tuner's concrete graph stays
    covered by being one of them.
    """
    return [n for n in _node_packages() if _private_modules(n)]


@pytest.mark.parametrize("node", _decomposed_nodes(), ids=lambda p: p.name)
def test_a_decomposed_nodes_private_modules_form_an_acyclic_graph(node: Path):
    """Pinned so a future move cannot reintroduce the ``records`` <->
    ``runtime`` cycle the tuner's first cut produced.

    ``records`` BUILDS records; ``runtime`` EMITS them. That is why ``runtime``
    may import ``records`` and never the reverse. The interpreter's graph is
    main -> {evidence, ordering, prediction} with ``ordering`` permitted to
    reach ``evidence``; the same one-way rule applies.
    """
    edges: dict[str, set[str]] = {}
    names = {p.stem for p in _private_modules(node)}
    for p in _private_modules(node):
        edges[p.stem] = {
            m.rsplit(".", 1)[-1]
            for m in _imported_modules(p)
            if m.startswith(f"nodes.{node.name}.") and m.rsplit(".", 1)[-1] in names
        }

    # depth-first cycle detection over the private graph
    state: dict[str, int] = {}

    def visit(n: str, trail: list[str]) -> None:
        state[n] = 1
        for m in sorted(edges.get(n, ())):
            if state.get(m) == 1:
                raise AssertionError(
                    f"import cycle among private modules: {' -> '.join([*trail, n, m])}"
                )
            if state.get(m, 0) == 0:
                visit(m, [*trail, n])
        state[n] = 2

    for n in sorted(edges):
        if state.get(n, 0) == 0:
            visit(n, [])


@pytest.mark.parametrize("node", _decomposed_nodes(), ids=lambda p: p.name)
def test_a_decomposed_node_defines_each_symbol_exactly_once(node: Path):
    """MUTATION TARGET: COPY a helper into a private module and leave the
    original in the main file.

    That is the failure mode an extraction is most likely to produce and least
    likely to notice: both definitions are green, both are imported somewhere,
    and the two drift. "Moved" has to mean the definition site MOVED — the main
    module re-exports by IMPORT, never by keeping a second copy.

    Step 09a C1b (design §4.2 acceptance: "every moved symbol is DEFINED
    exactly once ... never a copy, no duplicate authority").

    Scope: ``def`` / ``class``, plus module-level assignments of LITERAL data
    (a duplicated lookup table drifts exactly like a duplicated function). It
    deliberately does NOT cover a name bound to a call result: the tuner binds
    its own private modules as ``_records = _import_module(...)`` in three
    files and derives ``SIDERIUS_ROOT`` from ``__file__`` in two, and those are
    local bindings of the same thing, not two implementations of it. The first
    cut of this rule flagged them, which is how the scope was settled.
    """
    literal = (ast.Dict, ast.Set, ast.List, ast.Tuple, ast.Constant)
    definitions: dict[str, list[str]] = {}
    for module in [node / f"{node.name}.py", *_private_modules(node)]:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for stmt in tree.body:
            if isinstance(stmt, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                definitions.setdefault(stmt.name, []).append(module.name)
            elif isinstance(stmt, ast.Assign) and isinstance(stmt.value, literal):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        definitions.setdefault(target.id, []).append(module.name)

    duplicated = {n: sorted(where) for n, where in definitions.items() if len(where) > 1}
    assert duplicated == {}, (
        f"{node.name}: these names are defined in more than one module of the "
        f"node package — a re-export must be an import, not a copy: {duplicated}"
    )


@pytest.mark.parametrize("node", _decomposed_nodes(), ids=lambda p: p.name)
def test_a_decomposed_main_module_separates_public_api_from_compatibility_reexports(node: Path):
    """``__all__`` must not quietly redefine the node's public API.

    A decomposition re-exports moved private helpers from the main module so
    existing importers and ``mock.patch`` targets keep working (the tuner's C7
    moved several dozen; the interpreter's C1b moved nine). That is a
    COMPATIBILITY scaffold, not an interface: leaving it undistinguished would
    make "what is this node's public API" unanswerable again, which is the
    condition the decomposition set out to remove.

    Step 09a C1b generalised this from the tuner to every decomposed node. The
    public anchors are derived from the node's own source rather than
    hardcoded: its agent CLASS and its ``main`` entrypoint.
    """
    main = node / f"{node.name}.py"
    src = main.read_text(encoding="utf-8")

    public = re.search(r"^__all__ = \[(.*?)^\]", src, re.S | re.M)
    assert public, f"{node.name}: the main module must declare __all__"
    names = re.findall(r'"([^"]+)"', public.group(1))
    assert names, f"{node.name}: __all__ must not be empty"

    tree = ast.parse(src)
    classes = [
        n.name for n in tree.body if isinstance(n, ast.ClassDef) and not n.name.startswith("_")
    ]
    assert classes, f"{node.name}: the main module defines no public class"
    missing = [c for c in classes if c not in names]
    assert missing == [], (
        f"{node.name}: the node's public class(es) must appear in __all__ — "
        f"otherwise the declared surface omits the thing callers actually use: {missing}"
    )
    assert "main" in names, f"{node.name}: the CLI entrypoint belongs in __all__"

    private = [n for n in names if n.startswith("_")]
    assert private == [], (
        f"{node.name}: __all__ is the node's PUBLIC surface; private helpers "
        f"re-exported for compatibility belong in _COMPATIBILITY_REEXPORTS, "
        f"not here: {private}"
    )
    assert "_COMPATIBILITY_REEXPORTS" in src, (
        f"{node.name}: the compatibility re-exports must be named as such, so "
        "a reader can tell the node's contract from its scaffolding"
    )
