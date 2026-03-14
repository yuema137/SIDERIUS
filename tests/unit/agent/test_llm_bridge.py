"""
Unit tests for agent/llm_bridge.py

Mocks provider SDKs (google.genai, openai) to verify:
  - generate()      returns a Dict (JSON mode)
  - generate_text() returns a str  (plain-text mode)
  - Both methods work for both providers
  - generate() handles malformed JSON from Gemini gracefully
  - Unsupported provider raises ValueError at construction
"""
import json
import pytest
from unittest.mock import MagicMock, patch

from agent.llm_bridge import LLMBridge


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = "You are a helpful assistant."
USER_PROMPT   = "Describe the sky."

VALID_JSON_STR  = '{"color": "blue", "clouds": true}'
VALID_JSON_DICT = {"color": "blue", "clouds": True}
PLAIN_TEXT      = "The sky is blue with scattered clouds."


def _gemini_response(text: str) -> MagicMock:
    response = MagicMock()
    response.text = text
    return response


def _openai_response(content: str) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    return response


# ---------------------------------------------------------------------------
# Gemini — generate()
# ---------------------------------------------------------------------------

class TestGeminiGenerate:

    def test_returns_dict(self):
        with patch("agent.llm_bridge.genai.Client") as MockClient:
            MockClient.return_value.models.generate_content.return_value = _gemini_response(VALID_JSON_STR)
            bridge = LLMBridge(provider="gemini", model_id="test-model")
            result = bridge.generate(SYSTEM_PROMPT, USER_PROMPT)
        assert result == VALID_JSON_DICT

    def test_json_mode_requested(self):
        with patch("agent.llm_bridge.genai.Client") as MockClient:
            mock_generate = MockClient.return_value.models.generate_content
            mock_generate.return_value = _gemini_response(VALID_JSON_STR)
            bridge = LLMBridge(provider="gemini", model_id="test-model")
            bridge.generate(SYSTEM_PROMPT, USER_PROMPT)
            call_kwargs = mock_generate.call_args.kwargs
            config = call_kwargs.get("config")
            assert config is not None
            assert config.response_mime_type == "application/json"

    def test_malformed_json_returns_empty_dict(self):
        with patch("agent.llm_bridge.genai.Client") as MockClient:
            MockClient.return_value.models.generate_content.return_value = _gemini_response("not valid json {{")
            bridge = LLMBridge(provider="gemini", model_id="test-model")
            result = bridge.generate(SYSTEM_PROMPT, USER_PROMPT)
        assert result == {}

    def test_markdown_fenced_json_is_parsed(self):
        fenced = "```json\n" + VALID_JSON_STR + "\n```"
        with patch("agent.llm_bridge.genai.Client") as MockClient:
            MockClient.return_value.models.generate_content.return_value = _gemini_response(fenced)
            bridge = LLMBridge(provider="gemini", model_id="test-model")
            result = bridge.generate(SYSTEM_PROMPT, USER_PROMPT)
        assert result == VALID_JSON_DICT


# ---------------------------------------------------------------------------
# Gemini — generate_text()
# ---------------------------------------------------------------------------

class TestGeminiGenerateText:

    def test_returns_str(self):
        with patch("agent.llm_bridge.genai.Client") as MockClient:
            MockClient.return_value.models.generate_content.return_value = _gemini_response(PLAIN_TEXT)
            bridge = LLMBridge(provider="gemini", model_id="test-model")
            result = bridge.generate_text(SYSTEM_PROMPT, USER_PROMPT)
        assert isinstance(result, str)
        assert result == PLAIN_TEXT

    def test_no_json_mode_requested(self):
        with patch("agent.llm_bridge.genai.Client") as MockClient:
            mock_generate = MockClient.return_value.models.generate_content
            mock_generate.return_value = _gemini_response(PLAIN_TEXT)
            bridge = LLMBridge(provider="gemini", model_id="test-model")
            bridge.generate_text(SYSTEM_PROMPT, USER_PROMPT)
            call_kwargs = mock_generate.call_args.kwargs
            config = call_kwargs.get("config")
            # generate_text should not request JSON mime type
            assert config is None or getattr(config, "response_mime_type", None) is None


# ---------------------------------------------------------------------------
# OpenAI — generate()
# ---------------------------------------------------------------------------

class TestOpenAIGenerate:

    def test_returns_dict(self):
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value = _openai_response(VALID_JSON_STR)
            bridge = LLMBridge(provider="openai", model_id="gpt-4o")
            result = bridge.generate(SYSTEM_PROMPT, USER_PROMPT)
        assert result == VALID_JSON_DICT

    def test_json_mode_requested(self):
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            mock_create = MockOpenAI.return_value.chat.completions.create
            mock_create.return_value = _openai_response(VALID_JSON_STR)
            bridge = LLMBridge(provider="openai", model_id="gpt-4o")
            bridge.generate(SYSTEM_PROMPT, USER_PROMPT)
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs.get("response_format") == {"type": "json_object"}


# ---------------------------------------------------------------------------
# OpenAI — generate_text()
# ---------------------------------------------------------------------------

class TestOpenAIGenerateText:

    def test_returns_str(self):
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            MockOpenAI.return_value.chat.completions.create.return_value = _openai_response(PLAIN_TEXT)
            bridge = LLMBridge(provider="openai", model_id="gpt-4o")
            result = bridge.generate_text(SYSTEM_PROMPT, USER_PROMPT)
        assert isinstance(result, str)
        assert result == PLAIN_TEXT

    def test_no_json_mode_requested(self):
        with patch("agent.llm_bridge.OpenAI") as MockOpenAI:
            mock_create = MockOpenAI.return_value.chat.completions.create
            mock_create.return_value = _openai_response(PLAIN_TEXT)
            bridge = LLMBridge(provider="openai", model_id="gpt-4o")
            bridge.generate_text(SYSTEM_PROMPT, USER_PROMPT)
            call_kwargs = mock_create.call_args.kwargs
            assert "response_format" not in call_kwargs


# ---------------------------------------------------------------------------
# Provider validation
# ---------------------------------------------------------------------------

class TestProviderValidation:

    def test_unsupported_provider_raises(self):
        with pytest.raises(ValueError, match="Unsupported provider"):
            LLMBridge(provider="anthropic")
