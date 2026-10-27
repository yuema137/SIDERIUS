"""Step 09.5a C4 — Amendment C: exactly ONE writable authority per carried value.

The operator's amendment names the failure this file exists to prevent:

```text
old local x mutates;
state.x also mutates;
synchronisation glue keeps them "in agreement."
```

That is duplicate authority with a keeper — A-1 reproduced inside the PR that
exists to remove it. Nothing behavioural would notice while the two agree, and
by the time they disagree the cause is a hundred lines away.

Defect only this file catches: a cross-iteration value acquiring a second
writer. Behavioural tests read the value's final state, which is identical
whether one writer or two produced it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from core.chain_state import chain_state_field_names

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / "src/workflows" / "model_exploration.py"
# The completed-body history policy `run_workflow` delegates to; it owns most
# carrier writes since the finite-loop extraction (PR #940).
HISTORY = REPO_ROOT / "src/workflows" / "research_history.py"
HISTORY_ENTRYPOINT = "advance_completed_history"


def _function_ast(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)


def _run_workflow_ast() -> ast.FunctionDef:
    return _function_ast(WORKFLOW, "run_workflow")


def _carrier_writes(fn: ast.FunctionDef) -> set[str]:
    """Carried fields assigned as ``state.<field>`` inside ``fn``'s own body."""
    carried = chain_state_field_names()
    out: set[str] = set()
    for node in ast.walk(fn):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        for t in targets:
            if (
                isinstance(t, ast.Attribute)
                and isinstance(t.value, ast.Name)
                and t.value.id == "state"
                and t.attr in carried
            ):
                out.add(t.attr)
    return out


def _bare_local_writes(fn: ast.FunctionDef) -> dict[str, list[int]]:
    """Assignments to a BARE name that ``ChainState`` also declares.

    A bare `x = ...` alongside a live `state.x = ...` is the duplicate-writer
    shape. Attribute writes (`state.x = ...`) are the carrier's own and are not
    counted here.
    """
    carried = chain_state_field_names()
    out: dict[str, list[int]] = {}
    for node in ast.walk(fn):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        elif isinstance(node, (ast.For, ast.comprehension)):
            targets = [node.target]
        for t in targets:
            for name in ast.walk(t):
                if isinstance(name, ast.Name) and name.id in carried:
                    out.setdefault(name.id, []).append(getattr(node, "lineno", -1))
    return out


class TestSingleWriter:
    def test_no_carried_value_has_a_surviving_bare_local_writer(self):
        """Amendment C, at THIS milestone — not merely at the end of the PR."""
        offenders = _bare_local_writes(_run_workflow_ast())
        assert not offenders, (
            "these cross-iteration values are written both as a bare local and "
            f"through ChainState: {offenders}. Exactly one writable authority "
            "per carried value — synchronising two is the duplicate-authority "
            "shape this milestone removes."
        )

    def test_the_carrier_is_actually_written_in_the_loop(self):
        """Anti-vacuity: a workflow that stopped writing state entirely would
        satisfy the check above.

        Carrier writes live in `run_workflow` and in the history policy it
        calls; only writes inside those two function bodies count, so a write
        moved into a helper the loop never reaches does not keep this green.
        """
        run_workflow = _run_workflow_ast()
        calls = [
            n
            for n in ast.walk(run_workflow)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == HISTORY_ENTRYPOINT
        ]
        assert len(calls) == 1, f"run_workflow must call {HISTORY_ENTRYPOINT} exactly once"
        written = _carrier_writes(run_workflow) | _carrier_writes(
            _function_ast(HISTORY, HISTORY_ENTRYPOINT)
        )
        assert len(written) >= 5, (
            f"only {sorted(written)} are written through the carrier — if the "
            "loop legitimately stopped mutating the rest, re-derive this floor"
        )

    @pytest.mark.parametrize("field", sorted(chain_state_field_names()))
    def test_every_carried_field_is_reachable_from_the_workflow(self, field):
        """A carrier field nothing reads is state with no consumer."""
        src = WORKFLOW.read_text(encoding="utf-8")
        assert f"state.{field}" in src, (
            f"ChainState declares {field} but run_workflow never touches it"
        )

    def test_the_detector_catches_a_planted_second_writer(self):
        """The guard must bite. Planting a bare local write for a carried value
        into a copy of the function must be detected."""
        carried = sorted(chain_state_field_names())[0]
        planted = ast.parse(
            f"def run_workflow():\n"
            f"    state = None\n"
            f"    {carried} = []\n"
            f"    state.{carried} = {carried}\n"
        )
        fn = next(n for n in ast.walk(planted) if isinstance(n, ast.FunctionDef))
        assert _bare_local_writes(fn) == {carried: [3]}
