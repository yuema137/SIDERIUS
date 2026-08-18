"""A test may not take its expectation from the thing it is testing.

Three instances of one anti-pattern were found in a single audit
(2026-08-17), which is what justifies a mechanical guard rather than three
fixes:

  * `test_pr07c_validation_pricing.py:701` -- `actual < actual + c`, with
    `c > 0` established two lines above. Necessarily true. Its own comment
    named the mutation it was blind to.
  * `test_observed_subprocess_seam.py:422` --
    `ExperimentRecord.model_fields["gpu_evidence"].default is None`, the
    schema compared to itself.
  * `test_watchdog.py:53` -- `kill_info["survivors_detected"] is False`, a
    value produced by the code under test; deleting the probe and
    hardcoding `False` left it green.

CLAUDE.md already forbids the second form in prose ("Never assert a value
read back from the thing under test"). Prose did not stop three of them, so
this is the executable version.

SCOPE, stated precisely so nobody trusts it further than it goes. This
detects ONE syntactic shape: a comparison whose expected side is a
`model_fields[...]` lookup -- reading a declaration off a Pydantic model and
asserting a value equals it. That is the form that is both unambiguous and
mechanically checkable.

It does NOT detect the tautology form (`x < x + c`) or the
self-reported-value form, because neither is decidable from syntax: `x < x + c`
requires knowing `c > 0`, and "produced by the code under test" requires
knowing what the code under test is. Those two remain review-time rules. A
guard that guessed at them would fire on correct tests and be switched off,
which is how the launcher guard nearly died.

LEGITIMATE uses of `model_fields` are permitted and common:
  * a CROSS-MODEL comparison (`A.model_fields[k].default == B.model_fields[k].default`)
    -- two independent declarations that must agree is a real invariant;
  * an existence or membership check (`"x" in Model.model_fields`);
  * iterating fields to build a case list.
Only "assert <value> == <model_fields lookup>" is refused.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_ROOT = REPO_ROOT / "tests"

#: This module quotes the anti-pattern as test data.
SELF = Path(__file__).resolve()


def _is_model_fields_lookup(node: ast.expr) -> bool:
    """`X.model_fields["k"]`, or an attribute off one (`....default`)."""
    while isinstance(node, ast.Attribute):
        node = node.value
    if not isinstance(node, ast.Subscript):
        return False
    target = node.value
    return isinstance(target, ast.Attribute) and target.attr == "model_fields"


def _model_fields_lookups(node: ast.expr) -> int:
    """How many distinct `model_fields` lookups this expression contains."""
    return sum(
        1
        for child in ast.walk(node)
        if isinstance(child, ast.Subscript)
        and isinstance(child.value, ast.Attribute)
        and child.value.attr == "model_fields"
    )


def _offending_comparisons(tree: ast.AST) -> list[int]:
    """Line numbers of `assert <expr> ==/is <model_fields lookup>` (either side).

    A comparison containing TWO OR MORE lookups is a cross-model agreement
    check and is allowed -- that is a real invariant between two independent
    declarations, not a model compared to itself.
    """
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        for cmp_node in ast.walk(node.test):
            if not isinstance(cmp_node, ast.Compare):
                continue
            if not all(isinstance(op, (ast.Eq, ast.Is)) for op in cmp_node.ops):
                continue
            sides = [cmp_node.left, *cmp_node.comparators]
            if _model_fields_lookups(cmp_node) >= 2:
                continue
            if not any(_is_model_fields_lookup(side) for side in sides):
                continue
            # Comparing a declaration to a LITERAL is the correct form — it is
            # the hardcoded pin every offender should become. Only a
            # declaration compared to another runtime value is refused.
            others = [side for side in sides if not _is_model_fields_lookup(side)]
            if all(isinstance(side, ast.Constant) for side in others):
                continue
            lines.append(cmp_node.lineno)
    return lines


def _scan() -> dict[str, list[int]]:
    offenders: dict[str, list[int]] = {}
    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        if path.resolve() == SELF:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken test fails elsewhere
            continue
        found = _offending_comparisons(tree)
        if found:
            offenders[str(path.relative_to(REPO_ROOT))] = found
    return offenders


def test_no_test_asserts_a_value_against_a_declaration_it_reads() -> None:
    """The guarantee. A default compared to itself passes for ANY default."""
    offenders = _scan()
    detail = "\n".join(f"  {name}:{lines}" for name, lines in sorted(offenders.items()))
    assert not offenders, (
        "These assertions take their expected value from the model under "
        "test, so they pass for any value that model declares. Hardcode the "
        f"expectation instead.\n{detail}"
    )


class TestTheDetectorItself:
    """A guardrail that cannot detect the thing it guards is worse than none."""

    @staticmethod
    def _lines(src: str) -> list[int]:
        return _offending_comparisons(ast.parse(src))

    def test_it_catches_a_default_compared_to_itself(self):
        """The exact shape removed from `test_observed_subprocess_seam.py:422`."""
        assert self._lines('assert record.file_index == Model.model_fields["file_index"].default\n')

    def test_it_catches_the_lookup_on_either_side(self):
        assert self._lines('assert Model.model_fields["x"].default is record.x\n')

    def test_it_permits_a_cross_model_agreement_check(self):
        """Two INDEPENDENT declarations that must agree is a real invariant —
        it is what `test_cross_schema_invariants.py` exists for, and flagging
        it would make this guard the enemy of the thing it protects."""
        assert not self._lines(
            'assert A.model_fields["k"].default == B.model_fields["k"].default\n'
        )

    def test_it_permits_an_existence_check(self):
        assert not self._lines('assert "gpu_evidence" in ExperimentRecord.model_fields\n')

    def test_it_permits_a_hardcoded_expectation(self):
        """The correct form, and the one every offender should become."""
        assert not self._lines('assert TrainConfig.model_fields["epochs"].default == 10\n')

    def test_the_scan_covers_the_corpus(self):
        """Anti-vacuity: if `rglob` returned nothing the guarantee above would
        pass having read no files."""
        assert len(list(TESTS_ROOT.rglob("test_*.py"))) > 100
