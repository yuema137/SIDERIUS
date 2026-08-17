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
NODES_DIR = REPO_ROOT / "nodes"

#: Directories holding PRODUCTION code. Tests are deliberately excluded: a
#: structural or reachability test may legitimately import an internal module
#: to assert something about it.
PRODUCTION_DIRS = ("nodes", "agent", "core", "execute_tools", "workflows", "scripts", "dashboard")


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
        out.extend(sorted((REPO_ROOT / d).rglob("*.py")))
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


def test_the_tuner_nodes_private_modules_form_an_acyclic_graph():
    """The concrete graph C7 established, pinned so a future move cannot
    reintroduce the ``records`` <-> ``runtime`` cycle the first cut produced.

    ``records`` BUILDS records; ``runtime`` EMITS them. That is why ``runtime``
    may import ``records`` and never the reverse.
    """
    node = NODES_DIR / "ml_hyperparameter_tune_agent"
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


def test_the_tuner_main_module_separates_public_api_from_compatibility_reexports():
    """``__all__`` must not quietly redefine the node's public API.

    C7 re-exported several dozen moved private helpers from the main module so
    existing importers and ``mock.patch`` targets kept working. That is a
    COMPATIBILITY scaffold, not an interface: leaving it undistinguished would
    make "what is this node's public API" unanswerable again, which is the
    condition the decomposition set out to remove.
    """
    main = NODES_DIR / "ml_hyperparameter_tune_agent" / "ml_hyperparameter_tune_agent.py"
    src = main.read_text(encoding="utf-8")

    public = re.search(r"^__all__ = \[(.*?)^\]", src, re.S | re.M)
    assert public, "the main module must declare __all__"
    names = re.findall(r'"([^"]+)"', public.group(1))
    assert names, "__all__ must not be empty"

    assert "HyperparamTuningAgent" in names and "main" in names
    private = [n for n in names if n.startswith("_")]
    assert private == [], (
        "__all__ is the node's PUBLIC surface; private helpers re-exported for "
        f"compatibility belong in _COMPATIBILITY_REEXPORTS, not here: {private}"
    )
    assert "_COMPATIBILITY_REEXPORTS" in src, (
        "the compatibility re-exports must be named as such, so a reader can "
        "tell the node's contract from its scaffolding"
    )
