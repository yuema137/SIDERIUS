# agent/schemas/skill_spec.py
#
# Universal skill descriptor for the SIDERIUS skill graph.
#
# Every callable in the system — agent, tool, workflow, orchestrator — can be
# described by a SkillSpec. The spec holds the Pydantic input/output classes
# directly, so the same class is used for:
#   1. Generating OpenAI tool definitions (via .to_openai_tool())
#   2. Validating the LLM's tool-call arguments (via input_schema.model_validate())
#   3. Validating the node's output (via output_schema.model_validate())
#
# This is a Layer 1 building block. Individual nodes will expose SkillSpecs in
# Layer 2 (skill registry). See docs/architecture.md for the full roadmap.

from typing import Type, Dict, Any
from pydantic import BaseModel, Field


class SkillSpec(BaseModel):
    """
    Describes a single skill (node, tool, workflow, or orchestrator).

    Attributes:
        name:          Unique identifier for the skill (e.g. ``"tune_ml_hyperparam"``).
        description:   Human-readable summary of what the skill does. This is passed
                       to the LLM as the function description in tool-calling mode.
        input_schema:  The Pydantic ``BaseModel`` class for the skill's input.
        output_schema: The Pydantic ``BaseModel`` class for the skill's output.
    """

    model_config = {"arbitrary_types_allowed": True}

    name: str = Field(
        ...,
        description="Unique skill identifier.",
    )
    description: str = Field(
        ...,
        description="What this skill does — shown to the LLM in tool-calling mode.",
    )
    input_schema: Type[BaseModel] = Field(
        ...,
        description="Pydantic class defining the skill's input contract.",
    )
    output_schema: Type[BaseModel] = Field(
        ...,
        description="Pydantic class defining the skill's output contract.",
    )

    def to_openai_tool(self) -> Dict[str, Any]:
        """
        Convert this skill spec to an OpenAI function-calling tool definition.

        Returns a dict matching the OpenAI ``tools`` parameter format::

            {
                "type": "function",
                "function": {
                    "name": "...",
                    "description": "...",
                    "parameters": { ... JSON Schema from input_schema ... }
                }
            }

        The ``parameters`` field is generated from ``input_schema.model_json_schema()``,
        so it always reflects the current Pydantic model definition.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema.model_json_schema(),
            },
        }
