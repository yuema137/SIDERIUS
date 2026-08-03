"""The pre-flight status vocabulary, guarded at the seam that has no guard.

A status string crosses three seams on its way from the measurement to the
decision:

    wrapper.run_skill      "host_memory"
      -> _classify         HOST_MEMORY_ALLOCATION_FAILURE
      -> adapt_result      ("host_memory", <no feasible key>)
      -> the tuner         PREFLIGHT_CONSUMER_ACTIONS["host_memory"]

Two of those seams already fail closed. `preflight_adapter` calls
`_assert_mapping_is_exhaustive()` at import, so an outcome with no legacy
row cannot even be imported. `test_preflight_outcome_consumption.py` asserts
every adapter status has a consumer action.

THE FIRST SEAM HAS NO SUCH GUARD, and it fails OPEN. `_classify` is a chain
of `if status == "...":` returns with a trailing block that builds
`COMPLETED_MEASUREMENT` / `MEASURED_PEAK_ABOVE_VRAM_CAP` from whatever is
left. An unrecognised status does not raise -- it is reported as a
successful measurement. Rename `"host_memory"` in `wrapper.py` and a
host-memory kill becomes a completed verdict about the candidate, which is
#156's shape one layer upstream and worse: #156 refused to conclude,
this concludes wrongly.

Both sides are read from the AST rather than by text search. A source
search would match the status names in this module's own docstring, and in
`_classify`'s comments -- the mistake that made an earlier guard in this
suite pass against its own prose.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from agent.skills.evaluate_vram_skill import preflight_worker_main, wrapper

#: `_classify` deliberately lets this one fall through to the trailing
#: block: a successful measurement is exactly what that block is for. Every
#: other status must have its own branch.
INTENTIONAL_FALLTHROUGH = {"success"}


def _status_values(node: ast.AST) -> set[str]:
    """Constant strings a ``"status": <node>`` entry can evaluate to.

    Handles the ternary at `wrapper.py:744` by taking its two RESULTS and
    not its condition -- walking the whole node would collect ``"cuda"``
    from `memory_kind == "cuda"` and report a status that does not exist.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return _status_values(node.body) | _status_values(node.orelse)
    return set()


def _statuses_the_skill_emits() -> set[str]:
    tree = ast.parse(Path(wrapper.__file__).read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            if isinstance(key, ast.Constant) and key.value == "status":
                found |= _status_values(value)
    return found


def _statuses_classify_branches_on() -> set[str]:
    tree = ast.parse(Path(preflight_worker_main.__file__).read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_classify")
    found: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name):
            if node.left.id != "status":
                continue
            for comparator in node.comparators:
                if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
                    found.add(comparator.value)
    return found


class TestTheSkillToClassifySeam:
    def test_every_status_the_skill_emits_has_an_explicit_branch(self):
        """The guard this seam was missing.

        Fails when `wrapper.run_skill` gains a status, or renames one, that
        `_classify` does not branch on -- before that status can be
        misreported as a completed measurement.
        """
        emitted = _statuses_the_skill_emits()
        handled = _statuses_classify_branches_on()

        assert emitted, "AST extraction found no statuses; the shape of wrapper.py changed"

        unhandled = sorted(emitted - handled - INTENTIONAL_FALLTHROUGH)
        assert unhandled == [], (
            f"run_skill can emit {unhandled}, and _classify has no branch for "
            "them. They fall through to the trailing block and are reported "
            "as COMPLETED_MEASUREMENT -- a success verdict about the "
            "candidate, produced by a failure that was never about it."
        )

    def test_classify_does_not_branch_on_a_status_the_skill_cannot_emit(self):
        """The other direction. A branch for a status nobody produces is
        dead policy that reads as coverage -- and it hides the rename that
        orphaned it, because the seam still looks exhaustive."""
        orphaned = sorted(_statuses_classify_branches_on() - _statuses_the_skill_emits())
        assert orphaned == [], (
            f"_classify branches on {orphaned}, which run_skill never emits; "
            "either the skill was renamed out from under it or the branch is "
            "dead"
        )

    @pytest.mark.parametrize("status", ["host_memory", "timeout", "inconclusive"])
    def test_a_refusal_status_is_never_reported_as_a_measurement(self, status):
        """Reachability for the consequence, not just the table.

        Each of these means "nothing was measured". If `_classify` ever
        stops recognising one, this asserts on the OUTCOME rather than on
        the branch list, so it fails even if both AST checks above were
        deleted.
        """
        classified = preflight_worker_main._classify({"status": status, "message": "m"})
        assert classified["outcome"] not in {
            "COMPLETED_MEASUREMENT",
            "MEASURED_PEAK_ABOVE_VRAM_CAP",
        }, f"{status!r} was reported as a measurement of the candidate"

    def test_an_unknown_status_is_reported_as_a_completed_measurement(self):
        """Documents the hazard the first test guards, so the reason is not
        just a claim in a docstring.

        This is CURRENT production behaviour and is not a defect on its own
        -- the trailing block cannot distinguish "success" from "a status I
        do not know". It is why the exhaustiveness check has to live at the
        seam rather than relying on a runtime default.
        """
        classified = preflight_worker_main._classify({"status": "some_future_status"})
        assert classified["outcome"] == "COMPLETED_MEASUREMENT"
