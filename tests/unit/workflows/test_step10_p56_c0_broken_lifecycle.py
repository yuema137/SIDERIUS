"""Step 10 / P5+P6 — C0: the SEVERED ``vocab_link_confirmations`` lifecycle.

Design:
``docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
pr_10_p5_6_lifecycle_and_three_task_closure.md`` §13 C0, §2.1.

This module asserts **absence**. Every assertion below records a link of the
carried-state lifecycle that does not exist at the C0 head, so that C1 and C2
are diffs against executable evidence instead of belief.

    schema      OK   InterpretationInput/Output both declare the field
    producer    OK   update_vocab_link_confirmations accumulates
    persistence OK   the output IS the digest
    projection  --   MISSING  -> C1 inverts
    RestoredState  --   MISSING  -> C1 inverts
    ChainState  --   MISSING  -> C2 inverts
    workflow    --   MISSING  -> C2 inverts
    consumer    --   MISSING  -> C2 inverts

**This file is INVERTED by C1/C2, never deleted.** Each assertion carries the
commit that flips it. An inverted assertion is what proves the link was built;
deleting the file would discard the before-picture entirely.

The defect it names, which no other test catches: ``existing_confirmations`` is
always ``{}`` in production, so one iteration appends at most one ``run_name``,
and ``VocabEntry.related_to`` promotion (which needs ``min_runs=3`` DISTINCT
runs) is **unreachable in production**. The only place the carry exists is a
hand-threaded integration test outside CI
(``tests/integration/workflows/test_vocab_accumulation.py`` H.4) — a test
certifying a wiring production does not have.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import fields as dataclass_fields
from pathlib import Path

import core.resume as resume_mod
from core.chain_state import ChainState, chain_state_field_names
from core.resume import RestoredState

REPO_ROOT = Path(__file__).resolve().parents[3]
MODEL_EXPLORATION = REPO_ROOT / "src/workflows" / "model_exploration.py"
RESUME = REPO_ROOT / "src/core" / "resume.py"

FIELD = "vocab_link_confirmations"


def _module_ast(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _digest_payload_reads(tree: ast.Module) -> list[str]:
    """Names of the functions that read ``FIELD`` out of a digest payload.

    Matches both subscript (``data["k"]``) and ``.get("k")`` forms, and the
    membership test that guards them (``"k" in data``), so a second reader
    cannot hide behind a different spelling. Counted over the AST, so a mention
    in a docstring or comment does not register.
    """
    owners: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for sub in ast.walk(node):
            hit = False
            if isinstance(sub, ast.Subscript) and isinstance(sub.slice, ast.Constant):
                hit = sub.slice.value == FIELD
            elif (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "get"
                and sub.args
                and isinstance(sub.args[0], ast.Constant)
            ):
                hit = sub.args[0].value == FIELD
            elif isinstance(sub, ast.Compare) and isinstance(sub.left, ast.Constant):
                hit = sub.left.value == FIELD and any(isinstance(op, ast.In) for op in sub.ops)
            if hit:
                owners.append(node.name)
                break
    return sorted(set(owners))


# ---------------------------------------------------------------------------
# The half C1 builds: projection + RestoredState
# ---------------------------------------------------------------------------


class TestResumeHalfIsMissing:
    """**INVERTED BY C1** (commit "the confirmations projection + RestoredState").

    The three assertions below used to assert ABSENCE. They now assert the
    presence C1 built, and the docstrings record what each replaced — the
    before-picture is preserved here rather than deleted.
    """

    def test_restored_state_now_carries_the_confirmations_field(self):
        """WAS: ``FIELD not in names`` and ``len(names) == 15``."""
        names = {f.name for f in dataclass_fields(RestoredState)}
        assert FIELD in names
        # 15 at C0 -> 16 at C1; issue #396 adds the typed no-records feedback
        # carrier without changing this confirmation field's ownership.
        assert len(names) == 17

    def test_a_fifth_projection_now_produces_the_value(self):
        """WAS: exactly four projections, none for this key."""
        projections = sorted(
            name
            for name, obj in vars(resume_mod).items()
            if name.startswith("project_") and inspect.isfunction(obj)
        )
        assert projections == [
            "project_fingerprint_history",
            "project_knowledge",
            "project_knowledge_cache",
            "project_prediction_memory",
            "project_vocab_link_confirmations",
        ]

    def test_the_projection_is_the_only_non_interpreter_reader(self):
        """WAS: ``FIELD not in RESUME.read_text()``.

        The design's §12.3 constraint: ONE reader of the digest key outside the
        interpreter. `restore_prior_state` must reach it through the projection,
        never by indexing the payload itself.
        """
        source = RESUME.read_text(encoding="utf-8")
        assert f"def project_{FIELD}" in source
        assert f"state.{FIELD} = project_{FIELD}(digest_reads)" in source

        # Exactly ONE site pulls the key out of a digest payload, and it is
        # inside the projection. Counted over the AST so a mention in a
        # docstring or comment cannot satisfy it.
        payload_reads = _digest_payload_reads(_module_ast(RESUME))
        assert payload_reads == [f"project_{FIELD}"], (
            f"the digest key must be read in exactly one function, the "
            f"projection; found it read in {payload_reads}"
        )


# ---------------------------------------------------------------------------
# The half C2 builds: ChainState carrier, workflow seed/closure/input pass
# ---------------------------------------------------------------------------


class TestWorkflowHalfIsMissing:
    """**INVERTED BY C2** (commit "confirmations travel end-to-end").

    As with the resume half, the assertions are inverted in place and each
    docstring records what it replaced.
    """

    CARRIER = "current_vocab_link_confirmations"

    def test_chain_state_now_carries_the_confirmations_map(self):
        """WAS: no ChainState field, ``len(names) == 11``."""
        names = chain_state_field_names()
        assert self.CARRIER in names
        # 11 at C0 -> 12 at C2 (this carrier) -> 13 at C3
        # (`accumulated_key_findings`). Exactly TWO carriers added by this PR,
        # which is what §5's state contract declares.
        assert len(names) == 13
        assert {self.CARRIER, "accumulated_key_findings"} <= names
        assert len(names) == len(dataclass_fields(ChainState))

    def test_the_workflow_now_seeds_passes_and_closes_the_value(self):
        """WAS: ``FIELD not in MODEL_EXPLORATION.read_text()``.

        The three hops the lifecycle needs, each asserted by its own spelling
        so a partial wiring cannot satisfy the whole test.
        """
        source = MODEL_EXPLORATION.read_text(encoding="utf-8")
        # seed: RestoredState -> from_restored
        assert f"restored_{FIELD}=restored_{FIELD}," in source
        # closure: the single-writer census's exact literal
        assert f"state.{self.CARRIER} = " in source
        # consumer: passed into the interpreter's input
        assert f"{FIELD}=dict(state.{self.CARRIER})" in source

    def test_the_production_interpretation_input_now_passes_it(self):
        """WAS: ``FIELD not in keywords``, 19 keywords.

        AST census over the REAL construction site, not a grep. ``run_workflow``
        still builds exactly one ``InterpretationInput``; it now passes the
        carried mapping, so the interpreter no longer receives the schema
        default on every iteration.
        """
        calls = [
            node
            for node in ast.walk(_module_ast(MODEL_EXPLORATION))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "InterpretationInput"
        ]
        assert len(calls) == 1, "expected exactly one production construction site"
        keywords = {kw.arg for kw in calls[0].keywords}
        assert FIELD in keywords
        # 19 at C0 -> 20 at C2 -> 21 at arXiv U3 (declared delta: the
        # interpreter's input gained `baseline_isolation`, the WITHOUT arm's
        # explicit prompt-surface flag — this census fired at final
        # integration, as designed).
        assert len(keywords) == 21

    def test_exactly_two_write_sites_exist_for_the_carrier(self):
        """The §10 rule-4 single-writer contract, for THIS value specifically.

        The generic census (`test_step09_5a_c4_single_writer.py`) proves no
        carried value has a surviving BARE local twin. This asserts the
        positive form the design names: the seed and the one loop closure, and
        nothing else.
        """
        tree = _module_ast(MODEL_EXPLORATION)
        writes = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Attribute) and target.attr == self.CARRIER
        ]
        # The `from_restored` seed is a keyword argument, not an attribute
        # write, so exactly ONE attribute assignment exists: the loop closure.
        assert len(writes) == 1, (
            f"expected exactly one `state.{self.CARRIER} = ...` closure, "
            f"found {len(writes)} at lines {writes}"
        )


# ---------------------------------------------------------------------------
# Legacy / malformed digest payloads — how they behave TODAY (C1's before-picture)
# ---------------------------------------------------------------------------


class TestMalformedPayloadsStayInertForTheFourSIBLINGS:
    """**FLIPPED BY C1**, and deliberately kept afterwards.

    WAS: "malformed payloads are inert *today*, because no reader exists" —
    the before-picture proving C1's ``raise`` is genuinely NEW behaviour rather
    than a pre-existing one.

    NOW: the same payloads must remain inert for the FOUR SIBLING projections.
    C1 added a fail-closed policy for its OWN key; it must not have made the
    other four carry-overs newly brittle. The raise itself is owned by
    ``test_step10_p56_c1_confirmations_projection.py``.
    """

    @staticmethod
    def _reads(payload: dict):
        from core.committed_digests import DigestRead

        return [DigestRead(iter_idx=1, path="/tmp/d.json", status="ok", payload=payload)]

    def test_a_malformed_confirmations_value_raises_nothing_today(self):
        for garbage in (
            "not-a-mapping",
            ["a", "list"],
            {"pair": "a bare string, not a list"},
            {"pair": [1, 2, 3]},
            {7: ["numeric key"]},
        ):
            reads = self._reads({FIELD: garbage, "key_findings": ["kept"]})
            # All four existing projections tolerate it, because none reads it.
            vocab, findings = resume_mod.project_knowledge(reads)
            assert findings == ["kept"]
            assert vocab == []
            assert resume_mod.project_fingerprint_history(reads) == {}
            assert resume_mod.project_knowledge_cache(reads) == {}
            memory = resume_mod.project_prediction_memory(reads)
            assert memory.prediction_outcomes_history == {}

    def test_a_legacy_digest_without_the_key_is_equally_inert(self):
        reads = self._reads({"key_findings": ["legacy finding"]})
        _vocab, findings = resume_mod.project_knowledge(reads)
        assert findings == ["legacy finding"]
