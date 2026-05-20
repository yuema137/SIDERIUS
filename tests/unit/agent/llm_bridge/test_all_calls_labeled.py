"""Static AST guard: every ``bridge.<method>(...)`` call site has ``label=``.

Per §1.5 of ``docs/audit_and_optimize_token_usage_and_growth.md``, every
LLM call routed through ``LLMBridge`` must pass a stable ``label=``
kwarg so each row in ``token_usage.jsonl`` can be attributed to a
specific prompt site. Calls that fall back to the default
``label="unlabeled"`` emit a one-line stderr warning at runtime, but
that warning is observable only in test logs / chain_log.txt — it is
easy to introduce a new unlabeled site by accident.

This test parses every file under ``nodes/`` with the standard library
``ast`` module and walks every ``Call`` node whose function expression
matches ``<...>.bridge.{generate,generate_text,tool_call}``. If any
such call lacks a ``label=`` keyword, the test fails with file +
line numbers.

Why a static check rather than a runtime test: a runtime test only
exercises the call sites it happens to hit. A future refactor that
adds a new node calling ``bridge.generate(...)`` without a label would
slip past unit tests but be caught here in seconds.

Scope: ``nodes/`` only. The bridge's own internal call sites (e.g.
``self.generate(..., label="tuner.planner")`` inside ``plan()``) are
exercised by the bridge's own tests; this guard targets the agent
layer where new nodes get added.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_NODES_DIR = _REPO_ROOT / "nodes"

# Methods on the bridge that must always carry a label= kwarg. Mirrors
# the public API exposed in agent/llm_bridge.py (generate / generate_text
# / tool_call). reflect/plan are internal sites already labeled by the
# bridge itself in Commit 1.
_LABEL_REQUIRED_METHODS = {"generate", "generate_text", "tool_call"}


def _is_bridge_call(call: ast.Call) -> bool:
    """Return True iff ``call`` looks like ``<expr>.bridge.<method>(...)``.

    Matches both ``self.bridge.generate(...)`` and the rarer
    ``brain.bridge.generate(...)`` pattern. Does not match plain
    ``self.generate(...)`` calls inside the bridge module itself, which
    are deliberately out of scope.
    """
    func = call.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr not in _LABEL_REQUIRED_METHODS:
        return False
    parent = func.value
    if not isinstance(parent, ast.Attribute):
        return False
    return parent.attr == "bridge"


def _collect_unlabeled_bridge_calls(path: Path) -> list[tuple[int, str]]:
    """Return [(lineno, method_name)] for every bridge call in ``path``
    that lacks a ``label=`` keyword."""
    src = path.read_text()
    tree = ast.parse(src, filename=str(path))
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_bridge_call(node):
            continue
        kwargs = {kw.arg for kw in node.keywords if kw.arg is not None}
        if "label" not in kwargs:
            hits.append((node.lineno, node.func.attr))
    return hits


def test_nodes_dir_resolves():
    """Sanity: the resolved nodes directory exists at the expected path."""
    assert _NODES_DIR.is_dir(), (
        f"nodes/ not found at expected path: {_NODES_DIR}. "
        "Update _REPO_ROOT in this test if the test layout changed."
    )


def test_every_bridge_call_in_nodes_has_label_kwarg():
    """No bridge.generate / generate_text / tool_call without label=."""
    offenders: list[tuple[Path, int, str]] = []
    for py_file in sorted(_NODES_DIR.rglob("*.py")):
        for lineno, method in _collect_unlabeled_bridge_calls(py_file):
            offenders.append((py_file, lineno, method))

    assert not offenders, (
        f"Found {len(offenders)} bridge call(s) under nodes/ without a "
        f"`label=` kwarg. Per §1.5, every LLM call must be labeled so "
        f"`token_usage.jsonl` rows can be attributed to a specific prompt "
        f"site:\n"
        + "\n".join(
            f"  {p.relative_to(_REPO_ROOT)}:{ln}: bridge.{m}(...)" for p, ln, m in offenders
        )
        + '\nAdd a stable label string (e.g. `label="interpretation.synthesis"`).'
    )
