"""C6.2-C4 — end-to-end test of the prior-stage clamp+backstop orchestrator.

Exercises ``clamp_and_backstop_accumulated`` on a synthetic ``accumulated``
dict mimicking a V12 iter-13 envelope (13 ``ModelComparison`` entries with
near-cap strings, plus realistic ``causal_reasoning`` + ``proposing_stage_errors``
stage outputs and the five input-side keys carrying long strings).

The C2 helpers each have isolated unit tests in ``test_proposal_helpers.py``.
This file's job is to validate the orchestrator's *composition* contract
and to land the **Pre-Commit Checklist item 6 quantitative gate** (≥30%
prompt-char drop on the synthetic iter-13 envelope).

Spec: ``docs/audit_and_optimize_token_usage_and_growth.md`` Commit 6.2-C4.
Spec phrasing note: the original Rev 5 wording for assertion (b) said
"selected entries are the 5 most recent"; the Rev 8.6 pivot replaces this
with the 3-best + 2-recent hybrid. This file asserts the hybrid contract,
matching the C2 attestation under the same Rev 8.6 NOTE.
"""

import copy
import json
from typing import Any

from agent.schemas.proposal import ResearchPolicy
from nodes.ml_model_proposal_agent import _PROPOSER_INPUT_KEYS
from nodes.proposal_helpers import clamp_and_backstop_accumulated

# String long enough to trip the 4000-char backstop floor with margin —
# 5000 chars > default ``ResearchPolicy.prior_stage_max_chars`` (4000).
_LONG_TEXT = "x" * 5000

# Below the floor; verifies the backstop does NOT fire spuriously on
# short strings (the spec says "string leaves above threshold").
_SHORT_TEXT = "kx"


def _comparison_entry(
    model_type: str,
    source: str,
    best_score: float,
    *,
    key_mechanism: str = _LONG_TEXT,
) -> dict[str, Any]:
    """Build one ``ModelComparison``-shaped dict with a long key_mechanism.

    The default 5000-char ``key_mechanism`` ensures the backstop has work
    to do on every retained entry after the top-K clamp; this is what
    drives the ≥30% drop assertion above the naive 13→5 ratio.
    """
    return {
        "model_type": model_type,
        "source": source,
        "best_score": best_score,
        "key_mechanism": key_mechanism,
        "strengths": [],
        "weaknesses": [],
        "lesson_for_next_proposal": _SHORT_TEXT,
    }


def _make_v12_iter13_accumulated() -> dict[str, Any]:
    """Synthetic iter-13 envelope: shape mimics what a real V12 chain saw.

    Score pattern is chosen so the 3-best + 2-recent hybrid produces a
    predictable, non-trivial selection:

      * Top 3 by best_score:           {m03 (5.80), m00 (5.70), m11 (5.65)}
      * Top 2 by recency from
        remainder (m11 deduped):       {m12 (iter 12), m10 (iter 10)}
      * Hybrid union (5 entries):      {m00, m03, m10, m11, m12}

    All 13 entries carry a 5000-char ``key_mechanism`` so the backstop
    fires on the 5 retained entries after the clamp. Non-comparison
    stage outputs (``causal_reasoning``, ``proposing_stage_errors``) and
    the five input-side keys carry long strings too — those test
    backstop coverage and input-side pass-through respectively.
    """
    # Per-entry best_score pattern. Index = iteration; source for m00 is
    # "seed" (iter index 0), the rest are "proposed_iter_N".
    scores = [
        5.70,  # m00 seed
        5.50,  # m01
        5.30,  # m02
        5.80,  # m03  ← top-1 by score
        5.40,  # m04
        5.20,  # m05
        5.10,  # m06
        5.60,  # m07
        5.00,  # m08
        4.90,  # m09
        4.80,  # m10
        5.65,  # m11
        5.55,  # m12
    ]
    comparative_analysis: list[dict[str, Any]] = []
    for idx, score in enumerate(scores):
        source = "seed" if idx == 0 else f"proposed_iter_{idx}"
        comparative_analysis.append(_comparison_entry(f"m{idx:02d}", source, score))

    return {
        # ---- input-side keys (must pass through verbatim) ----
        "candidates": [
            {"model_type": "wavenet", "best_score": 5.6, "long_blob": _LONG_TEXT},
        ],
        "non_candidates_overview": [{"model_type": "rnn", "blob": _LONG_TEXT}],
        "interpretation_summary": {
            "take_home_message": _LONG_TEXT,
            "model_types": ["wavenet", "rnn", "transformer"],
        },
        "existing_model_types": ["wavenet", "rnn", "transformer"],
        "previous_failures": [_LONG_TEXT],
        # ---- non-input stage outputs (subject to clamp+backstop) ----
        "comparison": {
            "comparative_analysis": comparative_analysis,
            "sota_model_type": "m03",
            "sota_score": 5.80,
            "sota_mechanism": _LONG_TEXT,
        },
        "causal_reasoning": {
            "inherited_components": [{"name": "stack", "blob": _LONG_TEXT}],
            "proposed_change": _LONG_TEXT,
            "causal_hypothesis": _LONG_TEXT,
            "falsifiable_prediction": {
                "current_value": 5.80,
                "predicted_value": 6.20,
                "boldness": 0.07,
            },
        },
        "proposing_stage_errors": [_LONG_TEXT, _LONG_TEXT],
    }


