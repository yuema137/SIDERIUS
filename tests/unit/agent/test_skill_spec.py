"""
Unit tests for agent/schemas/skill_spec.py

Tests:
  - SkillSpec construction with Pydantic classes
  - to_openai_tool() produces valid OpenAI tool format
  - JSON schema is generated from the actual Pydantic input class
  - Output schema is stored but not included in the tool definition
"""

from pydantic import BaseModel, Field

from agent.schemas.skill_spec import SkillSpec

# ---------------------------------------------------------------------------
# Dummy schemas for testing
# ---------------------------------------------------------------------------


class DummyInput(BaseModel):
    query: str = Field(..., description="The search query.")
    max_results: int = Field(default=10, description="Maximum results to return.")


class DummyOutput(BaseModel):
    results: list = Field(default_factory=list)
    total: int = 0


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestSkillSpecConstruction:
    def test_basic_creation(self):
        spec = SkillSpec(
            name="search",
            description="Search the knowledge base.",
            input_schema=DummyInput,
            output_schema=DummyOutput,
        )
        assert spec.name == "search"
        assert spec.description == "Search the knowledge base."
        assert spec.input_schema is DummyInput
        assert spec.output_schema is DummyOutput

    def test_stores_class_not_instance(self):
        spec = SkillSpec(
            name="search",
            description="Search.",
            input_schema=DummyInput,
            output_schema=DummyOutput,
        )
        # Should be the class itself, not a schema dict or instance
        assert isinstance(spec.input_schema, type)
        assert issubclass(spec.input_schema, BaseModel)


# ---------------------------------------------------------------------------
# to_openai_tool()
# ---------------------------------------------------------------------------


class TestToOpenAITool:
    def _make_spec(self) -> SkillSpec:
        return SkillSpec(
            name="search",
            description="Search the knowledge base.",
            input_schema=DummyInput,
            output_schema=DummyOutput,
        )

    def test_top_level_structure(self):
        tool = self._make_spec().to_openai_tool()
        assert tool["type"] == "function"
        assert "function" in tool

    def test_function_name_and_description(self):
        tool = self._make_spec().to_openai_tool()
        func = tool["function"]
        assert func["name"] == "search"
        assert func["description"] == "Search the knowledge base."

    def test_parameters_match_input_schema(self):
        tool = self._make_spec().to_openai_tool()
        params = tool["function"]["parameters"]
        # Should be a JSON schema generated from DummyInput
        assert params == DummyInput.model_json_schema()

    def test_parameters_contain_expected_fields(self):
        tool = self._make_spec().to_openai_tool()
        props = tool["function"]["parameters"]["properties"]
        assert "query" in props
        assert "max_results" in props

    def test_required_fields_present(self):
        tool = self._make_spec().to_openai_tool()
        required = tool["function"]["parameters"].get("required", [])
        # "query" has no default — should be required
        assert "query" in required

    def test_output_schema_not_in_tool_definition(self):
        """The OpenAI tool format only includes input parameters, not output."""
        tool = self._make_spec().to_openai_tool()
        # Output schema should not leak into the tool definition
        assert "output" not in tool["function"]
        assert "results" not in tool["function"].get("parameters", {}).get("properties", {})

    def test_reflects_schema_changes(self):
        """to_openai_tool() generates from the live class, not a cached copy."""

        class DynamicInput(BaseModel):
            x: int

        spec = SkillSpec(
            name="dynamic",
            description="Test.",
            input_schema=DynamicInput,
            output_schema=DummyOutput,
        )
        params = spec.to_openai_tool()["function"]["parameters"]
        assert "x" in params["properties"]
