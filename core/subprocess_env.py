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

    Preserves the exact-checkout virtualenv selected by the launcher and
    forwards the run-scoped plugin directories when supplied. Framework
    source is never injected through ``PYTHONPATH``; installed package imports
    must resolve through that virtualenv, while generated model and loss roots
    travel through their dedicated environment variables.

    **The model-plugin variable is UNIONED, not assigned** (Step 12 /
    PR-12d, seam P). It used to be assigned while `PYTHONPATH` two lines
    above was joined, and that asymmetry was the defect: the one variable
    whose entire purpose is to say *which implementation runs* was the one
    a child spawn destroyed. A child or runtime default may now ADD to the
    set the run declared; it can never overwrite or drop it.

    TWO sources merge, in precedence order: the caller's `plugin_dir` (most
    run-specific — the workspace where implementor output lands) and the
    RUN-SCOPED BINDING's declared roots. Nothing else.

    **The ambient environment is deliberately NOT a third source**, and that
    is a correction rather than an omission. An earlier draft unioned it too,
    reasoning that a process which received roots from ITS parent carries no
    binding object. But that case is already covered: with no `plugin_dir`
    supplied the `os.environ.copy()` below carries the inherited value
    unchanged, so the transitive hop works without any union at all. What the
    third source DID do was change legacy behaviour — an ambient value that
    used to be replaced would now survive into a child — which breaks seam P's
    own requirement that un-composed plugin resolution be observably
    unchanged. It was caught by a REAL-TRAINING test whose numerics moved
    because the child suddenly scanned a directory it had never scanned:
    plugin imports consume RNG, so the trained weights differed. The frozen
    rule says a child default may never drop **the parent's BINDING**; it says
    nothing about ambient state, and reading more into it cost correctness.

    Args:
        plugin_dir: run-scoped model-plugin directory. When provided it is
            merged with the run's declared roots. `None` contributes nothing
            and leaves whatever the process inherited untouched. With no
            binding — every legacy and un-composed caller — the result is
            exactly `plugin_dir` alone, or the inherited value, byte-for-byte
            as before.
        loss_dir: run-scoped loss-plugin directory. Deliberately NOT changed
            here: `_resolve_loss_dirs` already unions the env var with the
            global losses directory on the READ side, so the loss family has
            no equivalent hole.

    Returns:
        A copy of the current environment with the above applied. Never
        mutates `os.environ`.
    """
    from ml_models.plugin_binding import (
        active_run_loss_plugin_roots,
        active_run_model_plugin_roots,
        union_plugin_roots,
    )

    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    plugin_roots = union_plugin_roots(
        [plugin_dir] if plugin_dir else (),
        active_run_model_plugin_roots(),
    )
    if plugin_roots:
        env[PLUGIN_DIRS_ENV_VAR] = os.pathsep.join(plugin_roots)
    # Step 12 / PR-12d D4c: the loss variable is UNIONED for the same reason
    # seam P unioned the model one — a child spawn must never destroy the set
    # the run declared. Two sources merge: the caller's `loss_dir` (most
    # specific, first) and the run's declared loss-plugin roots.
    loss_roots = union_plugin_roots(
        [loss_dir] if loss_dir else (),
        active_run_loss_plugin_roots(),
    )
    if loss_roots:
        env[LOSS_DIRS_ENV_VAR] = os.pathsep.join(loss_roots)
    return env
