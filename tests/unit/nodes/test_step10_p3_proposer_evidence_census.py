"""Step 10 / P3 — the standing census over the proposer's interpretation reads.

Design: ``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p3_proposer_typed_evidence.md`` §7 C0 (this baseline), §7 C2 (the count
drops to the legacy remainder), §7 C3 (the count reaches ZERO and this becomes
a standing guard), §8.1 (the "both entrypoints read one authority" claim).

What this owns
--------------
Parent §11.2's acceptance is an EXECUTABLE rule: *no new evidence field may
ever again need wiring into two readers*. Before P3 the proposer mined a raw
``dict[str, Any]`` in two independent readers plus the helpers, so "there is
one reader now" was a prose claim nobody could check. This module turns it
into a number.

The number is deliberately a hardcoded inventory rather than a "<= previous"
bound: the migration's whole point is that each commit moves it for a stated
reason, and a bound that only shrinks would let C2 silently leave a read
behind. Every change to :data:`EXPECTED_RAW_READS` must arrive in the commit
that removes the reads, with the removal visible in the same diff.

Why AST and not grep
--------------------
``grep`` for ``interpretation.get(`` also matches a comment, a docstring, a
test-fixture string and ``interp_summary.get(``. The scan below asks the parser
for the two shapes that ARE a raw semantic read of the interpretation mapping —
``<name>.get(...)`` and ``<name>[...]`` where the accessed name is ``interp`` or
``interpretation`` — so prose cannot inflate the count and a comment cannot
create one.

What it does NOT catch, stated so nobody trusts it further than it goes: an
ALIAS. ``d = inp.something`` followed by ``d.get("per_model_best")`` is invisible
here, because the census is name-shaped by design rather than a dataflow
analysis. That hole is closed by the STRUCTURAL half below
(:meth:`TestTheRawReaderInventory.test_the_raw_carrier_no_longer_exists_to_read`):
after C3 there is no raw interpretation field on ``ProposalInput`` at all, so
there is nothing for an alias to be bound FROM. The two halves are load-bearing
together and neither is sufficient alone.

Scope note: the scanned set is the proposer's OWN modules. The projection
authority (``agent/schemas/proposer_evidence.py``) legitimately reads the raw
mapping — that is its entire job — and is not scanned here; the census that
keeps it single is :func:`test_the_projection_authority_is_not_duplicated`
in the C1 module.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The proposer's own modules — the surface parent §11.2 talks about.
PROPOSER_MODULES: tuple[str, ...] = (
    "src/nodes/ml_model_proposal_agent/ml_model_proposal_agent.py",
    "src/nodes/proposal_helpers.py",
)

#: Names that, when subscripted or ``.get()``-ed, ARE a raw read of the
#: serialized interpretation. Both spellings are live in production today:
#: the legacy reader and the health block bind ``interp``; the helpers, the
#: pipeline (``inp.interpretation``) and the CLI use ``interpretation``.
RAW_INTERPRETATION_NAMES = frozenset({"interp", "interpretation"})

#: The measured inventory — now the TERMINAL state.
#:
#: At the P3 base ``c5f95ff0``:
#:   node module 40 = health block 4 + legacy reader 26 + run() banner 1
#:                  + pipeline 7 + standalone CLI 2
#:   helpers    12 = _interpretation_order 1 + select_candidate_models 9
#:                  + resolve_exploration_mode 2
#: After C2:  28 + 0  (pipeline, helpers, health block and banner typed)
#: After C3:  **0 + 0** — this state.
#:
#: From here this is a STANDING GUARD, not a migration counter. Any
#: ``interpretation.get(`` / ``interpretation[`` appearing in a proposer module
#: is a bypass of the typed boundary and turns this RED. It is also belt AND
#: braces: ``ProposalInput`` no longer HAS a raw interpretation field, so a
#: bypass has no input to read — but a future field could reintroduce one, and
#: the census is what would notice.
EXPECTED_RAW_READS: dict[str, int] = {
    "src/nodes/ml_model_proposal_agent/ml_model_proposal_agent.py": 0,
    "src/nodes/proposal_helpers.py": 0,
}


def _accessed_name(node: ast.expr) -> str | None:
    """The last identifier of a ``Name``/``Attribute`` chain, else ``None``.

    ``interpretation`` -> ``"interpretation"``; ``inp.interpretation`` ->
    ``"interpretation"``; ``self.foo()`` -> ``None`` (a call, not a carrier).
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def raw_interpretation_reads(source: str) -> list[str]:
    """Every ``<interp>.get(...)`` / ``<interp>[...]`` site, as ``line: text``."""
    tree = ast.parse(source)
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and _accessed_name(node.func.value) in RAW_INTERPRETATION_NAMES
        ):
            hits.append((node.lineno, ast.unparse(node)))
        elif (
            isinstance(node, ast.Subscript)
            and _accessed_name(node.value) in RAW_INTERPRETATION_NAMES
        ):
            hits.append((node.lineno, ast.unparse(node)))
    return [f"{line}: {text[:110]}" for line, text in sorted(hits)]


