"""C12-P / B8 — the latent-risk sentinel for `order_strategy="sequential"`.

**This module fixes nothing. It pins a REACHABILITY ASSUMPTION.**

Operator ruling, 2026-08-24 (C12-P confirmation matrix, §10): finding B8 of
the PR-12e §U.1 register — *"LLM-selectable ``order_strategy='sequential'``
crashes the composed training child"* — is **NOT CURRENTLY REACHABLE**, is
removed from production-fix scope, and must instead carry a narrow sentinel
that *"documents the current reachability assumption … and fails or demands
reconsideration when a future change makes that path reachable."*

Register note: `B8` here is **PR-12e §U.1's** register. PR-12d carries a
DIFFERENT `B0…B11` register in which `B8` means something else entirely.

The latent defect, and why it cannot fire today
-----------------------------------------------
The consumer is genuinely unsound. `execute_tools/train_engine_sandbox.py`
reaches ``cast("TIDMADEpochDataset", dataset).file_row_ranges`` on the
``sequential`` branch. ``typing.cast`` is a runtime no-op and
``file_row_ranges`` is defined on TIDMAD's epoch dataset only, so a
task-owned dataset there raises ``AttributeError``. The source comment says
as much: *"a non-TIDMAD dataset here would fail loudly."*

It cannot fire because the value never crosses the process boundary. In
``core/sandbox_executor.py`` the ``--order_strategy`` argv emission is nested
inside ``if sample_set is not None:`` — the same predicate C12-P records as
cluster B-prime, *a legacy artifact's PRESENCE used as a capability predicate*. A
composed contrast run has ``sample_set is None`` by construction, so the flag
is never emitted and the child's argparse default (``"shuffle"``) applies.

So B8 is masked by a defect C12-P is separately repairing, which is exactly
why it needs a sentinel rather than silence.

What each test here catches, and how it fails
---------------------------------------------
``test_order_strategy_transport_is_still_gated_on_sample_set`` is RED the
moment anyone hoists the argv block out of the ``sample_set`` conditional —
including the recorded D3 transported-scope follow-up, and including a
well-intentioned C12-P cluster-B-prime repair. Its failure is not "you broke
something"; it is *"B8 just became reachable — resolve the unsound cast
before this lands."*

``test_the_sequential_consumer_is_still_unguarded`` is the other half. If it
goes RED, the consumer was fixed and this whole sentinel should be RETIRED
rather than repaired. Without it the first test could keep passing while
guarding a hazard that no longer exists.

Neither test asserts a value read back from the thing under test: the
predicate name, the flag string and the attribute name are all hardcoded.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

SPAWN_MODULE = REPO_ROOT / "src/core" / "sandbox_executor.py"
CHILD_MODULE = REPO_ROOT / "src/execute_tools" / "train_engine_sandbox.py"

#: The argv flag whose transport is the gate on B8's reachability.
ORDER_STRATEGY_FLAG = "--order_strategy"

#: The legacy artifact whose PRESENCE currently serves as the capability
#: predicate. Hardcoded, not derived: the whole point is to notice when the
#: production code stops testing exactly this.
GATING_NAME = "sample_set"

#: The TIDMAD-only attribute the ``sequential`` branch reaches through an
#: unchecked ``cast``.
TIDMAD_ONLY_ATTRIBUTE = "file_row_ranges"


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _enclosing_if_tests(tree: ast.Module, needle: str) -> list[set[str]]:
    """For every statement mentioning ``needle``, the names its enclosing
    ``if`` tests reference.

    Returns one set per occurrence, so an occurrence that is not nested in any
    ``if`` yields an empty set and fails the assertion below rather than being
    silently skipped.
    """
    occurrences: list[set[str]] = []

    def walk(node: ast.AST, guards: tuple[set[str], ...]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.If):
                test_names = {n.id for n in ast.walk(child.test) if isinstance(n, ast.Name)}
                for stmt in child.body:
                    walk_stmt(stmt, (*guards, test_names))
                for stmt in child.orelse:
                    walk_stmt(stmt, guards)
            else:
                walk_stmt(child, guards)

    def walk_stmt(node: ast.AST, guards: tuple[set[str], ...]) -> None:
        if isinstance(node, ast.Constant) and node.value == needle:
            occurrences.append(set().union(*guards) if guards else set())
        if isinstance(node, ast.If):
            walk(ast.Module(body=[node], type_ignores=[]), guards)
            return
        for child in ast.iter_child_nodes(node):
            walk_stmt(child, guards)

    walk(tree, ())
    return occurrences


class TestB8RemainsUnreachable:
    def test_order_strategy_transport_is_still_gated_on_sample_set(self) -> None:
        """B8's reachability assumption, pinned.

        RED means the flag now crosses the process boundary on a route where
        ``sample_set`` is absent — i.e. a composed task can reach the
        ``sequential`` branch and its unchecked TIDMAD cast.
        """
        occurrences = _enclosing_if_tests(_parse(SPAWN_MODULE), ORDER_STRATEGY_FLAG)

        assert occurrences, (
            f"{SPAWN_MODULE.name} no longer emits {ORDER_STRATEGY_FLAG!r} at all. "
            f"This sentinel can no longer see the transport it exists to watch — "
            f"re-derive B8's reachability rather than deleting this test."
        )
        ungated = [i for i, names in enumerate(occurrences) if GATING_NAME not in names]
        assert not ungated, (
            f"{ORDER_STRATEGY_FLAG!r} is emitted from {len(ungated)} site(s) in "
            f"{SPAWN_MODULE.name} that are NOT gated on {GATING_NAME!r}.\n\n"
            f"B8 (PR-12e §U.1 register) has just become REACHABLE. A composed "
            f"non-TIDMAD run can now transport order_strategy='sequential' to the "
            f"training child, where {CHILD_MODULE.name} reaches "
            f'cast("TIDMADEpochDataset", dataset).{TIDMAD_ONLY_ATTRIBUTE} and '
            f"raises AttributeError.\n\n"
            f"This is expected to fire when the cluster-B-prime repair hoists the argv "
            f"block, or when the recorded D3 transported-scope follow-up lands. "
            f"Do NOT silence it: resolve the sequential consumer first "
            f"(refuse 'sequential' parent-side with recorded provenance, or "
            f"replace the cast with an explicit refusal), then retire this test."
        )

    def test_the_sequential_consumer_is_still_unguarded(self) -> None:
        """The other half: the hazard this sentinel guards still exists.

        RED means the consumer was made safe, so the reachability assumption
        above no longer protects anything and this module should be RETIRED.
        Without this test the sentinel could pass forever while guarding
        nothing — the vacuity shape that let B8 be mis-reported as an active
        intermittent defect in the first place.
        """
        source = CHILD_MODULE.read_text(encoding="utf-8")
        assert TIDMAD_ONLY_ATTRIBUTE in source, (
            f"{CHILD_MODULE.name} no longer reaches {TIDMAD_ONLY_ATTRIBUTE!r}. "
            f"The B8 hazard appears to be gone; RETIRE this sentinel module "
            f"rather than adjusting it."
        )


@pytest.mark.parametrize("path", [SPAWN_MODULE, CHILD_MODULE])
def test_sentinel_file_set_is_real(path: Path) -> None:
    """Non-vacuity: a census that cannot open its own file set is green for
    the wrong reason (F-12bc-9 / F-P2b-4, this repository, twice)."""
    assert path.is_file(), f"{path} does not exist in this checkout"
