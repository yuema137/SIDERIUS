# ml_models/plugin_loader.py
"""
Plugin loader for agent-generated models.

Scans agent_generated/models/ for *.py files and extends MODEL_REGISTRY,
PLUGIN_CONFIG_REGISTRY, and PLUGIN_OUTPUT_TYPE_REGISTRY with any valid plugins found.

Plugin interface — each plugin file must define:
    PLUGIN_MODEL_TYPE  : str   — unique model key (e.g. "attn_fcnet")
    PLUGIN_CONFIG_CLASS: type  — Pydantic BaseModel subclass
    PLUGIN_MODEL_CLASS : type  — nn.Module subclass
                                  forward contract: [B, T] int → [B, 256, T] float
    PLUGIN_OUTPUT_TYPE : str   — "classifier" or "regressor" (optional, defaults to "classifier")
"""

import importlib.util
import os
import sys

AGENT_GENERATED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "agent_generated",
    "models",
)

# Env var name used to opt into run-scoped plugin directories. When set to a
# non-empty ``os.pathsep``-separated list of directory paths, plugin loading
# scans *only* those directories and ignores ``AGENT_GENERATED_DIR``. When
# unset or empty, the loader falls back to scanning ``AGENT_GENERATED_DIR``
# (legacy global-dir mode) — this is the back-compat default.
# See docs/run_scoped_plugins.md.
_PLUGIN_DIRS_ENV_VAR = "SIDERIUS_PLUGIN_DIRS"

# Prefix for per-plugin module names registered in ``sys.modules`` after load.
# The full name is ``_MODULE_NAME_PREFIX + <filename stem>`` so each plugin gets
# a unique, stable identity. Stability is required for ``inspect.getsource`` /
# ``inspect.getmodule`` to resolve the source file — without registration, any
# class loaded from a plugin appears as a built-in (Python's inspect machinery
# walks ``sys.modules[cls.__module__]`` to find ``__file__``). The tuner's
# Phase D.1 planner-prompt excerpt (``format_plugin_source_excerpt_block``)
# depends on that resolution.
_MODULE_NAME_PREFIX = "siderius_plugin_"

# Populated at load time by extend_registries().
# Maps plugin model_type → "classifier" or "regressor".
PLUGIN_OUTPUT_TYPE_REGISTRY: dict[str, str] = {}


def _load_plugin(path: str) -> dict | None:
    """Load a single plugin file. Returns attribute dict or None if invalid.

    The module is registered in ``sys.modules`` under a stable, filename-
    derived name so that downstream callers of ``inspect.getsource(cls)``
    (Phase D.1 — planner-prompt excerpt) can resolve the source file.
    Without this, classes defined in the plugin appear as built-ins.
    """
    module_name = _MODULE_NAME_PREFIX + os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(module_name, path)
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
        print(f"[PluginLoader] Failed to load {path}: {e}")
        return None

    for attr in ("PLUGIN_MODEL_TYPE", "PLUGIN_CONFIG_CLASS", "PLUGIN_MODEL_CLASS"):
        if not hasattr(module, attr):
            print(f"[PluginLoader] Skipping {os.path.basename(path)}: missing '{attr}'")
            return None

    # PLUGIN_OUTPUT_TYPE is optional — defaults to "classifier" for backward compat
    output_type = getattr(module, "PLUGIN_OUTPUT_TYPE", "classifier")
    if output_type not in ("classifier", "regressor", "hybrid"):
        print(
            f"[PluginLoader] Warning: '{os.path.basename(path)}' has invalid "
            f"PLUGIN_OUTPUT_TYPE='{output_type}', defaulting to 'classifier'"
        )
        output_type = "classifier"

    return {
        "model_type": module.PLUGIN_MODEL_TYPE,
        "config_class": module.PLUGIN_CONFIG_CLASS,
        "model_class": module.PLUGIN_MODEL_CLASS,
        "output_type": output_type,
    }


def _resolve_plugin_dirs() -> list[str]:
    """Return the ordered list of directories to scan for plugins.

    Priority:
      1. ``SIDERIUS_PLUGIN_DIRS`` env var — ``os.pathsep``-separated list of
         directory paths. Per-run mode: scans exactly those directories,
         does NOT fall back to ``AGENT_GENERATED_DIR``.
      2. ``[AGENT_GENERATED_DIR]`` — legacy global-dir mode. Back-compat
         default when the env var is unset or empty.

    Whitespace-only or empty entries in the env var are filtered out so
    that ``SIDERIUS_PLUGIN_DIRS=":dir_a::dir_b:"`` still resolves to
    ``["dir_a", "dir_b"]`` — this matches how shells commonly compose
    path-like variables.
    """
    env = os.environ.get(_PLUGIN_DIRS_ENV_VAR, "").strip()
    if env:
        return [p for p in env.split(os.pathsep) if p.strip()]
    return [AGENT_GENERATED_DIR]


def extend_registries(model_registry: dict, config_registry: dict) -> list:
    """
    Scan the resolved plugin directories (see ``_resolve_plugin_dirs``)
    and extend both registries in-place. Also populates
    ``PLUGIN_OUTPUT_TYPE_REGISTRY``.

    Returns the list of successfully loaded plugin ``model_type`` strings,
    in the order they were loaded across all scanned directories. When the
    same ``model_type`` appears in more than one directory, the later
    directory's plugin overwrites the earlier one (matching the existing
    shadow-warning behavior).
    """
    loaded = []
    for plugin_dir in _resolve_plugin_dirs():
        if not os.path.isdir(plugin_dir):
            continue

        for fname in sorted(os.listdir(plugin_dir)):
            if not fname.endswith(".py") or fname.startswith("_"):
                continue

            plugin = _load_plugin(os.path.join(plugin_dir, fname))
            if plugin is None:
                continue

            model_type = plugin["model_type"]
            if model_type in model_registry:
                print(
                    f"[PluginLoader] Warning: plugin '{model_type}' shadows an existing registry entry."
                )

            model_registry[model_type] = plugin["model_class"]
            config_registry[model_type] = plugin["config_class"]
            PLUGIN_OUTPUT_TYPE_REGISTRY[model_type] = plugin["output_type"]
            loaded.append(model_type)
            print(f"[PluginLoader] Loaded plugin: '{model_type}' from {fname}")

    return loaded


def get_output_type(model_type: str) -> str:
    """
    Return 'classifier' or 'regressor' for any model (built-in or plugin).

    Lookup order:
      1. BUILTIN_OUTPUT_TYPES (from models_sandbox.py)
      2. PLUGIN_OUTPUT_TYPE_REGISTRY (loaded at import time)
      3. Default: 'classifier' (the standard forward contract)
    """
    # Lazy import to avoid circular dependency (models_sandbox imports plugin_loader)
    from ml_models.models_sandbox import BUILTIN_OUTPUT_TYPES

    if model_type in BUILTIN_OUTPUT_TYPES:
        return BUILTIN_OUTPUT_TYPES[model_type]
    if model_type in PLUGIN_OUTPUT_TYPE_REGISTRY:
        return PLUGIN_OUTPUT_TYPE_REGISTRY[model_type]
    # Unknown model — default to classifier (the standard [B, 256, T] contract)
    return "classifier"