def _read_module(rel: str) -> str:
    path = REPO_ROOT / rel
    assert path.is_file(), (
        f"the census names {rel!r}, which does not exist. A scanned file that "
        "silently disappears turns this census into a test that passes because "
        "it looked at nothing."
    )
    return path.read_text(encoding="utf-8")


class TestTheRawReaderInventory:
    """The count is the claim; the plant proves the count can move."""

    @pytest.mark.parametrize("rel", PROPOSER_MODULES)
    def test_the_raw_read_count_is_exactly_the_recorded_inventory(self, rel: str) -> None:
        reads = raw_interpretation_reads(_read_module(rel))
        expected = EXPECTED_RAW_READS[rel]
        assert len(reads) == expected, (
            f"{rel}: {len(reads)} raw interpretation reads, inventory says "
            f"{expected}. If a commit removed reads, update EXPECTED_RAW_READS "
            f"in that same commit. If a commit ADDED one, it bypassed the typed "
            f"evidence boundary (parent §11.2) — that is the defect this census "
            f"exists to catch.\n" + "\n".join(reads)
        )

    def test_the_raw_carrier_no_longer_exists_to_read(self) -> None:
        """The census reaching zero is only half of C3's claim.

        A count of zero could also mean "nobody happens to read it today". The
        stronger fact is structural: ``ProposalInput`` has no raw interpretation
        field and no dead typed mirror, so there is nothing left to bypass the
        projection WITH. Asserted here beside the count so the two claims cannot
        drift apart.
        """
        from agent.schemas.proposal import ProposalInput

        assert "interpretation" not in ProposalInput.model_fields
        assert "per_model_score_tables" not in ProposalInput.model_fields
        assert ProposalInput.model_fields["interpretation_evidence"].is_required(), (
            "the typed evidence must be REQUIRED — an optional field would let "
            "a caller construct an input that skipped the projection entirely"
        )

    def test_the_scanned_set_is_the_whole_proposer_surface(self) -> None:
        """A module that is not scanned is not guarded.

        Both keys must be present in both structures, so adding a module to
        one and forgetting the other cannot silently narrow the census.
        """
        assert set(PROPOSER_MODULES) == set(EXPECTED_RAW_READS)

    @pytest.mark.parametrize(
        "planted",
        [
            'x = interpretation.get("per_model_best")',
            'x = interp.get("model_types")',
            'x = interpretation["metric_identity"]',
            'x = inp.interpretation.get("key_findings")',
            'x = self.interpretation["bottlenecks"]',
        ],
    )
    def test_a_planted_raw_read_is_caught(self, planted: str) -> None:
        """Anti-vacuity: each production shape the census claims to see.

        Planted into the REAL module source rather than a toy snippet, so the
        proof is about this file's scanner running over this repository's code.
        """
        source = _read_module("src/nodes/proposal_helpers.py")
        baseline = len(raw_interpretation_reads(source))
        assert baseline == 0, "the module is expected to be clean before planting"
        planted_count = len(
            raw_interpretation_reads(source + f"\n\ndef _planted():\n    {planted}\n")
        )
        assert planted_count == baseline + 1, (
            f"the census did not see a planted raw read of the shape {planted!r} "
            "— it is green for a narrower reason than it claims"
        )

    def test_an_unrelated_mapping_read_is_not_counted(self) -> None:
        """Precision: the census is about the interpretation carrier only.

        ``accumulated.get(...)``, ``entry["signature"]`` and
        ``interp_summary.get(...)`` are legitimate dict reads on other
        objects. A census that counted them would be noise nobody keeps
        green, and would hide a real read inside a large number.
        """
        source = _read_module("src/nodes/proposal_helpers.py")
        baseline = len(raw_interpretation_reads(source))
        noise = (
            "\n\ndef _noise(accumulated, entry, interp_summary):\n"
            '    a = accumulated.get("candidates")\n'
            '    b = entry["signature"]\n'
            '    c = interp_summary.get("model_types")\n'
            "    return a, b, c\n"
        )
        assert len(raw_interpretation_reads(source + noise)) == baseline
