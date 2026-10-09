"""Flag OFF preserves the reasoning baseline without exposing health evidence.

CB4-a (``pr3_healthgate_feedback.md`` §3.7, CB4 spec §3/§5). The golden
was rendered at commit ``2052fa2`` (clean tree, before the proposer
renderer knew about structured health evidence) from the STRONG fixture:
the interpretation dict is the real ``model_dump`` of a typed
``InterpretationOutput`` carrying ``per_model_round_health_counts``,
``per_model_collapse_fingerprints``, and ``collapse_fingerprint_history``
for two disjoint models, plus §14.N gate-exhaustion data. So parity is
asserted with the structured fields PRESENT and the flag OFF — by exact
full-string equality, never by absence of the new block alone.
The #685 native budget-context prefix is included; the earlier health and
interpretation content remains unchanged.
"""

from pathlib import Path

from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
    _build_reasoning_prompt,
    _format_recent_gate_exhaustions_block,
)
from tests.unit.agent.ml_model_proposal_agent._health_feedback_fixtures import (
    SIG_A,
    SIG_B,
    gate_exhaustion,
    strong_proposal_input,
)

GOLDEN = Path(__file__).parent / "goldens" / "reasoning_prompt_structured_evidence.txt"


def test_flag_off_reasoning_prompt_byte_identical(tmp_path):
    inp = strong_proposal_input("/tmp/cb4_golden_ws")
    # The structured fields ARE in the evidence (strong form)…
    #
    # Step 10 / P3 C3 (guard disposition G9): these two probes used to subscript
    # ``inp.interpretation`` as a raw dict. That field no longer exists — the
    # evidence is typed — so they now read the typed carriers. The CLAIM is
    # unchanged and is the load-bearing half of this test: the golden below
    # would pass vacuously on a payload that simply had no health evidence to
    # leak, so the probes exist to prove there IS evidence and the flag alone
    # is what suppresses it.
    assert (inp.interpretation_evidence.per_model_collapse_fingerprints or {})["model_a"]
    assert (inp.interpretation_evidence.collapse_fingerprint_history or {})["model_b"]
    # …and the flag is OFF by default.
    prompt = _build_reasoning_prompt(inp)
    assert prompt == GOLDEN.read_text()


def test_flag_off_no_evidence_leakage(tmp_path):
    prompt = _build_reasoning_prompt(strong_proposal_input("/tmp/cb4_golden_ws"))
    assert "[HEALTHGATE EVIDENCE]" not in prompt
    assert SIG_A not in prompt and SIG_B not in prompt
    assert "Representative observation" not in prompt


def test_gate_exhaustion_block_pinned():
    """§14.N regression anchor: the exhaustion block renders identically
    from the same fixture — asserted standalone so a CB4 change to it is
    caught even if the surrounding prompt shifts."""
    block = _format_recent_gate_exhaustions_block([gate_exhaustion()])
    assert block  # non-empty on populated input
    assert block in GOLDEN.read_text()
