"""
Regression guard for the V9 Cognitive Alignment surgery (2-zh).

Asserts that a fixed set of denoise-bias / hardcoded-threshold tokens never
appear in the LLM-facing production prompt strings. Prevents the codebase
from drifting back to the pre-V9 framing — fixed file-index labels,
frequency-band partitions, hard threshold constants, IGNORE-style verbiage.

Scope: production prompt constants only (the strings that get sent to
the LLM). Test fixtures and free-form code comments are out of scope.

The runtime field name `denoising_score` and the literal word "denoising"
(which is the task name in this project) are intentionally NOT banned.
"""
import pytest

from agent.prompts import PLANNER_PROMPT, REFLECTOR_PROMPT
from nodes.result_interpretation_agent import (
    PER_MODEL_SYSTEM_PROMPT,
    SYNTHESIS_SYSTEM_PROMPT,
)
from nodes.ml_model_proposal_agent import PROPOSAL_REASONING_PROMPT


PRODUCTION_PROMPTS = {
    "PLANNER_PROMPT": PLANNER_PROMPT,
    "REFLECTOR_PROMPT": REFLECTOR_PROMPT,
    "PER_MODEL_SYSTEM_PROMPT": PER_MODEL_SYSTEM_PROMPT,
    "SYNTHESIS_SYSTEM_PROMPT": SYNTHESIS_SYSTEM_PROMPT,
    "PROPOSAL_REASONING_PROMPT": PROPOSAL_REASONING_PROMPT,
}


BANNED_VOCABULARY = [
    "frequency_band",
    "frequency band",
    "low-frequency",
    "mid-frequency",
    "high-frequency",
    "frequency_analysis",
    "frequency_comparison",
    "weak_frequency_files",
    "Weak Frequency",
    "Inconsequential",
    "HEADROOM_EPSILON",
]


@pytest.mark.parametrize("prompt_name,prompt_text", PRODUCTION_PROMPTS.items())
@pytest.mark.parametrize("token", BANNED_VOCABULARY)
def test_banned_vocabulary_absent(prompt_name, prompt_text, token):
    assert token not in prompt_text, (
        f"Banned vocabulary {token!r} found in {prompt_name}. "
        f"V9 cognitive alignment requires task-agnostic, Impact_Score-driven "
        f"framing — re-read the 'Log-of-Mean trap' section before reintroducing "
        f"this token."
    )


@pytest.mark.parametrize("prompt_name,prompt_text", {
    "PER_MODEL_SYSTEM_PROMPT": PER_MODEL_SYSTEM_PROMPT,
    "SYNTHESIS_SYSTEM_PROMPT": SYNTHESIS_SYSTEM_PROMPT,
}.items())
def test_impact_aware_framing_present(prompt_name, prompt_text):
    """The two interpretation prompts must carry the Impact_Score / Linear_Weight
    framing — guards against accidental deletion of the Log-of-Mean trap section."""
    assert "Impact_Score" in prompt_text, f"{prompt_name} missing Impact_Score framing"
    assert "Linear_Weight" in prompt_text, f"{prompt_name} missing Linear_Weight framing"
    assert "Log-of-Mean" in prompt_text, f"{prompt_name} missing Log-of-Mean trap section"


def test_planner_prompt_per_file_table_uses_impact_columns():
    assert "Impact_Score" in PLANNER_PROMPT
    assert "Linear_Weight" in PLANNER_PROMPT


def test_proposer_reasoning_uses_impact_score():
    assert "Impact_Score" in PROPOSAL_REASONING_PROMPT
