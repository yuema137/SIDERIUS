# agent_generated/_loss_loader.py
"""
Loss plugin loader for agent-generated loss functions.

Mirrors ``ml_models/plugin_loader.py`` for the loss-plugin surface. Each loss
plugin file must define exactly three module-level symbols:

    PLUGIN_LOSS_TYPE         : str   — unique key (e.g. "snr_weighted_mse")
    PLUGIN_LOSS_CONFIG_CLASS : type  — Pydantic BaseModel subclass
    PLUGIN_LOSS_CLASS        : type  — nn.Module subclass

    Forward contract:
        inputs:  torch.Tensor [B, num_classes, T] float32  (model logits)
        targets: torch.Tensor [B, T]              int64    (class indices)
        returns: torch.Tensor scalar                       (requires_grad=True)

Discovery: scans the directories returned by ``_resolve_loss_dirs()``:

    1. ``SIDERIUS_LOSS_DIRS`` env var (``os.pathsep``-separated). When set,
       this is the *exclusive* list — does NOT fall back to the global default.
       Mirrors ``SIDERIUS_PLUGIN_DIRS`` semantics in
       ``ml_models/plugin_loader.py``.
    2. ``[LOSSES_DIR]`` (i.e. ``agent_generated/losses/``) — the global default
       when the env var is unset or empty.

CRITICAL: this is a SEPARATE env var from ``SIDERIUS_PLUGIN_DIRS``. Sharing
would be unsafe — if ``SIDERIUS_PLUGIN_DIRS`` points at a run-scoped *model*
directory, the loss loader would (a) silently skip all globally-registered
losses (the env-var override is exclusive, no fallback), and (b) produce log
spam by trying to load every model ``.py`` as a loss plugin and failing the
required-attr check. See ``docs/design/enable_loss_inventory.md`` § Commit L1
"Rationale" block for the full justification.

Files starting with ``_`` are skipped (same convention as
``ml_models/plugin_loader.py``). This keeps ``_stub_loss_template.py`` dormant
even when it accidentally ends up in a scanned directory.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from typing import Any

# Default loss-plugin directory: ``agent_generated/losses/``. Computed from
# this file's own location so the resolver works regardless of the caller's cwd.
LOSSES_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "losses",
)

# Env var name for run-scoped loss-plugin directories. Distinct from
# ``SIDERIUS_PLUGIN_DIRS`` — see module docstring for why.
_LOSS_DIRS_ENV_VAR = "SIDERIUS_LOSS_DIRS"

# Prefix for per-plugin module names registered in ``sys.modules`` after load.
# Distinct from ``ml_models/plugin_loader.py``'s ``siderius_plugin_`` prefix
# so a model and a loss with the same filename stem can coexist in
# ``sys.modules`` without colliding.
_MODULE_NAME_PREFIX = "siderius_loss_plugin_"


def _load_loss_plugin(path: str) -> dict[str, Any] | None:
    """Load a single loss-plugin file. Returns attribute dict or None if invalid.

    The module is registered in ``sys.modules`` under a stable, filename-
    derived name so ``inspect.getsource(cls)`` resolves correctly downstream.
    Without registration, classes defined in the plugin appear as built-ins
    and the planner-prompt source excerpt would fail to resolve them.

    Args:
        path: Absolute filesystem path to the loss plugin ``.py`` file.

    Returns:
        Dict with keys ``"loss_type"``, ``"config_class"``, ``"loss_class"`` on
        success. ``None`` when the file can't be loaded as Python or fails
        the required-attribute check — the loader logs a single line per
        rejection and continues scanning.
    """
    module_name = _MODULE_NAME_PREFIX + os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        print(f"[LossLoader] Could not resolve module spec for {path}")
        return None
    module = importlib.util.module_from_spec(spec)
    # Register BEFORE exec so the plugin can reference its own module name
    # (via ``__name__``) without surprising downstream inspect calls.
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        # Roll back the sys.modules entry on load failure so a broken plugin
        # can be fixed and retried in the same process.
        sys.modules.pop(module_name, None)
        print(f"[LossLoader] Failed to load {path}: {e}")
        return None

    for attr in ("PLUGIN_LOSS_TYPE", "PLUGIN_LOSS_CONFIG_CLASS", "PLUGIN_LOSS_CLASS"):
        if not hasattr(module, attr):
            print(f"[LossLoader] Skipping {os.path.basename(path)}: missing '{attr}'")
            return None

    return {
        "loss_type": module.PLUGIN_LOSS_TYPE,
        "config_class": module.PLUGIN_LOSS_CONFIG_CLASS,
        "loss_class": module.PLUGIN_LOSS_CLASS,
    }


def _resolve_loss_dirs() -> list[str]:
    """Return the ordered list of directories to scan for loss plugins.

    Priority:
      1. ``SIDERIUS_LOSS_DIRS`` env var — ``os.pathsep``-separated list of
         directory paths. Per-run mode: scans exactly those directories,
         does NOT fall back to ``LOSSES_DIR``.
      2. ``[LOSSES_DIR]`` — legacy global-dir mode. Back-compat default when
         the env var is unset or empty.

    Whitespace-only or empty entries in the env var are filtered out so
    ``SIDERIUS_LOSS_DIRS=":dir_a::dir_b:"`` resolves to ``["dir_a", "dir_b"]``,
    matching how shells commonly compose path-like variables.
    """
    env = os.environ.get(_LOSS_DIRS_ENV_VAR, "").strip()
    if env:
        return [p for p in env.split(os.pathsep) if p.strip()]
    return [LOSSES_DIR]


def load_loss_plugin(loss_name: str) -> dict[str, Any] | None:
    """Look up a loss plugin by its ``PLUGIN_LOSS_TYPE`` key and return its attr dict.

    Convenience wrapper consumed by L2's ``_load_custom_loss`` in
    ``ml_models/loss_models_sandbox.py``. Walks ``_resolve_loss_dirs()`` and
    returns the first plugin whose ``PLUGIN_LOSS_TYPE`` matches ``loss_name``.

    Args:
        loss_name: The ``PLUGIN_LOSS_TYPE`` key to find (e.g. ``"snr_weighted_mse"``).

    Returns:
        The plugin attribute dict (same shape as ``_load_loss_plugin``) on hit.
        ``None`` when no matching plugin is found in any resolved directory.
    """
    for loss_dir in _resolve_loss_dirs():
        if not os.path.isdir(loss_dir):
            continue
        for fname in sorted(os.listdir(loss_dir)):
            if not fname.endswith(".py") or fname.startswith("_"):
                continue
            plugin = _load_loss_plugin(os.path.join(loss_dir, fname))
            if plugin is None:
                continue
            if plugin["loss_type"] == loss_name:
                return plugin
    return None
