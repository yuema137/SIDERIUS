# agent/prompt_templates/interpretation/task_blocks.py
"""The bounded Regime-A adapter for task-owned interpretation guidance.

Step 09b C2 (parent §13 ¶3, Q-09-1 = B refined). This module owns exactly ONE
job: parse a task-owned declaration file into the typed
``InterpretationTaskBlocks`` VALUE the caller then places on
``InterpretationInput.task_blocks``. It is compatibility PACKAGING, not an
extension mechanism: an external task supplies the same typed value directly
(or its own file anywhere on disk) with zero SIDERIUS edits, and Step 12's
composition root replaces the CALL SITE, never this contract.

It must never become a registry, a task catalog, a config manager or a
plugin system. The one task-identity occurrence below is a self-labelled
default-path CONSTANT, not a branch: it feeds no ``if``/``match``, no
dispatch, no task-id inference — the Step-09b census (design §16 items
3/3b) turns RED on a second task constant, a task table, or any conditional
that reads it.
"""

import os
from typing import Any

import yaml

from agent.prompt_templates._task_blocks_loader import SIDERIUS_ROOT
from agent.schemas.interpretation import InterpretationTaskBlocks

#: The bounded legacy compatibility path (the 08b
#: ``LEGACY_DEFAULT_TASK_HEALTH_CONFIG`` idiom — a CONSTANT, not a branch).
#: There is no ``if task == …`` anywhere: one unconditional default,
#: quarantined here so the Regime-A workflow and the node CLI resolve
#: TIDMAD's guidance without naming the task themselves. An external task
#: passes its own path — or constructs the typed value directly — and never
#: touches this.
#:
#: Anchored to THIS checkout, not to the caller's working directory (F-7,
#: second occurrence — see ``_task_blocks_loader.SIDERIUS_ROOT``). The
#: workflow and the node CLI call the loader zero-arg on the un-composed
#: branch, so a relative default made the interpreter die in any launch that
#: did not happen to start at the repo root. Only the anchor is imported:
#: this module keeps its own loader, which is 09b's frozen evidence.
LEGACY_DEFAULT_TASK_INTERPRETATION_CONFIG: str = os.path.join(
    SIDERIUS_ROOT, "configs", "task_interpretation", "tidmad.yaml"
)


def load_interpretation_task_blocks(path: str | None = None) -> InterpretationTaskBlocks:
    """Parse a task-owned declaration file into ``InterpretationTaskBlocks``.

    ``path=None`` resolves the ONE unconditional default above. The load is
    FAIL-CLOSED: a missing, unreadable or malformed file, an unknown key, a
    non-string section or an empty present section all raise — the Regime-A
    workflow must never silently interpret TIDMAD without its science, and a
    typo'd section name must never silently render nothing.

    Args:
        path: filesystem path to a YAML mapping whose keys are a subset of
            the four framework section names. ``None`` ⇒ the default
            declaration.

    Returns:
        the validated, frozen ``InterpretationTaskBlocks`` value.

    Raises:
        FileNotFoundError: the declaration file does not exist.
        ValueError: the file is not a YAML mapping, or the mapping fails the
            ``InterpretationTaskBlocks`` contract (unknown key, empty
            present section, non-string value).
    """
    resolved = path if path is not None else LEGACY_DEFAULT_TASK_INTERPRETATION_CONFIG
    if not os.path.exists(resolved):
        raise FileNotFoundError(
            f"interpretation task-blocks declaration not found: {resolved!r} — "
            "the caller must supply an existing declaration file or construct "
            "the InterpretationTaskBlocks value directly"
        )
    with open(resolved, encoding="utf-8") as f:
        raw: Any = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError(
            f"interpretation task-blocks declaration {resolved!r} must be a "
            f"YAML mapping of section name -> prose, got {type(raw).__name__}"
        )
    try:
        return InterpretationTaskBlocks.model_validate(raw)
    except Exception as exc:
        raise ValueError(
            f"interpretation task-blocks declaration {resolved!r} failed the "
            f"InterpretationTaskBlocks contract: {exc}"
        ) from exc
