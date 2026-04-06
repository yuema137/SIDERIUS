# agent/llm_bridge.py
#
# Unified LLM transport layer for SIDERIUS.
#
# This module provides two layers of functionality:
#
# 1. GENERIC TRANSPORT (provider-agnostic, used by all nodes):
#    - generate(system_prompt, user_prompt) -> dict   (JSON mode)
#    - generate_text(system_prompt, user_prompt) -> str (plain text)
#    - tool_call(system_prompt, user_prompt, tools) -> ToolCallResult
#    - list_models() -> list of model IDs
#    All providers (OpenAI, Gemini, any OpenAI-compatible endpoint) are
#    accessed through a single openai.OpenAI client routed via base_url.
#    Nodes call these methods directly with their own prompts.
#
# 2. DOMAIN-SPECIFIC WRAPPERS (only used by the tuning agent):
#    - plan()    -> assembles a prompt from memory_history + expert_advice +
#                   config_manual using generators from agent.prompts, then
#                   calls generate().
#    - reflect() -> assembles a prompt from experiment results using generators
#                   from agent.prompts, then calls generate().
#    These are specific to ml_hyperparameter_tune_agent. The other 4 nodes
#    (interpretation, proposal, implementor, validator) bypass plan()/reflect()
#    entirely and call generate()/generate_text() with their own prompts.
#
# NOTE: plan() and reflect() are candidates for moving into the tuning agent
# itself, which would make LLMBridge a pure transport layer. See Open Question
# 1 in docs/refactor_llm_bridge.md.

import os
import json
from dataclasses import dataclass
from typing import Any, List, Dict, Optional
from openai import OpenAI
from dotenv import load_dotenv

from agent.prompts import (
    PLANNER_PROMPT,
    REFLECTOR_PROMPT,
    get_planner_user_prompt,
    get_reflector_user_prompt
)


# ---------------------------------------------------------------------------
# Tool-call result — flattens the OpenAI SDK's nested response structure
# so callers remain SDK-agnostic.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ToolCallResult:
    """
    Structured result from an LLM tool-call request.

    Attributes:
        name:      The tool (skill) name the LLM chose to invoke.
        arguments: Parsed dict of the arguments the LLM provided.
                   Ready to pass to ``input_schema.model_validate(arguments)``.
        call_id:   The tool_call ID from the API (needed if you want to send
                   a tool-result message back in a multi-turn conversation).
    """

    name: str
    arguments: Dict[str, Any]
    call_id: str

# ---------------------------------------------------------------------------
# Known providers — convenience defaults, not a restriction.
# Any OpenAI-compatible endpoint can be used via base_url/api_key overrides.
# ---------------------------------------------------------------------------
_KNOWN_PROVIDERS: Dict[str, Dict[str, Optional[str]]] = {
    "openai": {
        "base_url": None,           # SDK default
        "api_key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4o",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key_env": "GEMINI_API_KEY",
        "default_model": "gemini-3.1-flash-lite-preview",
    },
    # Claude via Bedrock/Vertex requires non-standard auth (AWS SigV4 / Google
    # OAuth).  Placeholder entry — wire up when a compatible endpoint is available.
    # "claude": {
    #     "base_url": "https://...",
    #     "api_key_env": "ANTHROPIC_API_KEY",
    #     "default_model": "claude-sonnet-4-20250514",
    # },
}


