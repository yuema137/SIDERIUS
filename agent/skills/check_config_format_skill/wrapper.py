# skills/check_config_format_skill/wrapper.py

import json
from typing import Dict, Any
import models_format_sandbox as fmt #

def run_skill(sandbox, **kwargs) -> Dict[str, Any]:
    try:
        # 1. Add Transformer to the schema list
        schemas = {
            "PUNetConfig": fmt.PUNetConfig.model_json_schema(),
            "AEConfig": fmt.AEConfig.model_json_schema(),
            "TransformerConfig": fmt.TransformerConfig.model_json_schema(), # Added
            "LossConfig": fmt.LossConfig.model_json_schema(),
            "TrainConfig": fmt.TrainConfig.model_json_schema()
        }

        # 2. Update constraints with the CRITICAL matching rule
        constraints_summary = (
            "CRITICAL ARCHITECTURE RULES:\n"
            "- 'smooth_l1' loss is ONLY for 'fcnet' (AE) regression.\n"
            "- 'punet' and 'transformer' are CLASSIFIERS (256 classes) and MUST use 'ce' or 'focal'.\n\n"
            "DETAILED CONSTRAINTS:\n"
            "1. PUNet: kernel_size must be ODD. Depth vs segmentation_size check active.\n"
            "2. AE: latent_dims must be a list of positive integers.\n"
            "3. Transformer: Default segmentation_size is 20000 to avoid OOM. embedding_dim must be divisible by nhead.\n"
            "4. Loss: 'focal' requires alpha/gamma. 'smooth_l1' uses beta.\n"
            "5. Train: batch_size limit is 128."
        )

        return {
            "status": "success",
            "message": "Configuration schemas and ARCHITECTURE MATCHING RULES retrieved.",
            "data": {
                "schemas": schemas,
                "quick_notes": constraints_summary
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to parse Pydantic models: {str(e)}"
        }