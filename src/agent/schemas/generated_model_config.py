"""Shared value contract for newly generated model architecture defaults.

Registered model schemas and tuner inputs own their own supported value types.
Only the implementation path imposes this scalar-default restriction.
"""

from collections.abc import Mapping
from typing import Any

GENERATED_MODEL_CONFIG_GUIDANCE = (
    "## Generated model configuration contract\n"
    "Without a populated model_config.model_name reuse selector, the implementor "
    "generates a new model. Its architecture defaults in baseline_config.model_config "
    "must be individual int, float or bool values, not strings, lists, mappings or null. "
    "model_type is a routing identifier; segmentation_size and batch_size retain "
    "their template-owned contracts. Naming an "
    "existing model_type alone does not select reuse. Express configurable stages as "
    "named scalar fields and describe their relationship in the architecture. Do not "
    "silently discard structure or stringify containers. To reuse a registered model, "
    "set baseline_config.model_config.model_name to its registered name and follow that "
    "model's configuration schema. "
    "This restriction does not apply to train_config or loss_config."
)


def non_scalar_defaults(values: Mapping[str, Any]) -> dict[str, str]:
    """Report unsupported generated defaults without coercing their values."""
    return {
        name: type(value).__name__
        for name, value in values.items()
        if not isinstance(value, (int, float, bool))
    }


def validate_implementation_baseline(baseline: Mapping[str, Any]) -> None:
    """Check the actual generation/reuse route before implementation work.

    Omitted model_config remains supported for callers relying on generated
    defaults. Reuse membership and registered schema validation retain their
    existing owners. Never infer reuse from model_type alone.
    """
    if "model_config" not in baseline:
        return
    config = baseline["model_config"]
    if not isinstance(config, dict):
        raise ValueError("baseline_config.model_config must be an object")
    reuse_name = config.get("model_name")
    if reuse_name:
        if not isinstance(reuse_name, str):
            raise ValueError("baseline_config.model_config.model_name must be a string for reuse")
        return
    architecture = {
        key: value
        for key, value in config.items()
        if key not in {"model_type", "model_name", "segmentation_size", "batch_size"}
    }
    invalid = non_scalar_defaults(architecture)
    if invalid:
        paths = ", ".join(
            f"baseline_config.model_config.{name} ({kind})" for name, kind in invalid.items()
        )
        raise ValueError(
            f"Unsupported generated model defaults: {paths}. New model architecture "
            "fields must be int, float or bool. Express the architecture with named "
            "scalar fields before implementation, or explicitly reuse a registered "
            "model through model_config.model_name; do not discard or stringify values."
        )
