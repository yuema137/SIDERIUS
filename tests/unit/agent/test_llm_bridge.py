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

    def test_malformed_json_raises_value_error(self):
        """_chat_json raises ValueError on unparseable JSON (does not silently return {})."""
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value = _chat_response("not valid json {{")
            bridge = LLMBridge(provider="gemini", model_id="test-model")
            with pytest.raises(ValueError, match="not valid JSON"):
                bridge.generate(SYSTEM_PROMPT, USER_PROMPT)

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


# ---------------------------------------------------------------------------
# Reflect/planner model split (separate model for reflect() vs generate())
# ---------------------------------------------------------------------------

class TestReflectModelSplit:
    """
    Verify that LLMBridge can route reflect() to a different model than
    generate(), to allow cheaper / higher-quota models for the templated
    reflection step while keeping a frontier model for the planner.

    The split is controlled by the optional `reflect_model_id` constructor
    parameter. When unset, both methods use `model_id` (default behavior,
    backward compatible).
    """

    REFLECT_PROMPT_FRAGMENT = "Research Analyst"  # part of REFLECTOR_PROMPT

    def test_default_both_methods_use_same_model(self):
        """When reflect_model_id is not passed, planner and reflector
        share self.model_name (no behavior change for existing callers)."""
        bridge = LLMBridge(provider="gemini", model_id="planner-model")
        assert bridge.model_name == "planner-model"
        assert bridge.reflect_model_name == "planner-model"

    def test_explicit_none_falls_back_to_main_model(self):
        """Passing reflect_model_id=None explicitly is equivalent to
        not passing it (the parameter is optional with default None)."""
        bridge = LLMBridge(provider="gemini", model_id="planner-model",
                           reflect_model_id=None)
        assert bridge.reflect_model_name == "planner-model"

    def test_reflect_model_id_separates_planner_from_reflector(self):
        """When reflect_model_id is set, the two attributes diverge."""
        bridge = LLMBridge(provider="gemini",
                           model_id="planner-model",
                           reflect_model_id="reflector-model")
        assert bridge.model_name == "planner-model"
        assert bridge.reflect_model_name == "reflector-model"

    def test_generate_always_uses_main_model(self):
        """generate() must always pass model=self.model_name to the API,
        regardless of whether reflect_model_id is set."""
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            mock_create = MockOpenAI.return_value.chat.completions.create
            mock_create.return_value = _chat_response(VALID_JSON_STR)
            bridge = LLMBridge(provider="gemini",
                               model_id="planner-model",
                               reflect_model_id="reflector-model")
            bridge.generate(SYSTEM_PROMPT, USER_PROMPT)
            assert mock_create.call_args.kwargs["model"] == "planner-model"

    def test_reflect_uses_reflect_model_when_split(self):
        """reflect() must pass model=self.reflect_model_name when
        reflect_model_id was set in __init__."""
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            mock_create = MockOpenAI.return_value.chat.completions.create
            mock_create.return_value = _chat_response(VALID_JSON_STR)
            bridge = LLMBridge(provider="gemini",
                               model_id="planner-model",
                               reflect_model_id="reflector-model")
            bridge.reflect(
                exp_id="exp_001",
                hypothesis="test hypothesis",
                actual_results={"denoising_score": 1.5},
            )
            assert mock_create.call_args.kwargs["model"] == "reflector-model"

    def test_reflect_uses_main_model_when_not_split(self):
        """When reflect_model_id is not set, reflect() must use the
        same model as generate() (backward-compat path)."""
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            mock_create = MockOpenAI.return_value.chat.completions.create
            mock_create.return_value = _chat_response(VALID_JSON_STR)
            bridge = LLMBridge(provider="gemini", model_id="single-model")
            bridge.reflect(
                exp_id="exp_001",
                hypothesis="test hypothesis",
                actual_results={"denoising_score": 1.5},
            )
            assert mock_create.call_args.kwargs["model"] == "single-model"

    def test_reflect_uses_reflector_system_prompt(self):
        """reflect() must use REFLECTOR_PROMPT (not PLANNER_PROMPT) as the
        system prompt — it's still routed to the reflector regardless of
        which model handles it."""
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            mock_create = MockOpenAI.return_value.chat.completions.create
            mock_create.return_value = _chat_response(VALID_JSON_STR)
            bridge = LLMBridge(provider="gemini",
                               model_id="planner-model",
                               reflect_model_id="reflector-model")
            bridge.reflect(
                exp_id="exp_001",
                hypothesis="test hypothesis",
                actual_results={"denoising_score": 1.5},
            )
            messages = mock_create.call_args.kwargs["messages"]
            # The reflector system prompt should be present (signature
            # phrase from REFLECTOR_PROMPT)
            assert self.REFLECT_PROMPT_FRAGMENT in messages[0]["content"]

    def test_two_calls_in_sequence_use_correct_models(self):
        """A planner call followed by a reflector call on the same bridge
        should produce two distinct API calls with different model= args.
        This is the end-to-end signature of the split working."""
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            mock_create = MockOpenAI.return_value.chat.completions.create
            mock_create.return_value = _chat_response(VALID_JSON_STR)
            bridge = LLMBridge(provider="gemini",
                               model_id="planner-model",
                               reflect_model_id="reflector-model")
            bridge.generate(SYSTEM_PROMPT, USER_PROMPT)
            bridge.reflect(
                exp_id="exp_001",
                hypothesis="test hypothesis",
                actual_results={"denoising_score": 1.5},
            )
            # Two API calls expected, with two distinct model values
            assert mock_create.call_count == 2
            first_model = mock_create.call_args_list[0].kwargs["model"]
            second_model = mock_create.call_args_list[1].kwargs["model"]
            assert first_model == "planner-model"
            assert second_model == "reflector-model"


