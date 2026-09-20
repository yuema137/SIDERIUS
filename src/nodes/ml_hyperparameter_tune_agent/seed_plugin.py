"""Stage a seed and fill missing standalone-parent registration."""

from __future__ import annotations

from ml_models.models_format_sandbox import get_config_class
from ml_models.models_sandbox import MODEL_REGISTRY
from ml_models.plugin_loader import (
    UnknownOutputContractError,
    get_output_type,
    register_model_in_memory,
)
from nodes.ml_hyperparameter_tune_agent.records import _copy_seed_plugin


def stage_seed_model(source: str, plugin_dir: str, expected_model_type: str) -> str:
    """Preserve workflow registration; fill it from staged bytes when missing.

    Schema validation checks the source declaration, not its executable import.
    Refuse failed registration before constructing the planning bridge. Explicit
    seeds must not rely on an earlier validator having populated this process.
    An already registered workflow seed retains its existing classes and import
    side effects; only the missing standalone-parent registration is added.
    """
    staged = _copy_seed_plugin(source, plugin_dir)
    if expected_model_type in MODEL_REGISTRY and get_config_class(expected_model_type) is not None:
        try:
            get_output_type(expected_model_type)
        except UnknownOutputContractError:
            pass
        else:
            return staged
    registered = register_model_in_memory(staged)
    if registered != expected_model_type:
        raise ValueError(
            f"Seed model registration failed: expected {expected_model_type!r}, "
            f"loaded {registered!r} from {staged!r}"
        )
    return staged
