# agent/prompt_templates/interpretation/task_blocks.py
"""Loader for task-owned interpretation guidance.

Step 09b C2 (parent §13 ¶3, Q-09-1 = B refined). This module owns exactly ONE
job: parse a task-owned declaration file into the typed
``InterpretationTaskBlocks`` VALUE the caller then places on
``InterpretationInput.task_blocks``. It is compatibility PACKAGING, not an
extension mechanism: an external task supplies the same typed value directly
(or its own file anywhere on disk) with zero SIDERIUS edits, and Step 12's
composition root replaces the CALL SITE, never this contract.

It must never become a registry, task catalog, config manager, or plugin
system. An omitted path means no guidance; an explicit path is validated.
"""

from agent.prompt_templates._task_blocks_loader import load_task_blocks_declaration
from agent.schemas.interpretation import InterpretationTaskBlocks


def load_interpretation_task_blocks(path: str | None = None) -> InterpretationTaskBlocks:
    """Parse a task-owned declaration file into ``InterpretationTaskBlocks``.

    ``path=None`` returns an empty typed declaration. An explicit path is
    fail-closed on missing, unreadable, or malformed content.

    Args:
        path: filesystem path to a YAML mapping whose keys are a subset of
            the four framework section names. ``None`` means no guidance.

    Returns:
        the validated, frozen ``InterpretationTaskBlocks`` value.

    Raises:
        FileNotFoundError: the declaration file does not exist.
        ValueError: the file is not a YAML mapping, or the mapping fails the
            ``InterpretationTaskBlocks`` contract (unknown key, empty
            present section, non-string value).
    """
    return load_task_blocks_declaration(
        InterpretationTaskBlocks,
        path=path,
        kind="interpretation",
    )