# ---------------------------------------------------------------------------
# Cross-provider reflect support (Phase A.2)
# ---------------------------------------------------------------------------

class TestReflectProviderSplit:
    """
    Verify that LLMBridge can route reflect() to a completely different
    provider than generate(), instantiating a second OpenAI client when
    the providers differ. This is the Phase A.2 extension on top of the
    Phase A.1 model split.
    """

    def test_default_reflect_provider_falls_back_to_main_provider(self):
        """When reflect_provider is not passed, both methods use the
        same provider. self.reflect_provider equals self.provider."""
        bridge = LLMBridge(provider="gemini", model_id="planner-model")
        assert bridge.provider == "gemini"
        assert bridge.reflect_provider == "gemini"

    def test_explicit_same_provider_reuses_client(self):
        """When reflect_provider equals provider, the bridge reuses the
        main client (no duplicate connection)."""
        bridge = LLMBridge(provider="gemini",
                           model_id="planner-model",
                           reflect_provider="gemini",
                           reflect_model_id="reflector-model")
        assert bridge.client is bridge.reflect_client
        assert bridge.provider == "gemini"
        assert bridge.reflect_provider == "gemini"

    def test_cross_provider_creates_distinct_clients(self):
        """When reflect_provider differs from provider, the bridge
        instantiates a second OpenAI client. The two are distinct
        objects (verified by `is not` identity check)."""
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            # Each call to OpenAI(...) returns a different mock instance
            instances = [MagicMock(name="main_client"),
                         MagicMock(name="reflect_client")]
            MockOpenAI.side_effect = instances

            bridge = LLMBridge(provider="gemini",
                               model_id="planner-model",
                               reflect_provider="openai",
                               reflect_model_id="reflector-model")
            assert bridge.client is not bridge.reflect_client
            assert bridge.client is instances[0]
            assert bridge.reflect_client is instances[1]
            assert bridge.provider == "gemini"
            assert bridge.reflect_provider == "openai"
            # OpenAI() should have been called exactly twice — once for
            # the main client, once for the reflect client
            assert MockOpenAI.call_count == 2

    def test_cross_provider_routes_reflect_to_second_client(self):
        """When the bridge has two clients, reflect() must call the
        SECOND client's chat.completions.create, not the first."""
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            main_client = MagicMock(name="main_client")
            reflect_client = MagicMock(name="reflect_client")
            main_client.chat.completions.create.return_value = _chat_response(VALID_JSON_STR)
            reflect_client.chat.completions.create.return_value = _chat_response(VALID_JSON_STR)
            MockOpenAI.side_effect = [main_client, reflect_client]

            bridge = LLMBridge(provider="gemini",
                               model_id="planner-model",
                               reflect_provider="openai",
                               reflect_model_id="reflector-model")

            # generate() must hit the main client
            bridge.generate(SYSTEM_PROMPT, USER_PROMPT)
            assert main_client.chat.completions.create.call_count == 1
            assert reflect_client.chat.completions.create.call_count == 0

            # reflect() must hit the reflect client (NOT the main client)
            bridge.reflect(
                exp_id="exp_001",
                hypothesis="test hypothesis",
                actual_results={"denoising_score": 1.5},
            )
            assert main_client.chat.completions.create.call_count == 1  # unchanged
            assert reflect_client.chat.completions.create.call_count == 1  # incremented

            # And verify each client got the right model name
            assert main_client.chat.completions.create.call_args.kwargs["model"] == "planner-model"
            assert reflect_client.chat.completions.create.call_args.kwargs["model"] == "reflector-model"

    def test_reflect_provider_only_no_model_override(self):
        """reflect_provider can be set without reflect_model_id. In that
        case the reflector hits the second provider but with the main
        model name (which may or may not exist on that provider — the
        bridge does not validate)."""
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            MockOpenAI.side_effect = [MagicMock(), MagicMock()]
            bridge = LLMBridge(provider="gemini",
                               model_id="shared-model-name",
                               reflect_provider="openai")
            assert bridge.reflect_model_name == "shared-model-name"
            assert bridge.client is not bridge.reflect_client

    def test_unknown_reflect_provider_raises(self):
        """An unknown reflect_provider should fail-fast at construction
        time with a clear error pointing at the known providers list."""
        with pytest.raises(ValueError, match="Unknown reflect_provider"):
            LLMBridge(provider="gemini",
                      model_id="planner-model",
                      reflect_provider="nonexistent",
                      reflect_model_id="reflector-model")

    def test_reflect_provider_is_lowercased(self):
        """Like the main provider, reflect_provider should be normalized
        to lowercase for consistency."""
        bridge = LLMBridge(provider="gemini",
                           model_id="planner-model",
                           reflect_provider="GEMINI",
                           reflect_model_id="reflector-model")
        assert bridge.reflect_provider == "gemini"
        # And same-after-lowercase should still reuse the client
        assert bridge.client is bridge.reflect_client
