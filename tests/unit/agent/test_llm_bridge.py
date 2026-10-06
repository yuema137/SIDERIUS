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
from typing import Optional
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from agent.llm_bridge import (
    _KNOWN_PROVIDERS,
    _PLANNER_SCORE_TABLE_FALLBACK,
    _REFLECTOR_SCORE_TABLE_FALLBACK,
    LLMBridge,
    ToolCallResult,
)
from agent.prompts import PLANNER_PROMPT, REFLECTOR_PROMPT
from tests.helpers.metric_fixtures import accuracy_like_spec, shipped_spec
from tests.helpers.tuner_prompt_fixtures import TASK_RENDER


@pytest.fixture(autouse=True)
def _provider_keys_present(monkeypatch):
    """Pin every provider key PRESENT for this module.

    These tests construct bridges for gemini and deepseek to exercise
    provider/model resolution, and mock the SDK so no call is ever made — so
    they never needed a real key, and never said so either way. They simply
    inherited whatever the machine happened to export.

    That became load-bearing when F-SCANI-1 made the constructor refuse a
    provider whose key env is unset: the suite then PASSED on a developer box
    with keys exported and FAILED on a CI runner without them. Nothing in the
    file changed; the ambient environment decided the result.

    Pinning here makes the outcome the same on both. The refusal's own tests
    pin the OTHER direction — ``monkeypatch.delenv`` — so neither suite is at
    the mercy of the environment, and a dev box with keys exported cannot
    hide a refusal that CI would hit.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")


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
    def test_explicit_openai_effort_is_sent_on_each_request_path(self):
        with patch("agent.llm_bridge.OpenAI") as mock_openai:
            client = mock_openai.return_value
            client.chat.completions.create.return_value = _chat_response(VALID_JSON_STR)
            bridge = LLMBridge(provider="openai", model_id="gpt-5.6-sol", reasoning_effort="medium")
            bridge.generate(SYSTEM_PROMPT, USER_PROMPT, label="test.json")
            assert client.chat.completions.create.call_args.kwargs["reasoning_effort"] == "medium"
            client.chat.completions.create.return_value = _chat_response(PLAIN_TEXT)
            bridge.generate_text(SYSTEM_PROMPT, USER_PROMPT, label="test.text")
            assert client.chat.completions.create.call_args.kwargs["reasoning_effort"] == "medium"
            client.chat.completions.create.return_value = _tool_call_response("done", {})
            bridge.tool_call(SYSTEM_PROMPT, USER_PROMPT, [], label="test.tool")
            assert client.chat.completions.create.call_args.kwargs["reasoning_effort"] == "medium"

    def test_reflector_can_use_independent_effort_without_affecting_main(self):
        with patch("agent.llm_bridge.OpenAI") as mock_openai:
            client = mock_openai.return_value
            client.chat.completions.create.return_value = _chat_response(VALID_JSON_STR)
            bridge = LLMBridge(
                provider="openai",
                model_id="gpt-5.6-sol",
                reasoning_effort="medium",
                reflect_reasoning_effort="high",
            )
            bridge._chat_json(
                bridge.reflect_client,
                bridge.reflect_model_name,
                SYSTEM_PROMPT,
                USER_PROMPT,
                label="tuner.reflector",
            )
            assert client.chat.completions.create.call_args.kwargs["reasoning_effort"] == "high"
            bridge.generate(SYSTEM_PROMPT, USER_PROMPT, label="test.main")
            assert client.chat.completions.create.call_args.kwargs["reasoning_effort"] == "medium"

    def test_other_providers_cannot_silently_accept_openai_effort(self):
        with pytest.raises(ValueError, match="requires the OpenAI provider"):
            LLMBridge(provider="gemini", reasoning_effort="medium")

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
            MockOpenAI.return_value.chat.completions.create.return_value = _chat_response(
                VALID_JSON_STR
            )
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
        """_chat_json retries on unparseable JSON and surfaces ValueError after
        the bounded budget is exhausted (does not silently return {})."""
        with (
            patch("agent.llm_bridge.OpenAI") as MockOpenAI,
            patch("core.execution_deadline.time.sleep"),
        ):
            mock_create = MockOpenAI.return_value.chat.completions.create
            mock_create.return_value = _chat_response("not valid json {{")
            bridge = LLMBridge(provider="gemini", model_id="test-model")
            with pytest.raises(ValueError, match="not valid JSON"):
                bridge.generate(SYSTEM_PROMPT, USER_PROMPT)
            # 1 initial + _CONTENT_RETRY_BUDGET retries = 4 calls
            assert mock_create.call_count == bridge._CONTENT_RETRY_BUDGET + 1

    def test_extra_json_object_after_valid_one_is_discarded(self):
        """Direct repro of the explore_novel_v4_0425 crash: the LLM emitted a
        valid JSON object, then a newline, then a SECOND JSON object. Strict
        ``json.loads`` raised ``Extra data: line 2 column 1``. The bridge now
        uses ``raw_decode`` so the first object is accepted and the trailing
        content is discarded — production runs no longer crash on this."""
        payload = VALID_JSON_STR + "\n" + '{"second": "ignored"}'
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value = _chat_response(payload)
            bridge = LLMBridge(provider="openai", model_id="gpt-4o")
            result = bridge.generate(SYSTEM_PROMPT, USER_PROMPT)
        assert result == VALID_JSON_DICT

    def test_trailing_prose_after_valid_json_is_discarded(self):
        """Trailing free-form commentary after a valid JSON object must not
        crash. Same robustness contract as the dual-object case."""
        payload = VALID_JSON_STR + "\nThat's my answer — let me know if you want changes."
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value = _chat_response(payload)
            bridge = LLMBridge(provider="openai", model_id="gpt-4o")
            result = bridge.generate(SYSTEM_PROMPT, USER_PROMPT)
        assert result == VALID_JSON_DICT

    def test_non_dict_or_list_first_token_raises(self):
        """If the first JSON token is a bare string/number/bool, the response
        violates the caller contract (which expects a dict/list). The bridge
        retries the bounded budget and then surfaces ValueError so downstream
        code never receives a primitive."""
        with (
            patch("agent.llm_bridge.OpenAI") as MockOpenAI,
            patch("core.execution_deadline.time.sleep"),
        ):
            mock_create = MockOpenAI.return_value.chat.completions.create
            mock_create.return_value = _chat_response('"just a string"')
            bridge = LLMBridge(provider="openai", model_id="gpt-4o")
            with pytest.raises(ValueError, match="not valid JSON"):
                bridge.generate(SYSTEM_PROMPT, USER_PROMPT)
            assert mock_create.call_count == bridge._CONTENT_RETRY_BUDGET + 1

    def test_empty_content_retried_then_succeeds(self):
        """Reproduces the deepseek-v4-pro failure mode: HTTP 200 with empty
        content body. The bridge must retry and eventually surface the valid
        response on a later attempt rather than crash the whole chain."""
        with (
            patch("agent.llm_bridge.OpenAI") as MockOpenAI,
            patch("core.execution_deadline.time.sleep"),
        ):
            mock_create = MockOpenAI.return_value.chat.completions.create
            # First two calls return empty, third returns valid JSON.
            mock_create.side_effect = [
                _chat_response(""),
                _chat_response(""),
                _chat_response(VALID_JSON_STR),
            ]
            bridge = LLMBridge(provider="deepseek", model_id="deepseek-v4-pro")
            result = bridge.generate(SYSTEM_PROMPT, USER_PROMPT)
        assert result == VALID_JSON_DICT
        assert mock_create.call_count == 3

    def test_malformed_then_valid_succeeds(self):
        """Transient JSON-decode failure on the first call recovers via retry."""
        with (
            patch("agent.llm_bridge.OpenAI") as MockOpenAI,
            patch("core.execution_deadline.time.sleep"),
        ):
            mock_create = MockOpenAI.return_value.chat.completions.create
            mock_create.side_effect = [
                _chat_response("garbage {{"),
                _chat_response(VALID_JSON_STR),
            ]
            bridge = LLMBridge(provider="openai", model_id="gpt-4o")
            result = bridge.generate(SYSTEM_PROMPT, USER_PROMPT)
        assert result == VALID_JSON_DICT
        assert mock_create.call_count == 2

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
            MockOpenAI.return_value.chat.completions.create.return_value = _chat_response(
                PLAIN_TEXT
            )
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
            MockOpenAI.return_value.chat.completions.create.return_value = _chat_response(
                "  hello  \n"
            )
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
        with patch("agent.llm_bridge.OpenAI"):
            bridge = LLMBridge(provider="gemini", model_id="planner-model")
        assert bridge.model_name == "planner-model"
        assert bridge.reflect_model_name == "planner-model"

    def test_explicit_none_falls_back_to_main_model(self):
        """Passing reflect_model_id=None explicitly is equivalent to
        not passing it (the parameter is optional with default None)."""
        with patch("agent.llm_bridge.OpenAI"):
            bridge = LLMBridge(provider="gemini", model_id="planner-model", reflect_model_id=None)
        assert bridge.reflect_model_name == "planner-model"

    def test_reflect_model_id_separates_planner_from_reflector(self):
        """When reflect_model_id is set, the two attributes diverge."""
        with patch("agent.llm_bridge.OpenAI"):
            bridge = LLMBridge(
                provider="gemini", model_id="planner-model", reflect_model_id="reflector-model"
            )
        assert bridge.model_name == "planner-model"
        assert bridge.reflect_model_name == "reflector-model"

    def test_generate_always_uses_main_model(self):
        """generate() must always pass model=self.model_name to the API,
        regardless of whether reflect_model_id is set."""
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            mock_create = MockOpenAI.return_value.chat.completions.create
            mock_create.return_value = _chat_response(VALID_JSON_STR)
            bridge = LLMBridge(
                provider="gemini", model_id="planner-model", reflect_model_id="reflector-model"
            )
            bridge.generate(SYSTEM_PROMPT, USER_PROMPT)
            assert mock_create.call_args.kwargs["model"] == "planner-model"

    def test_reflect_uses_reflect_model_when_split(self):
        """reflect() must pass model=self.reflect_model_name when
        reflect_model_id was set in __init__."""
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            mock_create = MockOpenAI.return_value.chat.completions.create
            mock_create.return_value = _chat_response(VALID_JSON_STR)
            bridge = LLMBridge(
                provider="gemini", model_id="planner-model", reflect_model_id="reflector-model"
            )
            bridge.reflect(
                exp_id="exp_001",
                hypothesis="test hypothesis",
                actual_results={"denoising_score": 1.5},
                metric_spec=shipped_spec(),
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
                metric_spec=shipped_spec(),
            )
            assert mock_create.call_args.kwargs["model"] == "single-model"

    def test_reflect_uses_reflector_system_prompt(self):
        """reflect() must use REFLECTOR_PROMPT (not PLANNER_PROMPT) as the
        system prompt — it's still routed to the reflector regardless of
        which model handles it."""
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            mock_create = MockOpenAI.return_value.chat.completions.create
            mock_create.return_value = _chat_response(VALID_JSON_STR)
            bridge = LLMBridge(
                provider="gemini", model_id="planner-model", reflect_model_id="reflector-model"
            )
            bridge.reflect(
                exp_id="exp_001",
                hypothesis="test hypothesis",
                actual_results={"denoising_score": 1.5},
                metric_spec=shipped_spec(),
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
            bridge = LLMBridge(
                provider="gemini", model_id="planner-model", reflect_model_id="reflector-model"
            )
            bridge.generate(SYSTEM_PROMPT, USER_PROMPT)
            bridge.reflect(
                exp_id="exp_001",
                hypothesis="test hypothesis",
                actual_results={"denoising_score": 1.5},
                metric_spec=shipped_spec(),
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
        with patch("agent.llm_bridge.OpenAI"):
            bridge = LLMBridge(provider="gemini", model_id="planner-model")
        assert bridge.provider == "gemini"
        assert bridge.reflect_provider == "gemini"

    def test_explicit_same_provider_reuses_client(self):
        """When reflect_provider equals provider, the bridge reuses the
        main client (no duplicate connection)."""
        with patch("agent.llm_bridge.OpenAI"):
            bridge = LLMBridge(
                provider="gemini",
                model_id="planner-model",
                reflect_provider="gemini",
                reflect_model_id="reflector-model",
            )
        assert bridge.client is bridge.reflect_client
        assert bridge.provider == "gemini"
        assert bridge.reflect_provider == "gemini"

    def test_cross_provider_creates_distinct_clients(self):
        """When reflect_provider differs from provider, the bridge
        instantiates a second OpenAI client. The two are distinct
        objects (verified by `is not` identity check)."""
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            # Each call to OpenAI(...) returns a different mock instance
            instances = [MagicMock(name="main_client"), MagicMock(name="reflect_client")]
            MockOpenAI.side_effect = instances

            bridge = LLMBridge(
                provider="gemini",
                model_id="planner-model",
                reflect_provider="openai",
                reflect_model_id="reflector-model",
            )
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

            bridge = LLMBridge(
                provider="gemini",
                model_id="planner-model",
                reflect_provider="openai",
                reflect_model_id="reflector-model",
            )

            # generate() must hit the main client
            bridge.generate(SYSTEM_PROMPT, USER_PROMPT)
            assert main_client.chat.completions.create.call_count == 1
            assert reflect_client.chat.completions.create.call_count == 0

            # reflect() must hit the reflect client (NOT the main client)
            bridge.reflect(
                exp_id="exp_001",
                hypothesis="test hypothesis",
                actual_results={"denoising_score": 1.5},
                metric_spec=shipped_spec(),
            )
            assert main_client.chat.completions.create.call_count == 1  # unchanged
            assert reflect_client.chat.completions.create.call_count == 1  # incremented

            # And verify each client got the right model name
            assert main_client.chat.completions.create.call_args.kwargs["model"] == "planner-model"
            assert (
                reflect_client.chat.completions.create.call_args.kwargs["model"]
                == "reflector-model"
            )

    def test_reflect_provider_only_no_model_override(self):
        """reflect_provider can be set without reflect_model_id. In that
        case the reflector hits the second provider but with the main
        model name (which may or may not exist on that provider — the
        bridge does not validate)."""
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            MockOpenAI.side_effect = [MagicMock(), MagicMock()]
            bridge = LLMBridge(
                provider="gemini", model_id="shared-model-name", reflect_provider="openai"
            )
            assert bridge.reflect_model_name == "shared-model-name"
            assert bridge.client is not bridge.reflect_client

    def test_unknown_reflect_provider_raises(self):
        """An unknown reflect_provider should fail-fast at construction
        time with a clear error pointing at the known providers list."""
        with (
            patch("agent.llm_bridge.OpenAI"),
            pytest.raises(ValueError, match="Unknown reflect_provider"),
        ):
            LLMBridge(
                provider="gemini",
                model_id="planner-model",
                reflect_provider="nonexistent",
                reflect_model_id="reflector-model",
            )

    def test_reflect_provider_is_lowercased(self):
        """Like the main provider, reflect_provider should be normalized
        to lowercase for consistency."""
        with patch("agent.llm_bridge.OpenAI"):
            bridge = LLMBridge(
                provider="gemini",
                model_id="planner-model",
                reflect_provider="GEMINI",
                reflect_model_id="reflector-model",
            )
        assert bridge.reflect_provider == "gemini"
        # And same-after-lowercase should still reuse the client
        assert bridge.client is bridge.reflect_client


# ---------------------------------------------------------------------------
# _parse_retry_delay — extract retryDelay from Google 429 error body
# ---------------------------------------------------------------------------


class TestParseRetryDelay:
    def _make_exc(self, body: dict) -> MagicMock:
        exc = MagicMock()
        exc.body = body
        return exc

    def test_parses_seconds_string(self):
        exc = self._make_exc(
            {
                "error": {
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": "28890s",
                        }
                    ]
                }
            }
        )
        assert LLMBridge._parse_retry_delay(exc) == 28890.0

    def test_returns_none_when_no_retry_info(self):
        exc = self._make_exc(
            {"error": {"details": [{"@type": "type.googleapis.com/google.rpc.Help"}]}}
        )
        assert LLMBridge._parse_retry_delay(exc) is None

    def test_returns_none_when_details_missing(self):
        exc = self._make_exc({"error": {}})
        assert LLMBridge._parse_retry_delay(exc) is None

    def test_returns_none_when_body_not_dict(self):
        exc = MagicMock()
        exc.body = "not a dict"
        assert LLMBridge._parse_retry_delay(exc) is None

    def test_returns_none_when_delay_not_seconds_format(self):
        exc = self._make_exc(
            {
                "error": {
                    "details": [
                        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "1h30m"}
                    ]
                }
            }
        )
        assert LLMBridge._parse_retry_delay(exc) is None


# ---------------------------------------------------------------------------
# _call_with_retry — retry delay behavior
# ---------------------------------------------------------------------------


class TestCallWithRetryDelay:
    def _make_bridge(self):
        with patch("agent.llm_bridge.OpenAI"):
            return LLMBridge(provider="gemini", model_id="test-model")

    def _make_429(self, retry_delay_s: float | None = None):
        from openai import APIStatusError

        body = (
            {
                "error": {
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": f"{int(retry_delay_s)}s",
                        }
                    ]
                }
            }
            if retry_delay_s is not None
            else {"error": {}}
        )

        class Fake429(APIStatusError):
            status_code = 429

        response = MagicMock()
        response.status_code = 429
        exc = Fake429.__new__(Fake429)
        exc.status_code = 429
        exc.body = body
        exc.response = response
        exc.message = "quota exceeded"
        return exc

    def test_honors_retry_delay_on_429(self):
        """When API returns retryDelay=300s, bridge sleeps 300s (not the 60s cap)."""
        bridge = self._make_bridge()
        exc = self._make_429(retry_delay_s=300)
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise exc
            return _chat_response(VALID_JSON_STR)

        with patch("core.execution_deadline.time.sleep") as mock_sleep:
            bridge._call_with_retry(fn, label="test")
        mock_sleep.assert_called_once_with(300.0)

    def test_uses_exponential_backoff_without_retry_delay(self):
        """When 429 has no retryDelay, normal exponential backoff applies (starts at 2.5s)."""
        bridge = self._make_bridge()
        exc = self._make_429(retry_delay_s=None)
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise exc
            return _chat_response(VALID_JSON_STR)

        with patch("core.execution_deadline.time.sleep") as mock_sleep:
            bridge._call_with_retry(fn, label="test")
        mock_sleep.assert_called_once_with(2.5)


# ---------------------------------------------------------------------------
# Score-table substitution (docs/aggregated_score_table_awareness.md §9)
# ---------------------------------------------------------------------------

_TABLE_MARKER = "||SCORE-TABLE-MARKER-XYZ||"
_RENDERED_SENTINEL = (
    f"### Per-file performance (log-space)\n"
    f"| file | raw_baseline | ground_truth | model |\n"
    f"{_TABLE_MARKER}"
)


class TestScoreTablePromptStaticContent:
    """Verify the Phase 3 sub-commit C prompt rewrites land the expected
    tokens and section headers, and remove the old FILE VECTOR block."""

    def test_planner_prompt_contains_score_table_token(self):
        assert "{SCORE_COMPARISON_TABLE}" in PLANNER_PROMPT

    def test_reflector_prompt_contains_score_table_token(self):
        assert "{SCORE_COMPARISON_TABLE}" in REFLECTOR_PROMPT

    def test_planner_prompt_has_new_section_header(self):
        # Step 12 / PR-12a C7 — the header moved into the render authority as
        # the LEGACY substitution for a composition-gated token. What this
        # test asserts is what an un-composed run renders, which is unchanged.
        from tests.helpers.step12_pr12a_prompt_capture import legacy_rendered_template

        assert "### PER-FILE PERFORMANCE TABLE:" in legacy_rendered_template("planner")

    def test_reflector_prompt_has_new_section_header(self):
        from tests.helpers.step12_pr12a_prompt_capture import legacy_rendered_template

        assert "### PER-FILE COMPARISON" in legacy_rendered_template("reflector")

    def test_old_file_vector_section_removed_from_planner(self):
        """The §9.1 rewrite deletes the 'FILE VECTOR AND SCORING' block and
        the '~1.0 means no denoising' prose."""
        assert "FILE VECTOR AND SCORING" not in PLANNER_PROMPT
        assert "per-file score of ~1.0" not in PLANNER_PROMPT

    def test_planner_references_best_experiment_not_most_recent(self):
        """User-locked choice: the planner anchor is the best-so-far
        experiment, not the most recent. See the sub-commit C sign-off."""
        from tests.helpers.step12_pr12a_prompt_capture import legacy_rendered_template

        assert "best experiment" in legacy_rendered_template("planner")


class TestPlanScoreTableSubstitution:
    """LLMBridge.plan() substitutes the {SCORE_COMPARISON_TABLE} token in
    PLANNER_PROMPT with the caller-supplied rendered markdown, or a fallback
    when unset."""

    def _bridge_with_mocked_create(self, create_mock):
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create = create_mock
            return LLMBridge(provider="gemini", model_id="test-model")

    def test_plan_substitutes_score_table_md_into_system_prompt(self):
        create_mock = MagicMock(return_value=_chat_response(VALID_JSON_STR))
        bridge = self._bridge_with_mocked_create(create_mock)
        bridge.plan(
            planner_strategy="native-timing-v1",
            memory_history=[],
            expert_advice="none",
            score_table_md=_RENDERED_SENTINEL,
            task_render=TASK_RENDER,
            metric_spec=accuracy_like_spec(),
        )
        sent_system = create_mock.call_args.kwargs["messages"][0]["content"]
        assert _TABLE_MARKER in sent_system
        assert "{SCORE_COMPARISON_TABLE}" not in sent_system
        # Fallback must NOT appear when a real table is supplied
        assert _PLANNER_SCORE_TABLE_FALLBACK not in sent_system

    def test_plan_none_uses_planner_fallback(self):
        create_mock = MagicMock(return_value=_chat_response(VALID_JSON_STR))
        bridge = self._bridge_with_mocked_create(create_mock)
        bridge.plan(
            planner_strategy="native-timing-v1",
            memory_history=[],
            expert_advice="none",
            task_render=TASK_RENDER,
            metric_spec=accuracy_like_spec(),
        )  # no score_table_md
        sent_system = create_mock.call_args.kwargs["messages"][0]["content"]
        assert _PLANNER_SCORE_TABLE_FALLBACK in sent_system
        assert "{SCORE_COMPARISON_TABLE}" not in sent_system

    def test_plan_empty_string_treated_as_none(self):
        """An empty string is falsy — should fall back to the planner
        fallback text, consistent with None."""
        create_mock = MagicMock(return_value=_chat_response(VALID_JSON_STR))
        bridge = self._bridge_with_mocked_create(create_mock)
        bridge.plan(
            planner_strategy="native-timing-v1",
            memory_history=[],
            expert_advice="none",
            score_table_md="",
            task_render=TASK_RENDER,
            metric_spec=accuracy_like_spec(),
        )
        sent_system = create_mock.call_args.kwargs["messages"][0]["content"]
        assert _PLANNER_SCORE_TABLE_FALLBACK in sent_system


class TestReflectScoreTableSubstitution:
    """LLMBridge.reflect() reads score_comparison_table from reflection_context
    and substitutes into REFLECTOR_PROMPT; falls back when absent."""

    def _bridge_with_mocked_create(self, create_mock):
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create = create_mock
            return LLMBridge(provider="gemini", model_id="test-model")

    def test_reflect_substitutes_from_context(self):
        create_mock = MagicMock(return_value=_chat_response(VALID_JSON_STR))
        bridge = self._bridge_with_mocked_create(create_mock)
        bridge.reflect(
            exp_id="exp_001",
            hypothesis="hypo",
            actual_results={"denoising_score": 1.5},
            reflection_context={"score_comparison_table": _RENDERED_SENTINEL},
            metric_spec=shipped_spec(),
        )
        sent_system = create_mock.call_args.kwargs["messages"][0]["content"]
        assert _TABLE_MARKER in sent_system
        assert "{SCORE_COMPARISON_TABLE}" not in sent_system
        assert _REFLECTOR_SCORE_TABLE_FALLBACK not in sent_system

    def test_reflect_none_context_uses_reflector_fallback(self):
        create_mock = MagicMock(return_value=_chat_response(VALID_JSON_STR))
        bridge = self._bridge_with_mocked_create(create_mock)
        bridge.reflect(
            exp_id="exp_001",
            hypothesis="hypo",
            actual_results={"denoising_score": 1.5},
            reflection_context=None,
            metric_spec=shipped_spec(),
        )
        sent_system = create_mock.call_args.kwargs["messages"][0]["content"]
        assert _REFLECTOR_SCORE_TABLE_FALLBACK in sent_system
        assert "{SCORE_COMPARISON_TABLE}" not in sent_system

    def test_reflect_context_without_key_uses_reflector_fallback(self):
        create_mock = MagicMock(return_value=_chat_response(VALID_JSON_STR))
        bridge = self._bridge_with_mocked_create(create_mock)
        bridge.reflect(
            exp_id="exp_001",
            hypothesis="hypo",
            actual_results={"denoising_score": 1.5},
            reflection_context={"baseline_score": 0.5},  # no score_comparison_table
            metric_spec=shipped_spec(),
        )
        sent_system = create_mock.call_args.kwargs["messages"][0]["content"]
        assert _REFLECTOR_SCORE_TABLE_FALLBACK in sent_system

    def test_reflect_context_with_null_key_uses_reflector_fallback(self):
        """sub-commit B wires None into the context on failed rounds — the
        bridge must treat explicit None as 'no table', not as a literal."""
        create_mock = MagicMock(return_value=_chat_response(VALID_JSON_STR))
        bridge = self._bridge_with_mocked_create(create_mock)
        bridge.reflect(
            exp_id="exp_001",
            hypothesis="hypo",
            actual_results={"denoising_score": 1.5},
            reflection_context={"score_comparison_table": None},
            metric_spec=shipped_spec(),
        )
        sent_system = create_mock.call_args.kwargs["messages"][0]["content"]
        assert _REFLECTOR_SCORE_TABLE_FALLBACK in sent_system
