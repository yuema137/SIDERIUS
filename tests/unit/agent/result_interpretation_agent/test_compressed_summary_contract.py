"""The compressed-summary producer and its consumer, joined.

THE DEFECT (found 2026-08-02 by a test audit, verified against production).

`compress_model_summary` reads `key_findings` from the CACHE ENTRY and
emits it as `one_line_takeaway`. The synthesis-prompt consumer read:

    (A or B) if summary.get("key_findings") else "(no cached takeaway)"

on the compressed dict -- the INPUT's field name checked against the
OUTPUT. `compress_model_summary` returns exactly
`{model_type, best_score, n_rounds, one_line_takeaway}` and never
`key_findings`, so the guard was always falsy and EVERY compressed model
rendered the placeholder. The producer computed a takeaway, truncated it
to the V12 budget, and the consumer threw it away.

WHY NO TEST CAUGHT IT. `TestCompressModelSummary` asserted the producer
returns the right string. The consumer was exercised only with
hand-built payload dicts that already contained `key_findings` -- a
shape the producer never emits. Both sides green, interface broken.
That is the same failure the A5 field-drop taught, and the same reason
`test_preflight_ipc_composition.py` exists.

So every test here runs the REAL producer and feeds its REAL output to
the REAL consumer. No hand-built compressed dicts.
"""

from __future__ import annotations

import pytest

from nodes.interpretation_helpers import compress_model_summary
from nodes.result_interpretation_agent.result_interpretation_agent import (
    _build_synthesis_prompt,
)

#: Cache-entry shapes the producer genuinely accepts. Both `key_findings`
#: forms are live: pre-6.3 wrote list[str], the consolidator writes
#: list[{"statement": ...}].
ENTRY_SHAPES = [
    ("legacy_flat", {"key_findings": ["punet plateaus at 1.8"]}, "punet plateaus at 1.8"),
    (
        "consolidator",
        {"key_findings": [{"statement": "punet plateaus at 1.8"}]},
        "punet plateaus at 1.8",
    ),
    ("legacy_bca_str", {"best_config_analysis": "depth 4 wins"}, "depth 4 wins"),
    ("modern_bca_dict", {"best_config_analysis": {"latest": "depth 4 wins"}}, "depth 4 wins"),
]


def _entry(payload: dict) -> dict:
    return {**payload, "_stats": {"completed_rounds": 3, "best_denoising_score": 1.8}}


def _render(compressed: dict[str, dict]) -> str:
    """Drive the real consumer over real producer output."""
    return _build_synthesis_prompt(
        per_model_summaries=compressed,
        per_model_best={mt: 1.8 for mt in compressed},
        per_model_worst={mt: 1.2 for mt in compressed},
        overall_best_score=1.8,
        overall_worst_score=1.2,
        overall_best_config={},
        compressed_model_types=set(compressed),
    )


class TestTheTakeawayReachesThePrompt:
    """The join. Each case runs producer -> consumer end to end."""

    @pytest.mark.parametrize(
        "label,payload,expected", ENTRY_SHAPES, ids=[e[0] for e in ENTRY_SHAPES]
    )
    def test_a_cached_takeaway_is_rendered(self, label, payload, expected):
        compressed = {"punet": compress_model_summary("punet", _entry(payload))}
        prompt = _render(compressed)
        assert expected in prompt, (
            f"{label}: the producer computed {expected!r} and the consumer did not render it"
        )
        assert "(no cached takeaway)" not in prompt

    def test_the_placeholder_still_appears_when_there_is_genuinely_nothing(self):
        """The negative control. Without it, a consumer that hardcoded the
        takeaway would pass every test above."""
        compressed = {"punet": compress_model_summary("punet", _entry({}))}
        assert "(no cached takeaway)" in _render(compressed)

    def test_the_score_and_round_count_reach_the_prompt_too(self):
        """The other two producer fields travel the same path; if the
        consumer read the wrong name for one, it could for these."""
        compressed = {"punet": compress_model_summary("punet", _entry(ENTRY_SHAPES[0][1]))}
        prompt = _render(compressed)
        assert "1.8" in prompt
        assert "3" in prompt

    def test_each_compressed_model_keeps_its_own_takeaway(self):
        """A shared or last-wins takeaway would still pass a single-model
        test."""
        compressed = {
            "punet": compress_model_summary("punet", _entry({"key_findings": ["punet plateaus"]})),
            "fcnet": compress_model_summary("fcnet", _entry({"key_findings": ["fcnet diverges"]})),
        }
        prompt = _render(compressed)
        assert "punet plateaus" in prompt
        assert "fcnet diverges" in prompt


class TestTheProducerContractTheConsumerRelieson:
    """Pins the field name across the seam, so a rename on either side
    fails here rather than silently rendering the placeholder."""

    def test_the_producer_emits_one_line_takeaway_and_not_key_findings(self):
        out = compress_model_summary("punet", _entry({"key_findings": ["x"]}))
        assert "one_line_takeaway" in out
        assert "key_findings" not in out, (
            "the consumer's old guard checked `key_findings` on this dict; if "
            "the producer ever emits it, that dead branch becomes live again"
        )

    def test_the_producer_field_set_is_exactly_what_the_consumer_reads(self):
        out = compress_model_summary("punet", _entry({"key_findings": ["x"]}))
        assert set(out) == {"model_type", "best_score", "n_rounds", "one_line_takeaway"}

    def test_the_v12_truncation_survives_the_join(self):
        """The producer truncates to max_takeaway_chars. If the consumer
        re-derived the text from somewhere else, the budget would silently
        stop applying to what is actually sent."""
        long_finding = "x" * 500
        out = compress_model_summary("punet", _entry({"key_findings": [long_finding]}), 150)
        assert len(out["one_line_takeaway"]) <= 150
        prompt = _render({"punet": out})
        assert long_finding not in prompt
        assert out["one_line_takeaway"] in prompt


class TestTheV12BudgetAppliesToWhatIsActuallySent:
    """The 200-char budget, measured against production's real line.

    `test_stability_filter.py` used to assert this against a test-local
    format string -- `"- {mt} (best=..., n=...): {takeaway}"` -- while
    production emits `"- **{mt}** (best=..., n_rounds=...): {takeaway}"`,
    ten characters longer. Its docstring claimed to mirror the prompt and
    did not, so the V12 clamp was being verified against a fiction.

    Measuring the rendered prompt instead means the budget cannot drift
    from the renderer again.
    """

    @staticmethod
    def _rendered_line(prompt: str, model_type: str) -> str:
        for line in prompt.splitlines():
            if line.startswith(f"- **{model_type}**"):
                return line
        raise AssertionError(f"no compressed line for {model_type!r} in the prompt")

    def test_an_over_long_finding_still_fits_the_budget(self):
        out = compress_model_summary("punet", _entry({"key_findings": ["x" * 400]}), 150)
        line = self._rendered_line(_render({"punet": out}), "punet")
        assert len(line) <= 200, f"{len(line)} chars: {line}"

    def test_the_budget_covers_the_markup_production_actually_emits(self):
        """The exact gap the old test missed: the `**` and the longer
        `n_rounds=` label are part of what is sent."""
        out = compress_model_summary("punet", _entry({"key_findings": ["x" * 400]}), 150)
        line = self._rendered_line(_render({"punet": out}), "punet")
        assert "**punet**" in line
        assert "n_rounds=" in line
