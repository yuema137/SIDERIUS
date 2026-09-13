"""Captured entry acquisition and text for this model validator only."""

from __future__ import annotations

from types import ModuleType

from core.local_code import acquire_module, selected_member

REQUIRED_PLUGIN_ATTRIBUTES = ("PLUGIN_MODEL_TYPE", "PLUGIN_CONFIG_CLASS", "PLUGIN_MODEL_CLASS")


def captured_plugin(path: str) -> ModuleType | None:
    """Validate required symbols inside the captured-module rollback boundary."""
    with acquire_module(path) as module:
        if module is None:
            return None
        for attr in REQUIRED_PLUGIN_ATTRIBUTES:
            if not hasattr(module, attr):
                raise ValueError(f"Plugin is missing required attribute '{attr}'")
        return module


def captured_source(path: str) -> str | None:
    """The reviewed entry text is the same immutable source used for execution."""
    member = selected_member(path)
    return member.source.decode("utf-8") if member is not None else None


def read_source(path: str, captured: str | None) -> str:
    """Keep legacy disk reading when no captured member was selected."""
    if captured is not None:
        return captured
    with open(path) as stream:
        return stream.read()
