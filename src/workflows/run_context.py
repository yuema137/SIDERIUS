"""Bind native agent accounting without constructing providers or running nodes."""

from pathlib import Path
from typing import Any


def bind_agent_run_context(
    agent: Any,
    *,
    workspace: str | Path,
    iteration: int,
    run_name: str | None,
    run_id: str | None,
) -> None:
    """Preserve native dispatch and the workflow's optional-context behavior.

    Agent-owned binding takes priority: the proposer binds eager/lazy stage
    bridges, while the tuner retains context until its brain exists. Other
    nodes expose an eager bridge. Missing run identity leaves either untouched;
    callers requiring accounting must establish that identity before invoking.
    """
    if run_name is None or run_id is None:
        return
    kwargs = dict(
        workspace=Path(workspace),
        iter=iteration,
        run_name=run_name,
        run_id=run_id,
    )
    if hasattr(agent, "set_run_context"):
        agent.set_run_context(**kwargs)
    elif hasattr(agent, "bridge") and agent.bridge is not None:
        agent.bridge.set_run_context(**kwargs)
