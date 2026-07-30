"""C2 — prompt-contamination guard (§11/§17.2 of the runtime design).

Contract (docs/design/runtime_estimation_and_calibration.md §23-C2,
finding F-2): the SYSTEM must never compel or author an unqualified
parameter-count ceiling in proposer prompts.

* No prompt template or template constant may MANDATE a parameter-count
  limit in ``expert_advice.constraints`` (the VRAM-limit requirement
  stays — VRAM capacity is deterministic hardware arithmetic).
* The gate-exhaustion block's single-entry guidance is provenance-
  qualified (pre-attempt gate estimates may be uncalibrated), prefers
  workload-plan adjustment over capacity reduction, and explicitly
  forbids deriving a permanent parameter-count ceiling.
* The multi-entry family-switch signal (repeated measured exhaustion)
  is retained — that is legitimate evidence-based guidance.

These guards operate on the REAL template constants and the REAL
renderer output, so a regression that reintroduces the mandate anywhere
on the audited surfaces fails loudly.
"""

from __future__ import annotations

import re
from pathlib import Path

from agent.prompt_templates.proposal import load_stage_prompt
from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
    PROPOSAL_COMMIT_PROMPT,
    _format_recent_gate_exhaustions_block,
)
from tests.unit.agent.ml_model_proposal_agent._health_feedback_fixtures import (
    gate_exhaustion,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
TEMPLATE_DIR = REPO_ROOT / "agent" / "prompt_templates" / "proposal"

# The retired mandate, in every observed phrasing.
_MANDATE_PATTERNS = [
    r"one parameter count limit",
    r"must include at least one VRAM limit and one parameter",
]

_MODES = ["explore", "exploit"]


def _all_template_texts() -> dict[str, str]:
    texts = {"PROPOSAL_COMMIT_PROMPT": PROPOSAL_COMMIT_PROMPT}
    for md in sorted(TEMPLATE_DIR.glob("*.md")):
        texts[md.name] = md.read_text()
    return texts


class TestNoMandatedParameterCeiling:
    def test_no_template_mandates_a_parameter_count_limit(self):
        for name, text in _all_template_texts().items():
            for pat in _MANDATE_PATTERNS:
                assert not re.search(pat, text, re.I), (
                    f"{name}: reintroduces the template-mandated "
                    f"parameter-count ceiling (pattern {pat!r}) — "
                    f"forbidden by C2 (design §23-C2 / F-2)."
                )

    def test_vram_limit_requirement_retained(self):
        """The VRAM half of the old bullet must survive: deterministic
        capacity guidance is legitimate."""
        assert "must include at least one VRAM limit" in PROPOSAL_COMMIT_PROMPT
        proposing = (TEMPLATE_DIR / "proposing_stage.md").read_text()
        assert "must include at least one VRAM limit" in proposing

    def test_capacity_constraints_require_justification_language(self):
        """Where capacity constraints are mentioned, they carry the
        measured-evidence-or-arithmetic qualifier (whitespace-normalized:
        the phrase wraps across lines in the templates)."""
        for text in (
            PROPOSAL_COMMIT_PROMPT,
            (TEMPLATE_DIR / "proposing_stage.md").read_text(),
        ):
            normalized = " ".join(text.split())
            assert "measured evidence or explicit capacity arithmetic" in normalized

    def test_loaded_stage_prompts_are_mandate_free(self):
        """Belt-and-braces: the RENDERED prompts (base + explore/exploit
        overlays through the real loader) are also mandate-free."""
        for mode in _MODES:
            rendered = load_stage_prompt("proposing_stage", exploration_mode=mode, template_vars={})
            for pat in _MANDATE_PATTERNS:
                assert not re.search(pat, rendered, re.I)


class TestGateExhaustionClosing:
    def test_single_entry_guidance_is_qualified(self):
        block = _format_recent_gate_exhaustions_block([gate_exhaustion()])
        assert "may be uncalibrated" in block
        assert "Do not derive a permanent" in block
        assert "parameter-count ceiling" in block
        # workload-first ordering: steps/batch/segment before capacity
        assert "optimizer steps, batch size, segment" in block
        # the old unqualified shrink order is gone
        assert "reduce parameter count and/or layer count" not in block

    def test_multi_entry_family_switch_signal_retained(self):
        block = _format_recent_gate_exhaustions_block([gate_exhaustion(), gate_exhaustion()])
        assert "propose a" in block and "different family" in block
        assert "not a smaller variant of the same family" in block

    def test_stale_hardcoded_vram_budget_removed(self):
        """The '<10 GB VRAM' literal contradicted the real 16 GB budget and
        added VRAM-side small-model pressure; templates now defer to the
        [HARDWARE CONTEXT] effective cap."""
        for name, text in _all_template_texts().items():
            assert "<10 GB VRAM" not in text, f"{name}: stale VRAM literal"
