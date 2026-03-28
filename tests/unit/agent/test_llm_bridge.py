"""
Unit tests for agent/llm_bridge.py

Mocks the unified openai.OpenAI client to verify:
  - __init__       resolves known/unknown providers correctly
  - list_models    returns sorted model IDs
  - generate()     returns a Dict (JSON mode), handles malformed JSON
  - generate_text() returns a str (plain-text mode)
  - tool_call()    returns a ToolCallResult with parsed arguments
  - All methods are provider-agnostic (single code path)
"""
import json
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from agent.llm_bridge import LLMBridge, ToolCallResult, _KNOWN_PROVIDERS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = "You are a helpful assistant."
USER_PROMPT = "Describe the sky."

VALID_JSON_STR = '{"color": "blue", "clouds": true}'
VALID_JSON_DICT = {"color": "blue", "clouds": True}
PLAIN_TEXT = "The sky is blue with scattered clouds."


def _chat_response(content: str) -> MagicMock:
    """Build a mock OpenAI chat completion response."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    return response


def _tool_call_response(name: str, arguments: dict, call_id: str = "call_abc123") -> MagicMock:
    """Build a mock OpenAI chat completion response with a tool call."""
    tc = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments)
    tc.id = call_id
    msg = MagicMock()
    msg.tool_calls = [tc]
    msg.content = None
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    return response


# ---------------------------------------------------------------------------
# __init__ — provider resolution
# ---------------------------------------------------------------------------

class TestInit:

    def test_known_provider_gemini(self):
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            bridge = LLMBridge(provider="gemini", model_id="test-model")
        assert bridge.provider == "gemini"
        assert bridge.model_name == "test-model"
        MockOpenAI.assert_called_once()
        call_kwargs = MockOpenAI.call_args
        assert call_kwargs.kwargs["base_url"] == _KNOWN_PROVIDERS["gemini"]["base_url"]

    def test_known_provider_openai(self):
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            bridge = LLMBridge(provider="openai", model_id="gpt-4o")
        assert bridge.provider == "openai"
        assert bridge.model_name == "gpt-4o"
        MockOpenAI.assert_called_once()
        # OpenAI has no base_url override — should not be in kwargs
        call_kwargs = MockOpenAI.call_args
        assert "base_url" not in call_kwargs.kwargs

    def test_known_provider_default_model(self):
        with patch("agent.llm_bridge.OpenAI"):
            bridge = LLMBridge(provider="gemini")
        assert bridge.model_name == _KNOWN_PROVIDERS["gemini"]["default_model"]

    def test_unknown_provider_with_explicit_args(self):
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            bridge = LLMBridge(
                provider="custom",
                model_id="my-model",
                base_url="https://example.com/v1",
                api_key="test-key",
            )
        assert bridge.provider == "custom"
        assert bridge.model_name == "my-model"
        assert bridge.api_key == "test-key"
        call_kwargs = MockOpenAI.call_args
        assert call_kwargs.kwargs["base_url"] == "https://example.com/v1"
        assert call_kwargs.kwargs["api_key"] == "test-key"

    def test_unknown_provider_no_model_id_is_none(self):
        """Unknown provider without model_id defaults to None."""
        with patch("agent.llm_bridge.OpenAI"):
            bridge = LLMBridge(provider="custom", api_key="k")
        assert bridge.model_name is None

    def test_explicit_args_override_known_defaults(self):
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            bridge = LLMBridge(
                provider="gemini",
                model_id="override-model",
                base_url="https://override.com/v1",
                api_key="override-key",
            )
        assert bridge.model_name == "override-model"
        assert bridge.api_key == "override-key"
        call_kwargs = MockOpenAI.call_args
        assert call_kwargs.kwargs["base_url"] == "https://override.com/v1"

    def test_provider_is_lowercased(self):
        with patch("agent.llm_bridge.OpenAI"):
            bridge = LLMBridge(provider="OPENAI", model_id="gpt-4o")
        assert bridge.provider == "openai"


# ---------------------------------------------------------------------------
# list_models
# ---------------------------------------------------------------------------

class TestListModels:

    def test_returns_sorted_ids(self):
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            m1 = MagicMock()
            m1.id = "model-b"
            m2 = MagicMock()
            m2.id = "model-a"
            MockOpenAI.return_value.models.list.return_value = [m1, m2]

            bridge = LLMBridge(provider="openai", model_id="gpt-4o")
            result = bridge.list_models()

        assert result == ["model-a", "model-b"]


# ---------------------------------------------------------------------------
# generate() — JSON mode
# ---------------------------------------------------------------------------

class TestGenerate:

    def test_returns_dict(self):
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value = _chat_response(VALID_JSON_STR)
            bridge = LLMBridge(provider="gemini", model_id="test-model")
            result = bridge.generate(SYSTEM_PROMPT, USER_PROMPT)
        assert result == VALID_JSON_DICT

    def test_json_mode_requested(self):
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            mock_create = MockOpenAI.return_value.chat.completions.create
            mock_create.return_value = _chat_response(VALID_JSON_STR)
            bridge = LLMBridge(provider="openai", model_id="gpt-4o")
            bridge.generate(SYSTEM_PROMPT, USER_PROMPT)
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["response_format"] == {"type": "json_object"}

    def test_messages_contain_system_and_user(self):
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            mock_create = MockOpenAI.return_value.chat.completions.create
            mock_create.return_value = _chat_response(VALID_JSON_STR)
            bridge = LLMBridge(provider="gemini", model_id="test-model")
            bridge.generate(SYSTEM_PROMPT, USER_PROMPT)
            messages = mock_create.call_args.kwargs["messages"]
            assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
            assert messages[1] == {"role": "user", "content": USER_PROMPT}

    def test_malformed_json_returns_empty_dict(self):
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value = _chat_response("not valid json {{")
            bridge = LLMBridge(provider="gemini", model_id="test-model")
            result = bridge.generate(SYSTEM_PROMPT, USER_PROMPT)
        assert result == {}

    def test_markdown_fenced_json_is_parsed(self):
        fenced = "```json\n" + VALID_JSON_STR + "\n```"
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value = _chat_response(fenced)
            bridge = LLMBridge(provider="openai", model_id="gpt-4o")
            result = bridge.generate(SYSTEM_PROMPT, USER_PROMPT)
        assert result == VALID_JSON_DICT

    def test_provider_agnostic(self):
        """Same code path regardless of provider — both go through chat.completions.create."""
        for provider in ["gemini", "openai"]:
            with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
                mock_create = MockOpenAI.return_value.chat.completions.create
                mock_create.return_value = _chat_response(VALID_JSON_STR)
                bridge = LLMBridge(provider=provider, model_id="test-model")
                result = bridge.generate(SYSTEM_PROMPT, USER_PROMPT)
            assert result == VALID_JSON_DICT
            mock_create.assert_called_once()


# ---------------------------------------------------------------------------
# generate_text() — plain text mode
# ---------------------------------------------------------------------------

class TestGenerateText:

    def test_returns_str(self):
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value = _chat_response(PLAIN_TEXT)
            bridge = LLMBridge(provider="gemini", model_id="test-model")
            result = bridge.generate_text(SYSTEM_PROMPT, USER_PROMPT)
        assert isinstance(result, str)
        assert result == PLAIN_TEXT

    def test_no_json_mode_requested(self):
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            mock_create = MockOpenAI.return_value.chat.completions.create
            mock_create.return_value = _chat_response(PLAIN_TEXT)
            bridge = LLMBridge(provider="openai", model_id="gpt-4o")
            bridge.generate_text(SYSTEM_PROMPT, USER_PROMPT)
            call_kwargs = mock_create.call_args.kwargs
            assert "response_format" not in call_kwargs

    def test_strips_whitespace(self):
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value = _chat_response("  hello  \n")
            bridge = LLMBridge(provider="gemini", model_id="test-model")
            result = bridge.generate_text(SYSTEM_PROMPT, USER_PROMPT)
        assert result == "hello"

    def test_provider_agnostic(self):
        """Same code path regardless of provider."""
        for provider in ["gemini", "openai"]:
            with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
                mock_create = MockOpenAI.return_value.chat.completions.create
                mock_create.return_value = _chat_response(PLAIN_TEXT)
                bridge = LLMBridge(provider=provider, model_id="test-model")
                result = bridge.generate_text(SYSTEM_PROMPT, USER_PROMPT)
            assert result == PLAIN_TEXT
            mock_create.assert_called_once()


# ---------------------------------------------------------------------------
# tool_call() — structured tool calling
# ---------------------------------------------------------------------------

SAMPLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search the knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
        },
    }
]


class TestToolCall:

    def test_returns_tool_call_result(self):
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            mock_create = MockOpenAI.return_value.chat.completions.create
            mock_create.return_value = _tool_call_response(
                name="search", arguments={"query": "dark matter"}, call_id="call_001"
            )
            bridge = LLMBridge(provider="openai", model_id="gpt-4o")
            result = bridge.tool_call(SYSTEM_PROMPT, USER_PROMPT, SAMPLE_TOOLS)

        assert isinstance(result, ToolCallResult)
        assert result.name == "search"
        assert result.arguments == {"query": "dark matter"}
        assert result.call_id == "call_001"

    def test_arguments_are_parsed_dict(self):
        """arguments should be a parsed dict, not a JSON string."""
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            mock_create = MockOpenAI.return_value.chat.completions.create
            mock_create.return_value = _tool_call_response(
                name="search", arguments={"query": "test", "max_results": 5}
            )
            bridge = LLMBridge(provider="gemini", model_id="test-model")
            result = bridge.tool_call(SYSTEM_PROMPT, USER_PROMPT, SAMPLE_TOOLS)

        assert isinstance(result.arguments, dict)
        assert result.arguments["max_results"] == 5

    def test_tools_passed_to_api(self):
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            mock_create = MockOpenAI.return_value.chat.completions.create
            mock_create.return_value = _tool_call_response(
                name="search", arguments={"query": "test"}
            )
            bridge = LLMBridge(provider="openai", model_id="gpt-4o")
            bridge.tool_call(SYSTEM_PROMPT, USER_PROMPT, SAMPLE_TOOLS)

            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["tools"] == SAMPLE_TOOLS
            assert call_kwargs["tool_choice"] == "auto"

    def test_raises_when_no_tool_call_returned(self):
        """If the model responds with text instead of a tool call, raise ValueError."""
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            # _chat_response sets tool_calls=None
            mock_create = MockOpenAI.return_value.chat.completions.create
            mock_create.return_value = _chat_response("I can't use tools.")
            bridge = LLMBridge(provider="openai", model_id="gpt-4o")

            with pytest.raises(ValueError, match="did not return a tool call"):
                bridge.tool_call(SYSTEM_PROMPT, USER_PROMPT, SAMPLE_TOOLS)

    def test_tool_call_result_is_frozen(self):
        """ToolCallResult is immutable (frozen dataclass)."""
        result = ToolCallResult(name="x", arguments={"a": 1}, call_id="id")
        with pytest.raises(AttributeError):
            result.name = "y"
