"""Translate the three existing one-shot bridge operations to Direct API requests."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai.messages import ModelRequest, SystemPromptPart, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.output import OutputObjectDefinition
from pydantic_ai.tools import ToolDefinition

JSON_TOOL = "siderius_json_result"


class FunctionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    description: str | None = None
    parameters: dict[str, Any]
    strict: bool | None = None


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    function: FunctionSpec


def translate(
    kwargs: dict[str, Any], *, json_object_supported: bool = False
) -> tuple[list[ModelRequest], ModelRequestParameters, str | None]:
    """Preserve complete prompt strings. Never truncate or execute a returned tool."""
    messages = kwargs["messages"]
    if [message["role"] for message in messages] != ["system", "user"]:
        raise ValueError("The optional bridge transport supports one-shot system/user requests")
    parts = [SystemPromptPart(messages[0]["content"]), UserPromptPart(messages[1]["content"])]
    json_mode = "response_format" in kwargs
    if json_mode:
        if kwargs["response_format"] != {"type": "json_object"}:
            raise ValueError("Unsupported bridge response format")
        if json_object_supported:
            return (
                [ModelRequest(parts)],
                ModelRequestParameters(
                    output_mode="prompted",
                    output_object=OutputObjectDefinition(json_schema={"type": "object"}),
                    prompted_output_template=False,
                ),
                "object",
            )
        # Admit only an actual output-tool result. This never falls back to
        # treating unconstrained text as if the provider enforced JSON.
        output = ToolDefinition(
            name=JSON_TOOL,
            description="Return the requested JSON result in value. Do not execute any action.",
            parameters_json_schema={
                "type": "object",
                "properties": {
                    "value": {
                        "anyOf": [
                            {"type": "object", "additionalProperties": True},
                            {"type": "array", "items": {}},
                        ]
                    }
                },
                "required": ["value"],
                "additionalProperties": False,
            },
            strict=False,
            kind="output",
        )
        return (
            [ModelRequest(parts)],
            ModelRequestParameters(
                output_mode="tool", output_tools=[output], allow_text_output=False
            ),
            "tool",
        )
    tools = []
    for raw in kwargs.get("tools", []):
        spec = ToolSpec.model_validate(raw)
        if spec.type != "function":
            raise ValueError("Only function tools are supported by this bridge contract")
        tools.append(
            ToolDefinition(
                name=spec.function.name,
                description=spec.function.description,
                parameters_json_schema=spec.function.parameters,
                strict=spec.function.strict,
            )
        )
    return [ModelRequest(parts)], ModelRequestParameters(function_tools=tools), None
