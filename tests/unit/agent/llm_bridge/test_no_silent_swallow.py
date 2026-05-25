"""Static AST guard: ``LLMBridgeContextError`` is never caught.

Per §1.4.2 of ``docs/audit_and_optimize_token_usage_and_growth.md``,
``LLMBridgeContextError`` is uncaught by intent. Catching it inside the
bridge or its callers would silently mask audit-log corruption — the
exact failure mode the design is built to prevent.

This test parses ``agent/llm_bridge.py`` with the standard library
``ast`` module and walks every ``ExceptHandler``. If any handler's
exception type names ``LLMBridgeContextError`` (directly or as part of
a tuple), the test fails with the file location.

Why a static check rather than a runtime test: a runtime test can only
detect the cases it happens to exercise. A future refactor that adds
``except LLMBridgeContextError`` somewhere new would slip past unit
tests but be caught here in seconds.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Resolve the bridge file relative to this test, so the test still works
# when pytest is invoked from anywhere.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_BRIDGE_PATH = _REPO_ROOT / "agent" / "llm_bridge.py"


def _collect_handlers_naming(tree: ast.AST, forbidden_name: str) -> list[tuple[int, str]]:
    """Return [(lineno, source_excerpt)] for every ExceptHandler whose
    type expression names ``forbidden_name``."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        type_node = node.type
        if type_node is None:
            # Bare `except:` — does not name LLMBridgeContextError.
            continue
        # Collect every Name reachable from this type expression.
        for sub in ast.walk(type_node):
            if isinstance(sub, ast.Name) and sub.id == forbidden_name:
                hits.append((node.lineno, ast.unparse(type_node)))
                break
            if isinstance(sub, ast.Attribute) and sub.attr == forbidden_name:
                hits.append((node.lineno, ast.unparse(type_node)))
                break
    return hits


def test_bridge_path_resolves():
    """Sanity: the resolved bridge path exists and is the expected file."""
    assert _BRIDGE_PATH.is_file(), (
        f"Bridge file not found at expected path: {_BRIDGE_PATH}. "
        "Update _REPO_ROOT in this test if the test layout changed."
    )


def test_no_except_llm_bridge_context_error_in_bridge():
    """The bridge module must never catch ``LLMBridgeContextError``."""
    src = _BRIDGE_PATH.read_text()
    tree = ast.parse(src, filename=str(_BRIDGE_PATH))
    hits = _collect_handlers_naming(tree, "LLMBridgeContextError")
    assert not hits, (
        f"Found {len(hits)} forbidden `except LLMBridgeContextError` "
        f"handler(s) in {_BRIDGE_PATH}:\n"
        + "\n".join(f"  line {ln}: except {expr}" for ln, expr in hits)
        + "\nPer §1.4.2, this exception is uncaught by intent. "
        "If the catch is legitimately needed, update the design doc first."
    )


def test_bare_except_does_not_swallow_context_error():
    """A bare ``except:`` or ``except Exception:`` would also swallow our
    ``RuntimeError`` subclass. Flag those so authors think twice.

    This is a *softer* check — bare excepts have legitimate uses (e.g.
    cleanup wrappers). The test asserts that none of the bare/broad
    excepts in the bridge enclose code that calls ``_record_usage`` or
    ``set_run_context``, which are the only methods that can raise
    ``LLMBridgeContextError``.
    """
    src = _BRIDGE_PATH.read_text()
    tree = ast.parse(src, filename=str(_BRIDGE_PATH))

    risky_methods = {
        "_record_usage",
        "set_run_context",
        "_validate_pre_write_locked",
        "_flush_iter_marker_locked",
    }
    bad: list[tuple[int, str]] = []

    def _has_risky_call(node: ast.AST) -> str | None:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                func = sub.func
                if isinstance(func, ast.Attribute) and func.attr in risky_methods:
                    return func.attr
                if isinstance(func, ast.Name) and func.id in risky_methods:
                    return func.id
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            t = handler.type
            is_bare = t is None
            is_broad_exception = isinstance(t, ast.Name) and t.id in {"Exception", "BaseException"}
            if not (is_bare or is_broad_exception):
                continue
            for stmt in node.body:
                hit = _has_risky_call(stmt)
                if hit:
                    bad.append((node.lineno, hit))
                    break
    assert not bad, (
        "Found bare/broad `except` blocks that wrap a call to a method "
        "which can raise LLMBridgeContextError:\n"
        + "\n".join(f"  line {ln}: try-block calls {m}()" for ln, m in bad)
        + "\nNarrow the except clause or hoist the risky call out."
    )
