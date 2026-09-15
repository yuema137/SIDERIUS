# skills/check_config_format_skill/wrapper.py

from typing import Any

import ml_models.models_format_sandbox as fmt


def run_skill(sandbox, **kwargs) -> dict[str, Any]:
    try:
        schemas = {
            "PUNetConfig": fmt.PUNetConfig.model_json_schema(),
            "AEConfig": fmt.AEConfig.model_json_schema(),
            "TransformerConfig": fmt.TransformerConfig.model_json_schema(),
            "LossConfig": fmt.LossConfig.model_json_schema(),
            "TrainConfig": fmt.TrainConfig.model_json_schema(),
        }

        constraints_summary = (
            "Returned schemas define configuration format only. For model/loss "
            "compatibility, output shape and class cardinality, segmentation "
            "legality, and resource limits, consult the resolved task contracts "
            "and execution validators; those authorities decide whether a "
            "proposal is valid."
        )

        return {
            "status": "success",
            "message": "Configuration schemas and generic validation guidance retrieved.",
            "data": {"schemas": schemas, "quick_notes": constraints_summary},
        }
    except Exception as e:
        return {"status": "error", "message": f"Failed to parse Pydantic models: {e!s}"}