class TestIterEnvelopeClampDrop:
    """End-to-end test of clamp_and_backstop_accumulated on a V12 iter-13 fixture.

    These tests close out the C6.2-C4 ladder and the Pre-Commit Checklist
    item 6 quantitative gate.
    """

    # ------------------------------------------------------------------
    # (a) Post-clamp length matches policy.comparative_analysis_top_k
    # ------------------------------------------------------------------

    def test_post_clamp_comparative_analysis_has_top_k_entries(self):
        """Assertion (a) from the C6.2-C4 spec."""
        accumulated = _make_v12_iter13_accumulated()
        policy = ResearchPolicy()  # default top_k=5, max_chars=4000

        clamped = clamp_and_backstop_accumulated(
            accumulated,
            top_k=policy.comparative_analysis_top_k,
            max_chars=policy.prior_stage_max_chars,
            input_keys=_PROPOSER_INPUT_KEYS,
        )

        assert (
            len(clamped["comparison"]["comparative_analysis"]) == policy.comparative_analysis_top_k
        )

    # ------------------------------------------------------------------
    # (b) Selected entries follow the Rev 8.6 3-best + 2-recent hybrid
    # ------------------------------------------------------------------

    def test_selected_entries_follow_3plus2_hybrid_contract(self):
        """Assertion (b) from the C6.2-C4 spec (Rev 8.6 phrasing).

        With the fixture's score pattern:
          * Top 3 by best_score:  {m03 (5.80), m00 (5.70), m11 (5.65)}
          * Top 2 by recency from remainder
            (m11 already taken):  {m12 (iter 12), m10 (iter 10)}
          * Hybrid result:        {m00, m03, m10, m11, m12}
        """
        accumulated = _make_v12_iter13_accumulated()
        policy = ResearchPolicy()

        clamped = clamp_and_backstop_accumulated(
            accumulated,
            top_k=policy.comparative_analysis_top_k,
            max_chars=policy.prior_stage_max_chars,
            input_keys=_PROPOSER_INPUT_KEYS,
        )

        selected_types = {
            entry["model_type"] for entry in clamped["comparison"]["comparative_analysis"]
        }
        assert selected_types == {"m00", "m03", "m10", "m11", "m12"}

    # ------------------------------------------------------------------
    # (c) Quantitative gate: ≥30% prompt-char drop  ← Pre-Commit item 6
    # ------------------------------------------------------------------

    def test_combined_clamp_and_backstop_drops_prompt_chars_by_at_least_30pct(self):
        """Assertion (c) — the Pre-Commit Checklist item 6 quantitative gate.

        ``len(json.dumps(clamped)) / len(json.dumps(raw)) <= 0.7``.

        The naive 13→5 clamp alone produces a >60% drop on the
        ``comparative_analysis`` list; the additional backstop on retained
        entries plus other stage outputs only increases the savings, so
        the ≥30% bar is comfortably cleared.
        """
        accumulated = _make_v12_iter13_accumulated()
        policy = ResearchPolicy()

        clamped = clamp_and_backstop_accumulated(
            accumulated,
            top_k=policy.comparative_analysis_top_k,
            max_chars=policy.prior_stage_max_chars,
            input_keys=_PROPOSER_INPUT_KEYS,
        )

        raw_chars = len(json.dumps(accumulated, default=str))
        clamped_chars = len(json.dumps(clamped, default=str))
        ratio = clamped_chars / raw_chars

        assert ratio <= 0.7, (
            f"Quantitative gate failed: clamped/raw = {ratio:.3f} (>0.7). "
            f"raw_chars={raw_chars}, clamped_chars={clamped_chars}."
        )

    # ------------------------------------------------------------------
    # Bonus: input-side keys pass through verbatim
    # ------------------------------------------------------------------

    def test_input_side_keys_pass_through_verbatim(self):
        """Input-side keys (``_PROPOSER_INPUT_KEYS``) bypass clamp+backstop.

        The input-side context is the caller's responsibility to size;
        this layer must not silently mutate it. Each input-side key's
        long-string payload should be present in the clamped output
        bit-for-bit.
        """
        accumulated = _make_v12_iter13_accumulated()
        policy = ResearchPolicy()

        clamped = clamp_and_backstop_accumulated(
            accumulated,
            top_k=policy.comparative_analysis_top_k,
            max_chars=policy.prior_stage_max_chars,
            input_keys=_PROPOSER_INPUT_KEYS,
        )

        # Every input-side key should be the same object as in the raw
        # input — verbatim pass-through, no recursion, no copy.
        for key in _PROPOSER_INPUT_KEYS:
            assert clamped[key] is accumulated[key], (
                f"Input-side key {key!r} was not passed through verbatim."
            )

        # Spot-check: the long_blob string inside candidates is still 5000 chars.
        long_blob = clamped["candidates"][0]["long_blob"]
        assert isinstance(long_blob, str)
        assert len(long_blob) == 5000

    # ------------------------------------------------------------------
    # Bonus: raw `accumulated` is unmutated after the call
    # ------------------------------------------------------------------

    def test_input_accumulated_not_mutated(self):
        """The live ``accumulated`` is never mutated by the orchestrator.

        Downstream proposer stages must continue reading the full-fidelity
        ``accumulated`` after the prompt assembly view is built. A deep
        snapshot before and after the orchestrator runs must be bit-equal.
        """
        accumulated = _make_v12_iter13_accumulated()
        snapshot = copy.deepcopy(accumulated)
        policy = ResearchPolicy()

        _ = clamp_and_backstop_accumulated(
            accumulated,
            top_k=policy.comparative_analysis_top_k,
            max_chars=policy.prior_stage_max_chars,
            input_keys=_PROPOSER_INPUT_KEYS,
        )

        assert accumulated == snapshot, (
            "clamp_and_backstop_accumulated mutated its input dict — "
            "violates non-mutation contract."
        )
