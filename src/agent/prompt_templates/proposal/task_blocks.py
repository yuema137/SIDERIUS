# agent/prompt_templates/proposal/task_blocks.py
"""Loader for task-owned PROPOSER guidance.

Step 12 / PR-12a C7 (D-12a-6). Deliberately the same module as 09b's
``agent/prompt_templates/interpretation/task_blocks.py``, one node over: it
owns exactly ONE job — parse a task-owned declaration file into the typed
``ProposalTaskBlocks`` VALUE the caller then places on
``ProposalInput.proposal_blocks``. It is compatibility PACKAGING, not an
extension mechanism: an external task supplies the same typed value directly
(or its own file anywhere on disk) with zero SIDERIUS edits, and the
composition root replaces the CALL SITE, never this contract.

It must never become a registry, task catalog, config manager, or plugin
system. An omitted path means no guidance; an explicit path is validated.
"""

from agent.prompt_templates._task_blocks_loader import load_task_blocks_declaration
from agent.schemas.proposal import ProposalTaskBlocks


def load_proposal_task_blocks(path: str | None = None) -> ProposalTaskBlocks:
    """Parse a task-owned declaration file into ``ProposalTaskBlocks``.

    ``path=None`` returns an empty typed declaration. An explicit path remains
    fail-closed on missing, unreadable, or malformed content.

    Step 12 / PR-12a C7-4 shares the deterministic mechanics with the
    implementor adapter; the SCHEMAS stay separate, because the two families
    render in different places for different reasons.
    """
    return load_task_blocks_declaration(
        ProposalTaskBlocks,
        path=path,
        kind="proposal",
    )
