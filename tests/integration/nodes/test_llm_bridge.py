"""
Real-API integration tests for agent/llm_bridge.py

Requires:
  - GEMINI_API_KEY and/or OPENAI_API_KEY set in the environment (or .env file)

Run with:
  uv run pytest -m real_run tests/integration/agent/test_llm_bridge_real.py -v

DO NOT run in CI.
"""

import os

import pytest
from dotenv import load_dotenv

from agent.llm_bridge import LLMBridge

load_dotenv()

pytestmark = pytest.mark.real_run

SYSTEM_PROMPT = "You are a helpful assistant. Follow instructions exactly."

# ---------------------------------------------------------------------------
# Skip guards
# ---------------------------------------------------------------------------


def _skip_if_no_key(provider: str):
    key = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
    if not os.getenv(key):
        pytest.skip(f"{key} not set — skipping real API test")


# ---------------------------------------------------------------------------
# generate() — structured JSON output
# ---------------------------------------------------------------------------


class TestGenerateRealAPI:
    def test_gemini_returns_non_empty_dict(self):
        _skip_if_no_key("gemini")
        bridge = LLMBridge(provider="gemini", model_id="gemini-3.1-flash-lite-preview")
        result = bridge.generate(
            system_prompt=SYSTEM_PROMPT,
            user_prompt='Return a JSON object with a single key "answer" whose value is the string "42".',
        )
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert len(result) > 0, "Response dict is empty"

    def test_openai_returns_non_empty_dict(self):
        _skip_if_no_key("openai")
        bridge = LLMBridge(provider="openai", model_id="gpt-4o")
        result = bridge.generate(
            system_prompt=SYSTEM_PROMPT,
            user_prompt='Return a JSON object with a single key "answer" whose value is the string "42".',
        )
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert len(result) > 0, "Response dict is empty"


# ---------------------------------------------------------------------------
# generate_text() — plain-text output
# ---------------------------------------------------------------------------


class TestGenerateTextRealAPI:
    def test_gemini_returns_non_empty_str(self):
        _skip_if_no_key("gemini")
        bridge = LLMBridge(provider="gemini", model_id="gemini-3.1-flash-lite-preview")
        result = bridge.generate_text(
            system_prompt=SYSTEM_PROMPT,
            user_prompt="In one sentence, explain why the sky is blue.",
        )
        assert isinstance(result, str), f"Expected str, got {type(result)}"
        assert len(result) > 10, "Response is suspiciously short"

    def test_openai_returns_non_empty_str(self):
        _skip_if_no_key("openai")
        bridge = LLMBridge(provider="openai", model_id="gpt-4o")
        result = bridge.generate_text(
            system_prompt=SYSTEM_PROMPT,
            user_prompt="In one sentence, explain why the sky is blue.",
        )
        assert isinstance(result, str), f"Expected str, got {type(result)}"
        assert len(result) > 10, "Response is suspiciously short"
