# ml_models/plugin_loader.py
"""
Plugin loader for agent-generated models.

Scans agent_generated/models/ for *.py files and extends MODEL_REGISTRY
and PLUGIN_CONFIG_REGISTRY with any valid plugins found.

Plugin interface — each plugin file must define:
    PLUGIN_MODEL_TYPE  : str   — unique model key (e.g. "attn_fcnet")
    PLUGIN_CONFIG_CLASS: type  — Pydantic BaseModel subclass
    PLUGIN_MODEL_CLASS : type  — nn.Module subclass
                                  forward contract: [B, T] int → [B, 256, T] float
"""

import os
import importlib.util

AGENT_GENERATED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "agent_generated", "models",
)


def _load_plugin(path: str) -> dict | None:
    """Load a single plugin file. Returns attribute dict or None if invalid."""
    spec = importlib.util.spec_from_file_location("_siderius_plugin_tmp", path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        print(f"[PluginLoader] Failed to load {path}: {e}")
        return None

    for attr in ("PLUGIN_MODEL_TYPE", "PLUGIN_CONFIG_CLASS", "PLUGIN_MODEL_CLASS"):
        if not hasattr(module, attr):
            print(f"[PluginLoader] Skipping {os.path.basename(path)}: missing '{attr}'")
            return None

    return {
        "model_type":   module.PLUGIN_MODEL_TYPE,
        "config_class": module.PLUGIN_CONFIG_CLASS,
        "model_class":  module.PLUGIN_MODEL_CLASS,
    }


def extend_registries(model_registry: dict, config_registry: dict) -> list:
    """
    Scan agent_generated/models/ and extend both registries in-place.
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
        loaded.append(model_type)
        print(f"[PluginLoader] Loaded plugin: '{model_type}' from {fname}")

    return loaded
