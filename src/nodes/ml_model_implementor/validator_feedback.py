"""Validator rejection feedback shared by every model implementation call (#1572).

``ImplementorInput.previous_validation_failure`` carries the validator's
rejection of an earlier implementation of the same proposal (with every
earlier rejection since #1553). The implementor's reasoning, code and repair
calls are separate, stateless requests. Only the reasoning prompt rendered the
rejection, so the code call depended on the reasoning text restating it and a
repair could reintroduce the rejected mismatch. This module renders the
feedback for each call.

Rendering per stage:

* ``"reasoning"``: the established reasoning block, rendered natively and
  NOT through a prompt boundary. Its bytes are unchanged since before #1572,
  so historical prompt profiles keep working without declaring anything new.
* ``"code"`` and ``"repair"``: a section rendered through the published prompt
  boundary ``implementor.validator_feedback``. An experiment-owned profile
  restores the pre-#1572 prompts by returning ``""``.

Absent feedback (``None`` or empty) renders nothing and never enters the
boundary, so first-attempt prompts are byte-identical. The feedback string is
embedded whole; its size is bounded by its producer
(``workflows.proposal_failure_feedback``: one line per distinct rejection).
"""

from __future__ import annotations

from typing import Literal

from agent.prompt_rendering import prompt_boundary

LaterStage = Literal["code", "repair"]
FeedbackStage = Literal["reasoning", "code", "repair"]


def validator_feedback_section(feedback: str | None, stage: FeedbackStage) -> str:
    """The rejection section for one implementation call, or ``""`` without one.

    The result carries no leading or trailing blank line; each prompt builder
    owns its own separators.
    """
    if not feedback:
        return ""
    if stage == "reasoning":
        return _reasoning_block(feedback)
    return render_validator_feedback_section(feedback, stage)


def _reasoning_block(feedback: str) -> str:
    """The pre-#1572 reasoning block, byte for byte."""
    return "\n".join(
        [
            "## ⚠ Previous Implementation Failed Validation — Fix This",
            "",
            "Your previous implementation of this same proposal was rejected by the",
            "validator with the following error. Address it explicitly in your reasoning",
            "before committing to code:",
            "",
            feedback,
            "",
            "Do NOT reproduce the same mistake. Your reasoning must explain how you will",
            "fix each issue raised above.",
        ]
    )


@prompt_boundary("implementor.validator_feedback")
def render_validator_feedback_section(feedback: str, stage: LaterStage) -> str:
    """Render the rejection for the code or a repair call; identical for both stages.

    ``stage`` names the calling request so that a profile may render each one
    differently.
    """
    del stage  # The native rendering is stage-independent by design (#1572).
    return "\n".join(
        [
            "## ⚠ Previous Implementation Failed Validation — Do Not Reproduce",
            "",
            "The validator rejected an earlier implementation of this same proposal",
            "with the following feedback. The code you output must not reproduce it:",
            "",
            feedback,
        ]
    )