class LLMBridge:
    def __init__(
        self,
        provider: str = "gemini",
        model_id: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        """
        Unified LLM bridge — every provider is accessed through ``openai.OpenAI``.

        For known providers (``"openai"``, ``"gemini"``), ``base_url`` and
        ``api_key`` are resolved automatically from environment variables.
        Any OpenAI-compatible endpoint can be used by passing ``base_url``
        and ``api_key`` explicitly.

        Args:
            provider: Provider label (used for logging / identification).
            model_id: Model identifier (e.g. ``"gpt-4o"``, ``"gemini-3-flash"``).
                      Falls back to the provider's default when ``None``.
            base_url: Override the API base URL.  Required for providers not in
                      the known-providers map.
            api_key:  Override the API key.  When ``None``, looked up from the
                      environment variable associated with the provider.
        """
        load_dotenv()
        self.provider = provider.lower()

        known = _KNOWN_PROVIDERS.get(self.provider)

        # Resolve api_key: explicit arg > env var > None
        if api_key is None and known:
            api_key = os.getenv(known["api_key_env"])
        self.api_key = api_key

        # Resolve base_url: explicit arg > known default > None (SDK default)
        if base_url is None and known:
            base_url = known["base_url"]

        # Resolve model: explicit arg > known default (unknown providers must supply model_id)
        if model_id is None and known:
            model_id = known["default_model"]
        self.model_name = model_id

        self.client = OpenAI(
            api_key=self.api_key,
            max_retries=5,
            timeout=120.0,
            **({"base_url": base_url} if base_url else {}),
        )

    def list_models(self) -> List[str]:
        """
        List model IDs available from the current provider.

        Calls the ``GET /models`` endpoint exposed by OpenAI-compatible APIs.
        Returns a sorted list of model ID strings.
        """
        response = self.client.models.list()
        return sorted(m.id for m in response)

    def plan(self,
             memory_history: List[Dict],
             expert_advice: str = "None",
             force_model: str = "auto",
             config_manual: Optional[Dict] = None,
             current_round: Optional[int] = None,
             max_rounds: Optional[int] = None,
             trial_allowed: bool = True) -> Dict:
        """
        Uses the Planner logic to observe Research Memory and decide next steps.
        Incorporates physical constraints from config_manual to prevent hallucinations.

        Args:
            current_round: Current round number (1-based). Forwarded to prompt.
            max_rounds:    Total rounds in this run. Forwarded to prompt.
            trial_allowed: Whether the LLM may choose trial mode. Forwarded to prompt.
        """
        system_prompt = PLANNER_PROMPT

        # --- 2. Inject config manual ---
        manual_context = ""
        if config_manual:
            manual_context = f"\n\n[STRICT PHYSICAL CONSTRAINTS / CONFIG MANUAL]:\n{json.dumps(config_manual, indent=2)}"

        # Pass the new arguments to the prompt generator
        user_prompt = get_planner_user_prompt(
            memory_history=memory_history,
            expert_advice=expert_advice,
            force_model=force_model,
            current_round=current_round,
            max_rounds=max_rounds,
            trial_allowed=trial_allowed,
        )

        # pass the manual into prompt
        final_user_prompt = user_prompt + manual_context

        return self.generate(system_prompt, final_user_prompt)

    def reflect(self, exp_id: str, hypothesis: str, actual_results: Dict,
                reflection_context: Optional[Dict] = None) -> Dict:
        """
        Uses the Reflector logic to transform results into new Memory entries.
        reflection_context provides baseline/best score comparisons so the
        reflector can judge results correctly.
        """
        system_prompt = REFLECTOR_PROMPT
        user_prompt = get_reflector_user_prompt(exp_id, hypothesis, actual_results, reflection_context)

        return self.generate(system_prompt, user_prompt)

    def generate(self, system_prompt: str, user_prompt: str) -> Dict:
        """
        Call the LLM with a system prompt and user prompt, return a JSON dict.

        Uses ``response_format={"type": "json_object"}`` via the unified
        OpenAI-compatible ``chat.completions.create`` endpoint for all providers.
        """
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
        text = response.choices[0].message.content.strip()

        # Some models wrap JSON in markdown fences despite json_object mode
        if text.startswith("```json"):
            text = text[7:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            print(f"[LLMBridge.generate] Failed to parse JSON from {self.provider}/{self.model_name}: {text[:200]}")
            return {}

    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        """
        Call the LLM with a system prompt and user prompt, return plain text.

        Used for free-form reasoning steps where JSON mode would constrain
        output quality.
        """
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content.strip()

    def tool_call(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: List[Dict[str, Any]],
    ) -> ToolCallResult:
        """
        Ask the LLM to select a tool and provide arguments.

        Uses the OpenAI ``tools`` parameter so the model is structurally
        constrained to emit a valid tool call — no free-form JSON parsing.

        Args:
            system_prompt: System-level instruction for the LLM.
            user_prompt:   The user message describing the goal or context.
            tools:         List of OpenAI-format tool definitions.  Typically
                           built via ``SkillSpec.to_openai_tool()``.

        Returns:
            A ``ToolCallResult`` with the chosen tool name, parsed arguments
            dict, and the API's call ID.

        Raises:
            ValueError: If the model response does not contain a tool call
                        (e.g. the model replied with plain text instead).
        """
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            tools=tools,
            tool_choice="auto",
        )

        message = response.choices[0].message

        if not message.tool_calls:
            raise ValueError(
                f"[LLMBridge.tool_call] Model did not return a tool call. "
                f"Response: {message.content!r}"
            )

        tc = message.tool_calls[0]
        return ToolCallResult(
            name=tc.function.name,
            arguments=json.loads(tc.function.arguments),
            call_id=tc.id,
        )
