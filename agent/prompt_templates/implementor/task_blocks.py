# agent/prompt_templates/implementor/task_blocks.py
"""The bounded Regime-A adapter for task-owned IMPLEMENTOR science.

Step 12 / PR-12a C7-4. The third instance of the 09b pattern, and the same
job every time: parse a task-owned declaration file into the typed
``ImplementorTaskBlocks`` VALUE the caller places on
``ImplementorInput.implementor_blocks``. Compatibility PACKAGING, not an
extension mechanism — an external task supplies the typed value directly (or
its own file anywhere on disk) with zero SIDERIUS edits.

It must never become a registry, a task catalog, a config manager or a plugin
system. The one task-identity occurrence below is a self-labelled default-path
CONSTANT, not a branch: it feeds no ``if``/``match``, no dispatch, no task-id
inference.
"""

import os

from agent.prompt_templates._task_blocks_loader import (
    SIDERIUS_ROOT,
    load_task_blocks_declaration,
)
from agent.schemas.implementor import ImplementorTaskBlocks

#: The bounded legacy compatibility path — a CONSTANT, not a branch, matching
#: the 08b / 09b / C7-3 idiom. One unconditional default, quarantined here so
#: the Regime-A workflow resolves TIDMAD's implementor science without naming
#: the task itself.
#:
#: Anchored to THIS checkout, not to the caller's working directory (F-7,
#: second occurrence — see ``_task_blocks_loader.SIDERIUS_ROOT``). The
#: workflow calls the loader zero-arg on the un-composed branch, so a
#: relative default made the implementor die in any launch that did not
#: happen to start at the repo root.
LEGACY_DEFAULT_TASK_IMPLEMENTOR_CONFIG: str = os.path.join(
    SIDERIUS_ROOT, "configs", "task_implementor", "tidmad.yaml"
)


def load_implementor_task_blocks(path: str | None = None) -> ImplementorTaskBlocks:
    """Parse a task-owned declaration file into ``ImplementorTaskBlocks``.

    ``path=None`` resolves the ONE unconditional default above. FAIL-CLOSED on
    a missing, unreadable or malformed file, an unknown key or a non-string
    section — a typo'd section name must never silently render nothing.
    """
    return load_task_blocks_declaration(
        ImplementorTaskBlocks,
        path=path,
        default_path=LEGACY_DEFAULT_TASK_IMPLEMENTOR_CONFIG,
        kind="implementor",
    )
