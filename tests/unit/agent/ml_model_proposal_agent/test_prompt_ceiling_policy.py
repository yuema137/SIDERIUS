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
    PROPOSAL_REASONING_PROMPT,
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
    """Every proposer prompt SURFACE this guard governs.

    PR 01b / S1-E widened the scan set to include
    ``PROPOSAL_REASONING_PROMPT``. Its absence is the ONLY reason that
    constant's stale ``~100M`` parameter-count literal survived the
    original C2 sweep: a guard that cannot see a surface does not guard
    it, and deleting a literal without closing the blind spot leaves the
    deletion with no test that fails if it comes back.
    """
    texts = {
        "PROPOSAL_COMMIT_PROMPT": PROPOSAL_COMMIT_PROMPT,
        "PROPOSAL_REASONING_PROMPT": PROPOSAL_REASONING_PROMPT,
    }
    for md in sorted(TEMPLATE_DIR.glob("*.md")):
        texts[md.name] = md.read_text()
    return texts


# --- S1-E: numeric capacity literals, generalised beyond one exact string ---
#
# A magnitude with a size/count unit...
_MAGNITUDE = re.compile(r"\d[\d.,]*\s*(?:GiB|GB|MB|M|B)\b")
# ...appearing near capacity language. Both halves are required: the
# templates legitimately contain bare numerals (`segmentation_size >
# 20000`, `[B, 256, T]`, boldness ratios) and legitimately contain
# capacity PROSE with no numeral ("must include at least one VRAM
# limit", "the effective cap in [HARDWARE CONTEXT]"). Only the
# CONJUNCTION is the defect — a hardcoded budget that contradicts the
# live [HARDWARE CONTEXT] cap.
_CAPACITY_CONTEXT = re.compile(r"vram|memory|budget|parameter|param\b|ceiling|cap\b", re.I)
_CONTEXT_WINDOW = 90


def _numeric_capacity_literals(text: str) -> list[str]:
    """Return one context snippet per numeric capacity literal found.

    Whitespace-normalised first, because these sentences wrap across
    lines in the templates — the exact-string pin this generalises
    (``"<10 GB VRAM"``) missed the surviving ``"the 10 GB VRAM budget"``
    for want of a single ``<``.
    """
    flat = " ".join(text.split())
    snippets: list[str] = []
    for match in _MAGNITUDE.finditer(flat):
        window = flat[max(0, match.start() - _CONTEXT_WINDOW) : match.end() + _CONTEXT_WINDOW]
        if _CAPACITY_CONTEXT.search(window):
            snippets.append(window)
    return snippets


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
        [HARDWARE CONTEXT] effective cap.

        Kept as the dated exact-string regression pin. The generalised
        form below is what actually guards the surface now."""
        for name, text in _all_template_texts().items():
            assert "<10 GB VRAM" not in text, f"{name}: stale VRAM literal"

    def test_no_numeric_capacity_literal_on_any_proposer_surface(self):
        """S1-E: no hardcoded VRAM or parameter-count budget survives on
        ANY proposer prompt surface.

        This is the generalisation that the two blind spots demanded. The
        exact-string pin above could not see ``"the 10 GB VRAM budget"``
        (no ``<``), and the old scan set could not see
        ``PROPOSAL_REASONING_PROMPT`` at all (``~100M``). A numeric budget
        baked into a prompt contradicts the live ``[HARDWARE CONTEXT]``
        effective cap the proposer is told to treat as the hard limit.
        """
        offenders = {
            name: found
            for name, text in _all_template_texts().items()
            if (found := _numeric_capacity_literals(text))
        }
        assert offenders == {}, (
            "hardcoded numeric capacity budget(s) on a proposer prompt surface — "
            "defer to the [HARDWARE CONTEXT] effective cap instead of a literal: "
            f"{offenders}"
        )

    def test_generalised_pattern_does_not_fire_on_legitimate_text(self):
        """The negative control (design §4.3, adversarial finding A9).

        Over-broad patterns get 'fixed' by weakening the guard or by
        editing the innocent text. Pin the three things that must NOT
        trip it:

        1. the VRAM-limit REQUIREMENT prose — deterministic capacity
           guidance is legitimate and stays;
        2. bare numerals with no capacity meaning;
        3. the task-background block S1-C injects, which carries the
           shipped description's ``256`` and ``[B, 256, T]``.
        """
        from nodes.ml_model_proposal_agent.ml_model_proposal_agent import (
            _render_pipeline_task_background,
        )
        from workflows.task_config import get_task_description, load_task_config

        assert (
            _numeric_capacity_literals(
                "expert_advice.constraints must include at least one VRAM limit "
                "(relative to the effective cap in [HARDWARE CONTEXT])"
            )
            == []
        )
        assert (
            _numeric_capacity_literals(
                "'FNO layer may exceed VRAM budget at segmentation_size > 20000'"
            )
            == []
        )
        joined = _render_pipeline_task_background(get_task_description(load_task_config()))
        assert _numeric_capacity_literals(joined) == [], (
            "the widened pattern fires on the shipped task description injected by S1-C"
        )
        # ...and it DOES fire on the thing it exists to catch.
        assert _numeric_capacity_literals("keep parameter_count_estimate under ~100M")
        assert _numeric_capacity_literals("may exceed the 10 GB VRAM budget")

    def test_vram_requirement_prose_survives_the_cleanup(self):
        """S1-E deletes numeric budgets, NOT the VRAM mandate. The
        proposer must still be told to declare a VRAM limit, and the
        reasoning constant must still point at the effective cap."""
        assert "must include at least one VRAM limit" in PROPOSAL_COMMIT_PROMPT
        assert "VRAM ceiling" in PROPOSAL_REASONING_PROMPT
        assert "HARDWARE CONTEXT" in PROPOSAL_REASONING_PROMPT
