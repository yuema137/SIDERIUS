"""Syntactic tripwire for exception text entering console views (#1249/#1265)."""

import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4] / "src/tools/candidate_console"
BASELINE = Path(__file__).with_name("error_projection_followups.json")


def _logging(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in {"logger", "logging", "log"}
        and node.func.attr in {"debug", "info", "warning", "error", "exception", "critical"}
    )


def _raw_expression(node: ast.AST, caught: set[str]) -> bool:
    """Recognize direct exception conversions and message carriers."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id in {"str", "repr"} and any(
            isinstance(arg, ast.Name) and arg.id in caught for arg in node.args
        )
    if isinstance(node, ast.FormattedValue):
        return isinstance(node.value, ast.Name) and node.value.id in caught
    if isinstance(node, ast.Attribute) and node.attr == "message":
        return isinstance(node.value, ast.Name) and node.value.id in caught | {"failure"}
    return False


def _forwarding(tree: ast.AST) -> set[str]:
    """Find direct conversions/interpolations and serialized message forwarding.

    This is a review tripwire, not whole-program taint analysis. Exact legacy
    expressions are enumerated with their owner and follow-up, never whole files.
    Logging arguments are the intentional private diagnostic destination.
    """
    caught = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler) and node.name
    }
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    findings = set()
    for node in ast.walk(tree):
        if not _raw_expression(node, caught):
            continue
        ancestor = parents.get(node)
        while ancestor is not None and not _logging(ancestor):
            ancestor = parents.get(ancestor)
        if ancestor is None:
            statement = node
            while not isinstance(statement, ast.stmt) and statement in parents:
                statement = parents[statement]
            findings.add(ast.unparse(statement))
    return findings


def test_console_exception_forwarding_has_no_unreviewed_surfaces():
    """Fail on restored task/GPU/setup leaks or any newly introduced direct projection."""
    baseline = json.loads(BASELINE.read_text())
    observed = {
        str(path.relative_to(ROOT)): sorted(_forwarding(ast.parse(path.read_text())))
        for path in ROOT.rglob("*.py")
    }
    observed = {name: expressions for name, expressions in observed.items() if expressions}
    assert observed == baseline["expressions"], (
        "Review the error projection; use the shared category owner and private logging. "
        "Remove repaired legacy exceptions; do not expand the baseline to hide new leaks."
    )


@pytest.mark.parametrize("expression", ["str(cause)", "repr(cause)", "f'{cause}'", "cause.message"])
def test_guard_detects_exception_forwarding(expression):
    """The guard must catch arbitrary exception variable names and all direct spellings."""
    tree = ast.parse(
        f"try:\n    work()\nexcept Exception as cause:\n    return View(message={expression})"
    )
    assert _forwarding(tree)


def test_guard_detects_serialized_failure_and_allows_logging():
    assert _forwarding(ast.parse("return View(message=failure.message)"))
    assert not _forwarding(ast.parse("logger.error('cause: %s', failure.message)"))
