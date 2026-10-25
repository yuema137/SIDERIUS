"""Disclose the same declared input facts used by deterministic validation."""

import json
from typing import Literal

from agent.prompt_rendering import prompt_boundary
from agent.schemas.model_io_contract import ModelIOContract


@prompt_boundary("validator.input_contract")
def render_input_contract(
    model_io_contract: ModelIOContract | None,
    segmentation_applicability: Literal["temporal", "not_applicable"] | None = None,
) -> str:
    """Render validated declarations without inventing probe extents or requirements."""
    if model_io_contract is None and segmentation_applicability is None:
        return ""
    parts = ["## Declared Input Contract\n\n"]
    if model_io_contract is None:
        parts.append("Normalized input tensor: undeclared.\n")
    else:
        tensor = model_io_contract.input
        parts.extend(
            [
                f"Declared input shape: {tensor.render_shape()}\n",
                "Normalized input tensor (ordered axes, roles, dimensions and all admissible "
                "dtypes): "
                + json.dumps(tensor.model_dump(mode="json"), separators=(",", ":"))
                + "\n",
                "Fixed extents are fixed. Repeated symbolic names express shared dimensions; "
                "symbols do not declare numeric ranges. Dynamic extents and omitted roles "
                "remain unspecified. Probe sizes are not additional task requirements.\n",
            ]
        )
    parts.append(f"Segmentation applicability: {segmentation_applicability or 'undeclared'}.\n")
    parts.append(
        "Segmentation applicability describes resource-probe identity; it does not override "
        "the tensor contract or establish an arbitrary valid length range.\n"
        "Assess the declared inputs. Do not demand additional channel counts or lengths "
        "merely because a configuration field accepts them. Still report failures on "
        "declared inputs, runtime errors, broken gradients and requirements explicitly "
        "present in the mathematical specification. Assess trainability separately from "
        "specification alignment.\n\n"
    )
    return "".join(parts)
