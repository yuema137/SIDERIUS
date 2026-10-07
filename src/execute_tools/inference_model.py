"""Production inference model construction, shared with bounded measurement."""

from typing import Any

from agent.schemas.model_io_contract import ModelIOContract
from execute_tools.model_input_dtype import apply_contract_cardinality


def construct_inference_model(
    model_type: str,
    model_config: dict[str, Any],
    *,
    model_io_contract: ModelIOContract | None,
    loss_type: str,
):
    """Preserve the inference entrypoint's existing constructor contract.

    Task cardinality is resolved before configuration validation. The built-in
    fcnet constructor historically receives the loss type; other inference
    constructors receive only the config. Changing that interface is separate
    from measuring the workload that this entrypoint currently executes.
    """
    from ml_models.models_format_sandbox import get_config_class
    from ml_models.models_sandbox import MODEL_REGISTRY

    config_class = get_config_class(model_type)
    model_class = MODEL_REGISTRY.get(model_type)
    if config_class is None or model_class is None:
        raise ValueError(f"Model type '{model_type}' is not supported in MODEL_REGISTRY")
    config = config_class(**apply_contract_cardinality(model_config, model_io_contract))
    model = (
        model_class(config, loss_type=loss_type) if model_type == "fcnet" else model_class(config)
    )
    return model, config
