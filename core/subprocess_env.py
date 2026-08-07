"""The one environment a SIDERIUS subprocess needs to see generated plugins.

**Why this module exists** (V20 launch attempt 2, aborted 2026-08-07).

The training, inference and scoring subprocesses were handed an env
carrying `SIDERIUS_PLUGIN_DIRS`. The isolated pre-phase GPU measurement
worker was spawned with no `env=` at all, so it inherited the parent's
environment — which does *not* contain that variable, because it is
constructed per-sandbox and passed only to the sandbox's own children.

The worker therefore started with a clean registry, could not resolve the
config class of an agent-generated model, and returned:

    status : CONFIG_REJECTED
    detail : no config class registered for '<generated model>'

which the pre-phase gate correctly turned into
`STOP_INFRASTRUCTURE_FAILURE` and fail-closed. Every agent-generated
candidate passed its trial rounds and then died at the formal promotion
boundary — 15 consecutive attempts on one chain before the campaign was
stopped.

**The lesson this module encodes.** Parent reachability is not subprocess
reachability. A clean subprocess boundary turns plugin/config context
into an explicit runtime dependency that must be *transported*, and
tested across that boundary. The registry design was never wrong; one hop
of the transport was missing.

So the construction lives here, once, and every spawner calls it. Copying
three environment variables into a second spawn site is exactly how the
two drift apart again.
"""

from __future__ import annotations

import os

#: Run-scoped model-plugin directory. Read by `ml_models/plugin_loader.py`.
PLUGIN_DIRS_ENV_VAR = "SIDERIUS_PLUGIN_DIRS"
#: Run-scoped loss-plugin directory. Deliberately distinct from the model
#: one — sharing would mask globally-registered losses whenever only a
#: model dir is set. See `docs/design/enable_loss_inventory.md` § Commit L1.
LOSS_DIRS_ENV_VAR = "SIDERIUS_LOSS_DIRS"


def subprocess_env(
    plugin_dir: str | None = None,
    loss_dir: str | None = None,
) -> dict[str, str]:
    """Env for any subprocess that must resolve SIDERIUS models or losses.

    Adds `ml_models` and `execute_tools` to `PYTHONPATH` so the flat
    imports in those scripts resolve regardless of working directory, and
    forwards the run-scoped plugin directories when supplied.

    Args:
        plugin_dir: run-scoped model-plugin directory. When provided, the
            subprocess scans only this directory instead of the legacy
            global `agent_generated/models/`. `None` leaves the variable
            unset and the subprocess falls back to the legacy global dir —
            preserving back-compat for callers outside the sandbox flow.
        loss_dir: run-scoped loss-plugin directory, same semantics.

    Returns:
        A copy of the current environment with the above applied. Never
        mutates `os.environ`.
    """
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    extra_paths = [
        project_root,
        os.path.join(project_root, "ml_models"),
        os.path.join(project_root, "execute_tools"),
    ]
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(extra_paths + ([existing] if existing else []))
    if plugin_dir:
        env[PLUGIN_DIRS_ENV_VAR] = plugin_dir
    if loss_dir:
        env[LOSS_DIRS_ENV_VAR] = loss_dir
    return env
