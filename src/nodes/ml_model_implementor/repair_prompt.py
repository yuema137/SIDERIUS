"""System prompt of the implementor's stateless repair calls (#1574).

A repair call is a separate LLM request. Before #1574 its system prompt was a
short constant saying the hard constraints "from the previous prompt still
apply", but the repair request never received that prompt, so a repair could
fix the reported error while breaking a constraint it had never seen (the
import allow-list, the helper-class ban, the output shape ...).

The repair system prompt is now the repair instructions followed by the SAME
output contract and hard constraints the code call receives. The caller passes
that contract in (``ml_model_implementor._code_contract`` /
``IMPLEMENTOR_LOSS_CODE_CONTRACT``), so the constraint text has one owner and is
never duplicated here.

``implementor.repair_system`` is a published prompt boundary, entered on every
repair call. An experiment-owned profile restores the pre-#1574 system prompts
by returning the historical constant for each ``kind``; a profile that does
not declare the boundary raises when a repair is requested.
"""

from __future__ import annotations

from typing import Literal

from agent.prompt_rendering import prompt_boundary

RepairKind = Literal["model", "loss"]

_INSTRUCTIONS: dict[str, str] = {
    "model": (
        "You are a senior PyTorch engineer. Your previous code attempt failed validation.\n"
        "Fix the error described in the user message and return the corrected JSON object.\n"
        "Focus specifically on that error — do not rewrite unrelated code. The output\n"
        "contract and hard constraints below apply to the corrected code.\n\n"
    ),
    "loss": (
        "You are a senior PyTorch engineer. Your previous loss-plugin code failed validation.\n"
        "Fix the error described in the user message and return the corrected JSON object.\n"
        "Focus specifically on that error — do not rewrite unrelated code. The output\n"
        "contract and hard constraints below apply to the corrected code.\n\n"
    ),
}


@prompt_boundary("implementor.repair_system")
def render_repair_system_prompt(kind: RepairKind, code_contract: str) -> str:
    """Repair instructions for ``kind`` followed by the code call's ``code_contract``.

    ``code_contract`` is the exact contract text of the sibling code call
    (output fields, hard constraints and, for models, the native-training
    appendix), so a repair is held to the same rules as the code it repairs.
    """
    return _INSTRUCTIONS[kind] + code_contract
