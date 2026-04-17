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

import os
import sys
import importlib.util

AGENT_GENERATED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "agent_generated", "models",
)

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
        print(f"[PluginLoader] Warning: '{os.path.basename(path)}' has invalid "
              f"PLUGIN_OUTPUT_TYPE='{output_type}', defaulting to 'classifier'")
        output_type = "classifier"

    return {
        "model_type":   module.PLUGIN_MODEL_TYPE,
        "config_class": module.PLUGIN_CONFIG_CLASS,
        "model_class":  module.PLUGIN_MODEL_CLASS,
        "output_type":  output_type,
    }


def extend_registries(model_registry: dict, config_registry: dict) -> list:
    """
    Scan agent_generated/models/ and extend both registries in-place.
    Also populates PLUGIN_OUTPUT_TYPE_REGISTRY.
    Returns list of successfully loaded plugin model_type strings.
    """
    loaded = []
    if not os.path.isdir(AGENT_GENERATED_DIR):
        return loaded

    for fname in sorted(os.listdir(AGENT_GENERATED_DIR)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue

        plugin = _load_plugin(os.path.join(AGENT_GENERATED_DIR, fname))
        if plugin is None:
            continue

        model_type = plugin["model_type"]
        if model_type in model_registry:
            print(f"[PluginLoader] Warning: plugin '{model_type}' shadows an existing registry entry.")

        model_registry[model_type]  = plugin["model_class"]
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
