# agent/prompt_templates/proposal/task_blocks.py
"""The bounded Regime-A adapter for task-owned PROPOSER guidance.

Step 12 / PR-12a C7 (D-12a-6). Deliberately the same module as 09b's
``agent/prompt_templates/interpretation/task_blocks.py``, one node over: it
owns exactly ONE job — parse a task-owned declaration file into the typed
``ProposalTaskBlocks`` VALUE the caller then places on
``ProposalInput.proposal_blocks``. It is compatibility PACKAGING, not an
extension mechanism: an external task supplies the same typed value directly
(or its own file anywhere on disk) with zero SIDERIUS edits, and the
composition root replaces the CALL SITE, never this contract.

It must never become a registry, a task catalog, a config manager or a plugin
system. The one task-identity occurrence below is a self-labelled default-path
CONSTANT, not a branch: it feeds no ``if``/``match``, no dispatch, no task-id
inference. The PR-12a census turns RED on a second task constant, a task
table, or any conditional that reads it.
"""

import os

from agent.prompt_templates._task_blocks_loader import load_task_blocks_declaration
from agent.schemas.proposal import ProposalTaskBlocks

#: The bounded legacy compatibility path (the 08b
#: ``LEGACY_DEFAULT_TASK_HEALTH_CONFIG`` / 09b
#: ``LEGACY_DEFAULT_TASK_INTERPRETATION_CONFIG`` idiom — a CONSTANT, not a
#: branch). There is no ``if task == …`` anywhere: one unconditional default,
#: quarantined here so the Regime-A workflow resolves TIDMAD's proposer
#: guidance without naming the task itself. An external task passes its own
#: path — or constructs the typed value directly — and never touches this.
LEGACY_DEFAULT_TASK_PROPOSAL_CONFIG: str = os.path.join("configs", "task_proposal", "tidmad.yaml")


def load_proposal_task_blocks(path: str | None = None) -> ProposalTaskBlocks:
    """Parse a task-owned declaration file into ``ProposalTaskBlocks``.

    ``path=None`` resolves the ONE unconditional default above. FAIL-CLOSED on
    a missing, unreadable or malformed file, an unknown key or a non-string
    section — the Regime-A workflow must never silently propose for TIDMAD
    without its science, and a typo'd section name must never silently render
    nothing.

    Step 12 / PR-12a C7-4 shares the deterministic mechanics with the
    implementor adapter; the SCHEMAS stay separate, because the two families
    render in different places for different reasons.
    """
    return load_task_blocks_declaration(
        ProposalTaskBlocks,
        path=path,
        default_path=LEGACY_DEFAULT_TASK_PROPOSAL_CONFIG,
        kind="proposal",
    )
