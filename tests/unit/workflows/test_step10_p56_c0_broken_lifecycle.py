"""Unrelated resume projections tolerate missing or malformed confirmation payloads.

The digest-reader helper also supports the mutation witness in resume-equality tests."""

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
