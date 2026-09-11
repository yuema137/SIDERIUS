# agent/prompt_templates/implementor/task_blocks.py
"""Loader for task-owned IMPLEMENTOR guidance.

Step 12 / PR-12a C7-4. The third instance of the 09b pattern, and the same
job every time: parse a task-owned declaration file into the typed
``ImplementorTaskBlocks`` VALUE the caller places on
``ImplementorInput.implementor_blocks``. Compatibility PACKAGING, not an
extension mechanism — an external task supplies the typed value directly (or
its own file anywhere on disk) with zero SIDERIUS edits.

It must never become a registry, task catalog, config manager, or plugin
system. An omitted path means no guidance; an explicit path is validated.
"""

from agent.prompt_templates._task_blocks_loader import load_task_blocks_declaration
from agent.schemas.implementor import ImplementorTaskBlocks


def load_implementor_task_blocks(path: str | None = None) -> ImplementorTaskBlocks:
    """Parse a task-owned declaration file into ``ImplementorTaskBlocks``.

    ``path=None`` returns an empty typed declaration. An explicit path remains
    fail-closed on missing, unreadable, or malformed content.
    """
    return load_task_blocks_declaration(
        ImplementorTaskBlocks,
        path=path,
        kind="implementor",
    )
