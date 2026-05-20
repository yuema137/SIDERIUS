"""Unit tests for ``_audit_proposer_components`` (§1.3 of the design doc).

The audit hook produces a per-call char-count breakdown that is written
to ``token_usage.jsonl.components`` so a post-run analysis can localise
prompt bloat to a specific source (system prompt vs. interpretation JSON
vs. agent cards, etc.) before we have a tokenizer that reproduces the
provider's exact split.

Coverage:

1. **Positive** — full ``accumulated`` dict with all blocks populated:
   the returned dict has the 9 documented component keys, and
   ``total_chars`` equals ``sum(components.values())``.
2. **Negative — empty blocks** — when ``vocab_block`` /
   ``agent_cards_block`` / ``expert_context_block`` are empty strings,
   their entries are still present with value ``0`` (no ``KeyError``
   when downstream tooling iterates the breakdown).
3. **Stage name passthrough** — ``stage_name`` lands in the result
   verbatim so the per-row ``label`` and the audit dict agree.
4. **Char accounting** — the candidates_markdown count matches what
   ``build_candidate_markdown_block`` actually produces for the same
   list, so we trust the audit number when blaming a row.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from agent.schemas.proposal import ProposalInput
from nodes.ml_model_proposal_agent import _audit_proposer_components

_EXPECTED_KEYS = {
    "system_prompt",
    "candidates_markdown",
    "interpretation_json",
    "non_candidates_overview",
    "previous_failures",
    "vocab_block",
    "expert_context_block",
    "agent_cards_block",
    "prior_stage_outputs",
    "recent_gate_block",
}


def _make_input(**overrides: Any) -> ProposalInput:
    """Build a ``ProposalInput`` with sensible defaults for these tests.

    Only the fields the audit hook reads are populated; the rest take
    their schema defaults. Tests pass overrides for the specific fields
    they care about.
    """
    base: dict[str, Any] = {
        "interpretation": {"unused_by_audit": True},
        "existing_model_types": ["existing_a", "existing_b"],
        "previous_failures": [],
        "recent_gate_exhaustions": [],
    }
    base.update(overrides)
    return ProposalInput(**base)


def test_audit_components_returns_all_10_keys_with_full_payload():
    inp = _make_input(previous_failures=["err one", "err two longer"])
    accumulated: dict[str, Any] = {
        "candidates": [],  # empty list → markdown helper returns ""
        "interpretation_summary": {
            "foo": "bar",
            "per_model_score_tables": {"heavy": "stripped"},
        },
        # Stage outputs (anything not in _PROPOSER_INPUT_KEYS):
        "comparison": {"stage_data": "output1"},
        "causal_reasoning": {"stage_data": "output2"},
    }
    result = _audit_proposer_components(
        inp=inp,
        accumulated=accumulated,
        agent_cards_block="AGENT_CARDS_X",
        expert_context_block="EXPERT_CTX_Y",
        vocab_block="VOCAB_Z",
        system_prompt="SYS_PROMPT",
        stage_name="comparison",
    )

    assert set(result["components"].keys()) == _EXPECTED_KEYS
    assert result["stage_name"] == "comparison"
    assert result["total_chars"] == sum(result["components"].values())
    # All values are non-negative ints (schema contract).
    for k, v in result["components"].items():
        assert isinstance(v, int) and v >= 0, (k, v)


def test_audit_components_handles_empty_blocks():
    """Negative path: empty/missing blocks must yield value 0 keys, not KeyErrors."""
    inp = _make_input()  # empty previous_failures, recent_gate_exhaustions
    accumulated: dict[str, Any] = {}  # no candidates, no stage outputs
    result = _audit_proposer_components(
        inp=inp,
        accumulated=accumulated,
        agent_cards_block="",
        expert_context_block="",
        vocab_block="",
        system_prompt="",
        stage_name="proposing",
    )

    components = result["components"]
    assert set(components.keys()) == _EXPECTED_KEYS
    # All the optional/empty inputs must collapse to 0:
    for k in (
        "system_prompt",
        "candidates_markdown",
        "previous_failures",
        "vocab_block",
        "expert_context_block",
        "agent_cards_block",
        "recent_gate_block",
    ):
        assert components[k] == 0, f"{k} should be 0 for empty inputs, got {components[k]}"
    # interpretation_json and prior_stage_outputs serialise to the JSON
    # object literal '{}' — 2 chars each — when their inputs are missing.
    assert components["interpretation_json"] == 2
    assert components["prior_stage_outputs"] == 2
    # non_candidates_overview serialises to the JSON list literal '[]' —
    # also 2 chars — when missing/empty (Commit 4.3.3, Rev 8).
    assert components["non_candidates_overview"] == 2
    assert result["total_chars"] == sum(components.values())


def test_audit_components_stage_name_passthrough():
    inp = _make_input()
    for stage_name in ("comparison", "causal_reasoning", "proposing"):
        result = _audit_proposer_components(
            inp=inp,
            accumulated={},
            agent_cards_block="",
            expert_context_block="",
            vocab_block="",
            system_prompt="",
            stage_name=stage_name,
        )
        assert result["stage_name"] == stage_name


def test_audit_components_char_accounting_matches_helpers():
    """The audit-reported counts must match the helpers' actual output.

    Otherwise the ``components`` dict in ``token_usage.jsonl`` lies and
    downstream Top-3 Bloat Reports will blame the wrong source.
    """
    from nodes.proposal_helpers import build_candidate_markdown_block

    fake_candidate = {
        "model_type": "fake_arch",
        "score_table": None,
        "source_code": "class Foo: pass",
        "config": {"hidden": 64},
    }
    accumulated = {"candidates": [fake_candidate]}

    inp = _make_input()
    result = _audit_proposer_components(
        inp=inp,
        accumulated=accumulated,
        agent_cards_block="",
        expert_context_block="",
        vocab_block="",
        system_prompt="",
        stage_name="comparison",
    )

    expected_md_chars = len(build_candidate_markdown_block([fake_candidate]))
    assert result["components"]["candidates_markdown"] == expected_md_chars

    # interpretation_json: missing key → audit reports len("{}") == 2.
    assert result["components"]["interpretation_json"] == 2


def test_audit_components_non_candidates_overview_attributed_separately():
    """Commit 4.3.3 (Rev 8) regression — ``non_candidates_overview`` is its
    own audit key, not pooled into ``prior_stage_outputs``.

    Background: the V12 forensic audit (§8 Commit 4.3.2) showed this single
    field grew from 15 K → 111 K chars across iter 1 → 14 of the explore run,
    contributing 113 % of the false ``template_and_scaffolding`` Δ. Promoting
    it to a named key was the gate that made the per-component breakdown
    trustworthy for Phase 2 surgery.

    Pin three properties of the fix:

    1. The reported value equals ``len(json.dumps(value, default=str))`` —
       the same compact serialisation used for ``interpretation_json`` and
       ``prior_stage_outputs``. Mismatches mean the audit number is lying.
    2. Because ``non_candidates_overview`` is in ``_PROPOSER_INPUT_KEYS``,
       it is excluded from ``prior_stage_outputs``. Otherwise the same
       chars would be double-counted (and the bridge's catch-all clamp
       would kick in, masking real leaks).
    3. The 10-key set is reported (no key dropped, no extra key added).
    """
    overview = [
        {
            "model_type": "fake_arch_a",
            "best_score": -1.5,
            "description": "A fake description string." * 10,
            "key_findings": ["finding-a"] * 5,
        },
        {
            "model_type": "fake_arch_b",
            "best_score": -2.1,
            "description": "Another fake description." * 8,
        },
    ]
    expected_chars = len(json.dumps(overview, default=str))

    inp = _make_input()
    accumulated = {
        "non_candidates_overview": overview,
        # A real stage output to keep ``prior_stage_outputs`` non-trivial:
        "comparison": {"output": "stage_payload_X"},
    }
    result = _audit_proposer_components(
        inp=inp,
        accumulated=accumulated,
        agent_cards_block="",
        expert_context_block="",
        vocab_block="",
        system_prompt="",
        stage_name="proposing",
    )

    components = result["components"]
    # Property 1 — exact char count.
    assert components["non_candidates_overview"] == expected_chars
    # Property 2 — non-overlap with prior_stage_outputs. If the leak were
    # double-counted, prior_stage_outputs would include the overview chars.
    assert components["prior_stage_outputs"] < expected_chars
    # Property 3 — the 10-key contract holds.
    assert set(components.keys()) == _EXPECTED_KEYS


def test_audit_components_total_chars_is_sum_invariant():
    """Property-style: total_chars must always equal sum(components.values()).

    A drift here would mean the audit's headline number and its breakdown
    disagree — exactly the kind of silent bug we're trying to prevent.
    """
    inp = _make_input(previous_failures=["a" * 100, "b" * 50])
    accumulated = {
        "candidates": [{"model_type": "x", "source_code": "y" * 200}],
        "interpretation_summary": {"k": "v" * 30},
        "comparison": {"big": "z" * 500},
    }
    result = _audit_proposer_components(
        inp=inp,
        accumulated=accumulated,
        agent_cards_block="A" * 10,
        expert_context_block="B" * 20,
        vocab_block="C" * 30,
        system_prompt="S" * 40,
        stage_name="proposing",
    )
    assert result["total_chars"] == sum(result["components"].values())
    # And it should be strictly positive given we passed real content.
    assert result["total_chars"] > 0
