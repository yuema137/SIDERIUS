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


def _mentions_exception(node: ast.AST, caught: set[str]) -> bool:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id in {
            "console_error_message",
            "advice_error_message",
            "summary_error_message",
            "error_category",
        }:
            return False
    if isinstance(node, ast.Name):
        return node.id in caught
    return any(_mentions_exception(child, caught) for child in ast.iter_child_nodes(node))


def _message_attribute(node: ast.AST, caught: set[str]) -> bool:
    if not isinstance(node, ast.Attribute):
        return False
    if node.attr == "args":
        return _mentions_exception(node.value, caught)
    if node.attr != "message":
        return False
    return _mentions_exception(node.value, caught | {"failure"}) or any(
        isinstance(item, ast.Attribute) and item.attr == "failure" for item in ast.walk(node.value)
    )


def _raw_expression(node: ast.AST, caught: set[str]) -> bool:
    """Recognize direct formatting, exception args and nested failure messages."""
    if isinstance(node, ast.Call):
        name = node.func.id if isinstance(node.func, ast.Name) else None
        method = node.func.attr if isinstance(node.func, ast.Attribute) else None
        return (name in {"str", "repr", "format"} or method == "format") and any(
            _mentions_exception(arg, caught)
            for arg in (*node.args, *(kw.value for kw in node.keywords))
        )
    if isinstance(node, ast.FormattedValue):
        return _mentions_exception(node.value, caught)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
        return _mentions_exception(node.right, caught)
    return _message_attribute(node, caught)


def _forwarding(tree: ast.AST) -> list[str]:
    """Find direct conversions/interpolations and serialized message forwarding.

    This is a review tripwire, not whole-program taint analysis. Exact legacy
    expressions are enumerated with their owner and follow-up, never whole files.
    Logging arguments are the intentional private diagnostic destination.
    """
    caught = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler) and node.name
    }
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    findings: dict[ast.AST, str] = {}
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
            findings[statement] = ast.unparse(statement)
    return sorted(findings.values())


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


@pytest.mark.parametrize(
    "expression",
    [
        "str(cause)",
        "repr(cause)",
        "format(cause)",
        "f'{cause}'",
        "f'{cause!r}'",
        "'{}'.format(cause)",
        "'{err}'.format(err=cause)",
        "'%s' % cause",
        "'%s' % (cause,)",
        "cause.message",
        "cause.args",
        "str(cause.args[0])",
    ],
)
def test_guard_detects_exception_forwarding(expression):
    """The guard must catch arbitrary exception variable names and all direct spellings."""
    tree = ast.parse(
        f"try:\n    work()\nexcept Exception as cause:\n    return View(message={expression})"
    )
    assert _forwarding(tree)


def test_guard_detects_serialized_failure_and_allows_logging():
    assert _forwarding(ast.parse("return View(message=failure.message)"))
    assert not _forwarding(ast.parse("logger.error('cause: %s', failure.message)"))


@pytest.mark.parametrize("expression", ["x.failure.message", "x.result.failure.message"])
def test_guard_detects_chained_messages(expression):
    assert _forwarding(ast.parse(f"return View(message={expression})"))


def test_guard_counts_duplicate_statements_once_per_occurrence():
    tree = ast.parse(
        "try:\n    work()\nexcept Exception as cause:\n    view(str(cause))\n    view(str(cause))"
    )
    assert _forwarding(tree) == ["view(str(cause))", "view(str(cause))"]
    # Multiple raw subexpressions in one statement must not inflate its count.
    assert len(_forwarding(ast.parse("return str(x.failure.message)"))) == 1
