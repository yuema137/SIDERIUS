"""C12-P-P / W2 — the proposer really executes inside the composition binding.

THE GAP THIS CLOSES
-------------------
P1-A resolves the applicable dataset from the AMBIENT run scope
(``resolve_dataset_profile()``), exactly as C12-P / B3 does. Every P1-A
falsifier and the aggregate invariant bind the composition *themselves*, so
they prove "the proposer renders clean WHEN BOUND". None of them proves that
**production** binds it. If the binding did not enclose the proposer, the
composed run would silently resolve TIDMAD's profile and every other test in
this unit would stay green.

That is a reachability question, and CLAUDE.md requires reachability evidence
for exactly this shape: *a test that fails when the production path bypasses
the boundary.*

WHY THIS IS STRUCTURAL AND NOT A LIVE RUN
-----------------------------------------
The property is lexical containment of a call inside a ``with`` block, which is
fully decided by the source. Driving a real or pseudo chain to observe it would
cost orders of magnitude more and prove the same thing less directly — and the
parent's minimum-semantic-witness policy asks for the smallest production-valid
evidence. Measured cost here: milliseconds, no LLM, no data, no training.

``tests/integration/`` pseudo-mode chains exist and could observe this at
runtime, but they are deliberately excluded from CI, so a guard living there
would not protect the invariant on the branch that matters.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE = REPO_ROOT / "src/workflows" / "model_exploration.py"

_BINDING = "bind_run_task_composition"
_WORKFLOW = "run_workflow"


def _with_items_call_names(node: ast.With) -> set[str]:
    names: set[str] = set()
    for item in node.items:
        call = item.context_expr
        if isinstance(call, ast.Call):
            func = call.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _calls_within(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def test_w2_run_workflow_is_invoked_inside_the_composition_binding() -> None:
    """``run_workflow`` is called from inside a ``with bind_run_task_composition``.

    DEFECT THIS TEST ALONE CATCHES
        The composition binding being moved, narrowed, or dropped so that the
        proposer executes OUTSIDE run scope. P1-A would then resolve TIDMAD's
        profile for every composed run and re-emit TIDMAD's constraint block —
        the exact contamination this unit removed — while every self-binding
        test in the unit stayed green, because they establish the binding
        themselves.

    HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
        No ``with`` statement binding the composition contains a ``run_workflow``
        call, and the assertion says so.

    NOT ASSERTED HERE
        That the *binding value* is correct, or that the proposer is reached on
        any particular iteration. This is containment only — the one thing the
        self-binding tests structurally cannot see.
    """
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))

    enclosing = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.With)
        and _BINDING in _with_items_call_names(node)
        and _WORKFLOW in _calls_within(node)
    ]

    assert enclosing, (
        f"no `with {_BINDING}(...)` block in {MODULE.name} contains a "
        f"`{_WORKFLOW}(...)` call. The proposer would then run OUTSIDE the "
        "composition scope, and P1-A's ambient dataset resolution would fall "
        "back to TIDMAD for every composed task."
    )


def test_w2_the_proposer_is_constructed_inside_run_workflow() -> None:
    """The proposer is instantiated within ``run_workflow``'s own body.

    DEFECT THIS TEST ALONE CATCHES
        The proposer being hoisted out of ``run_workflow`` — e.g. constructed
        by the caller and injected. The containment proof above would still
        pass, while the proposer's ambient reads happened outside the binding.
        The two assertions are only jointly sufficient.

    HOW IT FAILS WHEN THE BEHAVIOUR REGRESSES
        ``MLModelProposalAgent`` no longer appears among the calls inside
        ``run_workflow``.
    """
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    workflow_defs = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == _WORKFLOW
    ]
    assert len(workflow_defs) == 1, f"expected exactly one `{_WORKFLOW}` definition"

    assert "MLModelProposalAgent" in _calls_within(workflow_defs[0]), (
        f"`MLModelProposalAgent` is no longer constructed inside `{_WORKFLOW}`. "
        "If it moved to the caller, verify it is still within the "
        f"`{_BINDING}` scope before relaxing this."
    )
