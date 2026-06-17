"""
Unit tests for the T4b placeholder-substitution path in the interpreter's
two system prompts (``PER_MODEL_SYSTEM_PROMPT`` and
``SYNTHESIS_SYSTEM_PROMPT``) and the ``InterpretationInput.task_description``
field.

Covers:

* The ``{TASK_DESCRIPTION}`` placeholder literal is present in both
  templates (regression guard against accidental removal).
* ``_build_per_model_system_prompt`` and ``_build_synthesis_system_prompt``
  substitute the placeholder at call time.
* Custom ``task_description`` replaces the SQUID-specific framing.
* Old persona hardcode "deep learning for signal denoising" is gone.
* Phase 8 content (Impact_Score, Linear_Weight, Log-of-Mean trap) is
  preserved in both prompts.
* ``InterpretationInput.task_description`` defaults to ``""`` and
  round-trips through Pydantic.

See docs/design/enable_global_task_config.md § Commit T4.
"""

from __future__ import annotations

import pytest

from agent.schemas.interpretation import InterpretationInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.result_interpretation_agent.result_interpretation_agent import (
    PER_MODEL_SYSTEM_PROMPT,
    SYNTHESIS_SYSTEM_PROMPT,
    _build_per_model_system_prompt,
    _build_synthesis_system_prompt,
)

_SQUID_TD = (
    "full-spectrum 1-D time-series denoising of SQUID dark-matter detector data: "
    "map a noisy [B, T] integer signal to a clean [B, 256, T] reconstruction"
)
_ALT_TD = "audio enhancement for speech synthesis: spectrogram → waveform"


def _make_input(task_description: str = "") -> InterpretationInput:
    return InterpretationInput(
        summaries=[],
        model_knowledge_cache={},
        model_types=["punet"],
        task_description=task_description,
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace="/tmp/test", run_name="r1"),
        ),
    )


# ---------------------------------------------------------------------------
# Template integrity
# ---------------------------------------------------------------------------


class TestTemplatePlaceholders:
    def test_per_model_placeholder_present(self):
        assert "{TASK_DESCRIPTION}" in PER_MODEL_SYSTEM_PROMPT

    def test_synthesis_placeholder_present(self):
        assert "{TASK_DESCRIPTION}" in SYNTHESIS_SYSTEM_PROMPT

    def test_old_persona_hardcode_gone_in_both_templates(self):
        # The pre-T4b persona was identical in both prompts.
        assert "specialising in deep learning for signal denoising" not in PER_MODEL_SYSTEM_PROMPT
        assert "specialising in deep learning for signal denoising" not in SYNTHESIS_SYSTEM_PROMPT

    def test_new_persona_is_task_agnostic_in_both_templates(self):
        # The new persona is the task-agnostic prefix.
        assert "You are a senior ML research analyst." in PER_MODEL_SYSTEM_PROMPT
        assert "You are a senior ML research analyst." in SYNTHESIS_SYSTEM_PROMPT

    def test_phase8_log_of_mean_section_preserved_in_per_model(self):
        # Phase 8 — Log-of-Mean trap section must survive T4b.
        assert "Log-of-Mean trap" in PER_MODEL_SYSTEM_PROMPT
        assert "Linear_Weight" in PER_MODEL_SYSTEM_PROMPT
        assert "Impact_Score" in PER_MODEL_SYSTEM_PROMPT

    def test_phase8_log_of_mean_section_preserved_in_synthesis(self):
        assert "Log-of-Mean trap" in SYNTHESIS_SYSTEM_PROMPT
        assert "Linear_Weight" in SYNTHESIS_SYSTEM_PROMPT
        assert "Impact_Score" in SYNTHESIS_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Helper substitution
# ---------------------------------------------------------------------------


class TestPerModelSystemPromptHelper:
    def test_placeholder_never_survives(self):
        out = _build_per_model_system_prompt(_make_input(task_description=_SQUID_TD))
        assert "{TASK_DESCRIPTION}" not in out

    def test_placeholder_collapses_to_empty_with_default(self):
        out = _build_per_model_system_prompt(_make_input())
        assert "{TASK_DESCRIPTION}" not in out

    def test_custom_task_description_appears(self):
        out = _build_per_model_system_prompt(_make_input(task_description=_ALT_TD))
        assert _ALT_TD in out
        # Old SQUID framing is gone — both from template removal and
        # because the substituted value is the alt task.
        assert "SQUID" not in out
        assert "TIDMAD" not in out

    def test_squid_input_carries_squid_anchors(self):
        out = _build_per_model_system_prompt(_make_input(task_description=_SQUID_TD))
        assert "SQUID" in out
        assert "[B, T] integer signal" in out

    def test_phase8_content_present_after_substitution(self):
        """Even after substitution, Phase 8 Log-of-Mean trap section is
        unchanged."""
        out = _build_per_model_system_prompt(_make_input(task_description=_SQUID_TD))
        assert "Log-of-Mean trap" in out
        assert "Linear_Weight" in out
        assert "Impact_Score" in out


class TestSynthesisSystemPromptHelper:
    def test_placeholder_never_survives(self):
        out = _build_synthesis_system_prompt(_make_input(task_description=_SQUID_TD))
        assert "{TASK_DESCRIPTION}" not in out

    def test_placeholder_collapses_to_empty_with_default(self):
        out = _build_synthesis_system_prompt(_make_input())
        assert "{TASK_DESCRIPTION}" not in out

    def test_custom_task_description_appears(self):
        out = _build_synthesis_system_prompt(_make_input(task_description=_ALT_TD))
        assert _ALT_TD in out
        assert "SQUID" not in out
        assert "TIDMAD" not in out

    def test_phase8_content_present_after_substitution(self):
        out = _build_synthesis_system_prompt(_make_input(task_description=_SQUID_TD))
        assert "Log-of-Mean trap" in out
        assert "Linear_Weight" in out
        assert "Impact_Score" in out


# ---------------------------------------------------------------------------
# InterpretationInput.task_description — schema field
# ---------------------------------------------------------------------------


class TestInterpretationInputTaskDescription:
    def test_default_is_empty(self):
        inp = _make_input()
        assert inp.task_description == ""

    def test_round_trips_through_pydantic(self):
        inp = _make_input(task_description="custom task")
        rehydrated = InterpretationInput.model_validate(inp.model_dump())
        assert rehydrated.task_description == "custom task"

    @pytest.mark.parametrize("td", ["", "trivial", _SQUID_TD, _ALT_TD])
    def test_accepts_arbitrary_strings(self, td):
        inp = _make_input(task_description=td)
        assert inp.task_description == td
