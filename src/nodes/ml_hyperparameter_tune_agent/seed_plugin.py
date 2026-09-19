"""Stage an explicit seed for both the planner and training subprocess."""

from __future__ import annotations

from ml_models.plugin_loader import register_model_in_memory
from nodes.ml_hyperparameter_tune_agent.records import _copy_seed_plugin


def stage_seed_model(source: str, plugin_dir: str, expected_model_type: str) -> str:
    """Use the same staged bytes in parent registries and child discovery.

    Schema validation checks the source declaration, not its executable import.
    Refuse failed registration before constructing the planning bridge. Explicit
    seeds must not rely on an earlier validator having populated this process.
    """
    staged = _copy_seed_plugin(source, plugin_dir)
    registered = register_model_in_memory(staged)
    if registered != expected_model_type:
        raise ValueError(
            f"Seed model registration failed: expected {expected_model_type!r}, "
            f"loaded {registered!r} from {staged!r}"
        )
    return staged
