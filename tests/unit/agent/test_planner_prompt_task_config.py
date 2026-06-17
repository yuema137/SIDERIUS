"""
Unit tests for the T4a placeholder-substitution path in ``PLANNER_PROMPT``
(``agent/prompts.py``) and ``LLMBridge.plan()`` (``agent/llm_bridge.py``).

Covers:

* The ``{TASK_DESCRIPTION}`` placeholder literal is present in the
  ``PLANNER_PROMPT`` template (regression guard against accidental removal).
* ``{TASK_DESCRIPTION}`` never survives into the rendered system prompt for
  any caller — non-empty input substitutes the value, empty input substitutes
  the empty string (test fixtures only).
* Custom ``task_description`` replaces the SQUID-specific framing.
* The Phase 8 ``{SCORE_COMPARISON_TABLE}`` placeholder is still wired
  (regression guard for the existing T4a-orthogonal substitution).
* ``HyperparamTuningInput.task_description`` defaults to ``""`` and round-trips
  through Pydantic.

See docs/design/enable_global_task_config.md § Commit T4a.
"""

from __future__ import annotations

import pytest

from agent.prompts import PLANNER_PROMPT
from agent.schemas.hyperparam_tuning import HyperparamTuningInput

_SQUID_TD = (
    "full-spectrum 1-D time-series denoising of SQUID dark-matter detector data: "
    "map a noisy [B, T] integer signal to a clean [B, 256, T] reconstruction"
)
_ALT_TD = "audio enhancement for speech synthesis: spectrogram → waveform"


# ---------------------------------------------------------------------------
# Template integrity
# ---------------------------------------------------------------------------


class TestPlannerPromptTemplate:
    def test_task_description_placeholder_present(self):
        """Regression guard: ``{TASK_DESCRIPTION}`` must be in the template
        before the substitution path can fire. If this fails, T4a was
        partially reverted."""
        assert "{TASK_DESCRIPTION}" in PLANNER_PROMPT

    def test_score_comparison_table_placeholder_still_present(self):
        """Regression guard for the existing Phase 8 ``{SCORE_COMPARISON_TABLE}``
        placeholder — orthogonal to T4a, must not have been touched."""
        assert "{SCORE_COMPARISON_TABLE}" in PLANNER_PROMPT

    def test_old_squid_hardcodes_are_gone(self):
        """The pre-T4a persona referenced SQUID-specific framing directly.
        After T4a, those phrases live only via the ``{TASK_DESCRIPTION}``
        substitution path."""
        assert "Senior Signal Processing Researcher" not in PLANNER_PROMPT
        assert "deep learning for signal denoising." not in PLANNER_PROMPT
        # "TIDMAD dataset" used to appear in the goal line.
        assert "TIDMAD dataset" not in PLANNER_PROMPT

    def test_persona_is_task_agnostic(self):
        """The new persona line frames the agent's job (hyperparameter
        optimization) without anchoring on the SQUID denoising task."""
        assert "Senior ML Research Analyst" in PLANNER_PROMPT
        assert "hyperparameter optimization" in PLANNER_PROMPT

    def test_denoising_score_field_name_preserved(self):
        """``denoising_score`` is the canonical metric field name across the
        codebase — preserving it as a Python identifier in the prompt is
        intentional (it's a field reference, not task framing). Phase 8
        regression guard."""
        # The new goal line includes the literal field name.
        assert "denoising_score" in PLANNER_PROMPT


# ---------------------------------------------------------------------------
# LLMBridge.plan() substitution — via direct .replace() simulation
# ---------------------------------------------------------------------------
#
# We test the substitution logic directly rather than calling
# ``LLMBridge.plan()`` end-to-end (which requires an API key and exercises
# 400+ lines of bridge plumbing irrelevant to T4a). The substitution chain
# at agent/llm_bridge.py:843-846 is the one-line behaviour T4a introduces;
# this test mirrors it exactly.


def _render_planner_system_prompt(
    score_table_md: str | None,
    task_description: str,
    score_table_fallback: str = "(no prior round yet)",
) -> str:
    """Mirror of agent/llm_bridge.py:843-846 substitution chain."""
    return PLANNER_PROMPT.replace(
        "{SCORE_COMPARISON_TABLE}",
        score_table_md or score_table_fallback,
    ).replace("{TASK_DESCRIPTION}", task_description)


class TestPlannerSubstitution:
    def test_placeholder_never_survives_with_non_empty_input(self):
        out = _render_planner_system_prompt(
            score_table_md="| f0 | 1.0 |", task_description=_SQUID_TD
        )
        assert "{TASK_DESCRIPTION}" not in out
        assert "{SCORE_COMPARISON_TABLE}" not in out

    def test_placeholder_collapses_to_empty_with_empty_input(self):
        """Test-fixture path: empty task_description substitutes to "".
        Production callers always pass non-empty values."""
        out = _render_planner_system_prompt(score_table_md=None, task_description="")
        # The placeholder literal must still be gone (replaced with "").
        assert "{TASK_DESCRIPTION}" not in out

    def test_custom_task_description_replaces_squid(self):
        out = _render_planner_system_prompt(score_table_md=None, task_description=_ALT_TD)
        # Custom task framing appears.
        assert _ALT_TD in out
        # The line right before the placeholder ("for the following task:")
        # is still template-resident and lives above the substituted value.
        assert "for the following task:" in out
        # SQUID hardcodes don't leak in from anywhere (template or fixture).
        assert "SQUID" not in out
        assert "TIDMAD" not in out

    def test_squid_input_reproduces_squid_anchors(self):
        """Byte-equivalent semantic content for production callers:
        when fed the SQUID task description, the rendered prompt carries
        the same task-anchoring strings the pre-T4a hardcode used to provide."""
        out = _render_planner_system_prompt(score_table_md=None, task_description=_SQUID_TD)
        assert "SQUID" in out
        assert "[B, T] integer signal" in out
        assert "[B, 256, T] reconstruction" in out

    def test_score_table_substitution_still_works(self):
        """T4a must not break the Phase 8 score-table substitution."""
        out = _render_planner_system_prompt(
            score_table_md="| filename | denoising_score |\n| f17 | 5.32 |",
            task_description=_SQUID_TD,
        )
        assert "f17" in out
        assert "5.32" in out


# ---------------------------------------------------------------------------
# HyperparamTuningInput.task_description — schema field
# ---------------------------------------------------------------------------


class TestHyperparamTuningInputTaskDescription:
    def test_default_is_empty(self):
        inp = HyperparamTuningInput(model_type="punet")
        assert inp.task_description == ""

    def test_round_trips_through_pydantic(self):
        inp = HyperparamTuningInput(
            model_type="punet",
            task_description="custom task here",
        )
        rehydrated = HyperparamTuningInput.model_validate(inp.model_dump())
        assert rehydrated.task_description == "custom task here"

    @pytest.mark.parametrize("td", ["", "trivial", _SQUID_TD, _ALT_TD])
    def test_accepts_arbitrary_strings(self, td):
        """No validation constraints on task_description in the schema —
        loader fail-fast already rejects empty + corrupted YAML upstream."""
        inp = HyperparamTuningInput(model_type="punet", task_description=td)
        assert inp.task_description == td
