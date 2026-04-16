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
import time
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
    """
    Universal API gateway for all LLM calls in SIDERIUS.

    **Architectural invariant**: this class is the ONLY place in the
    `agent/`, `nodes/`, and `workflows/` codebase that constructs an
    `OpenAI()` client. Every agent must route its LLM calls through an
    `LLMBridge` instance. This is enforced by
    ``tests/unit/agent/test_llm_bridge_singleton.py``, which fails if
    any other file under those directories instantiates ``OpenAI()``
    directly.

    Why this matters: the retry policy, timeouts, provider routing,
    planner/reflector model split, and any future cross-cutting
    concerns (rate limiting, observability, fallbacks) all live in
    one place. Bypassing the bridge silently opts an agent out of
    every one of those guarantees — and the bug usually only surfaces
    in production under load.

    If you genuinely need a one-off client (e.g. a test or a
    diagnostic script), put it under ``tests/`` or ``scripts/``,
    where the singleton check does not run.
    """

    def __init__(
        self,
        provider: str = "gemini",
        model_id: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        reflect_provider: Optional[str] = None,
        reflect_model_id: Optional[str] = None,
        max_retries: Optional[int] = None,
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
            reflect_provider:
                      Optional separate provider for the reflector method
                      (``reflect()``). When set, the bridge instantiates a
                      second OpenAI client pointed at this provider's
                      base_url and uses its API key. When unset (default),
                      ``reflect()`` uses the same provider/client as
                      ``generate()``. Designed to let the reflector use a
                      different vendor entirely (e.g. main planner on
                      gemini, reflector on openai).
            reflect_model_id:
                      Optional separate model ID for the reflector method
                      (``reflect()``). When set, ``reflect()`` uses this model
                      while ``plan()`` and other methods continue to use
                      ``model_id``. Designed to let cheaper/faster models
                      handle the templated reflection step while keeping the
                      main reasoning model for planning. When unset (default),
                      both planner and reflector use ``model_id``.

                      ``reflect_provider`` and ``reflect_model_id`` are
                      independent — you can set either or both, or neither.
                      Common patterns:
                        - Both unset: planner and reflector use the same
                          provider+model (legacy behavior).
                        - Only ``reflect_model_id`` set: same provider, two
                          different models (e.g. gemini-3.1-pro for planner,
                          gemini-2.5-flash for reflector).
                        - Both set: cross-provider routing (e.g. gemini for
                          planner, openai for reflector).
            max_retries:
                      Maximum number of retry attempts for transient API
                      errors (429, 5xx, connection, timeout). ``None``
                      (default) means retry indefinitely — the process
                      owner (Slurm wall time, Ctrl-C) is the natural
                      timeout. Set to a positive integer for interactive
                      use where infinite retry would be annoying (e.g. 6
                      for the legacy ~77s window, 20 for ~15 minutes).
                      Backoff doubles from 2.5s up to a 60s cap.
        """
        load_dotenv()
        self.provider = provider.lower()
        self.max_retries = max_retries

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
        # Reflect model defaults to the main model when unset, so existing
        # callers see no behavior change.
        self.reflect_model_name = reflect_model_id or self.model_name

        # Retry policy: SDK retries are disabled (max_retries=0) and
        # replaced with our own loop in _chat_json that uses a longer
        # backoff schedule (2.5s, 5s, 10s, 20s, 40s — total ~77s).
        # The default SDK schedule (capped at ~8s, ~25s total) gave up
        # too fast on the E9 SDSC iter 47950268 503 (Google "high
        # demand" / per-key QPM saturation under parallel runs).
        self.client = OpenAI(
            api_key=self.api_key,
            max_retries=0,
            timeout=120.0,
            **({"base_url": base_url} if base_url else {}),
        )

        # --- Reflect client setup (Phase A.2: cross-provider support) ---
        # When reflect_provider is None or matches the main provider, the
        # reflect client is the same object as the main client (no duplicate
        # connections, no extra resource cost). When it differs, we
        # instantiate a second OpenAI client with the reflect provider's
        # credentials.
        normalized_reflect_provider = (
            reflect_provider.lower() if reflect_provider else self.provider
        )
        self.reflect_provider = normalized_reflect_provider

        if normalized_reflect_provider == self.provider:
            # Same provider — reuse the main client. Saves a connection
            # and ensures both calls hit the same authenticated endpoint.
            self.reflect_client = self.client
        else:
            # Different provider — resolve its credentials from
            # _KNOWN_PROVIDERS and instantiate a second OpenAI client.
            reflect_known = _KNOWN_PROVIDERS.get(normalized_reflect_provider)
            if reflect_known is None:
                raise ValueError(
                    f"Unknown reflect_provider {normalized_reflect_provider!r}. "
                    f"Known providers: {list(_KNOWN_PROVIDERS.keys())}. "
                    f"For ad-hoc providers, instantiate the second client "
                    f"manually and assign it to LLMBridge.reflect_client "
                    f"after construction."
                )
            reflect_api_key = os.getenv(reflect_known["api_key_env"])
            reflect_base_url = reflect_known["base_url"]
            self.reflect_client = OpenAI(
                api_key=reflect_api_key,
                max_retries=0,
                timeout=120.0,
                base_url=reflect_base_url,
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
             model_description: Optional[str] = None,
             exploration_checklist: str = "",
             current_round: Optional[int] = None,
             max_rounds: Optional[int] = None,
             trial_allowed: bool = True) -> Dict:
        """
        Uses the Planner logic to observe Research Memory and decide next steps.
        Incorporates physical constraints from config_manual and architecture
        knowledge from model_description to prevent hallucinations.

        Args:
            config_manual:    JSON schema of the model's config fields.
            model_description: Markdown description of the architecture and its physics.
            current_round:    Current round number (1-based). Forwarded to prompt.
            max_rounds:       Total rounds in this run. Forwarded to prompt.
            trial_allowed:    Whether the LLM may choose trial mode. Forwarded to prompt.
        """
        system_prompt = PLANNER_PROMPT

        # --- 2. Inject model description + config manual ---
        manual_context = ""
        if model_description:
            manual_context += f"\n\n[MODEL ARCHITECTURE DESCRIPTION]:\n{model_description}"
        if config_manual:
            manual_context += f"\n\n[STRICT PHYSICAL CONSTRAINTS / CONFIG MANUAL]:\n{json.dumps(config_manual, indent=2)}"

        # Pass the new arguments to the prompt generator
        user_prompt = get_planner_user_prompt(
            memory_history=memory_history,
            expert_advice=expert_advice,
            force_model=force_model,
            current_round=current_round,
            max_rounds=max_rounds,
            trial_allowed=trial_allowed,
        )

        # Assemble final prompt: user prompt + checklist + description + manual
        final_user_prompt = user_prompt
        if exploration_checklist:
            final_user_prompt += f"\n\n{exploration_checklist}"
        final_user_prompt += manual_context

        return self.generate(system_prompt, final_user_prompt)

    def reflect(self, exp_id: str, hypothesis: str, actual_results: Dict,
                reflection_context: Optional[Dict] = None) -> Dict:
        """
        Uses the Reflector logic to transform results into new Memory entries.
        reflection_context provides baseline/best score comparisons so the
        reflector can judge results correctly.

        Routes through ``self.reflect_client`` and ``self.reflect_model_name``,
        both of which default to the main client/model when ``reflect_provider``
        and ``reflect_model_id`` were not passed to ``__init__``. When set
        independently, the reflector can use a different provider AND/OR a
        different model than the planner — it is a templated structured-
        extraction task, not a reasoning task, and does not need a frontier
        model.
        """
        system_prompt = REFLECTOR_PROMPT
        user_prompt = get_reflector_user_prompt(exp_id, hypothesis, actual_results, reflection_context)

        return self._chat_json(self.reflect_client, self.reflect_model_name,
                               system_prompt, user_prompt)

    # Retry policy for ALL OpenAI API calls. SDK-level retry is disabled
    # (max_retries=0 in the client constructors), so this helper is the
    # single source of truth for how we handle transient API failures.
    #
    # Backoff: doubles from 2.5s up to a 60s cap, then stays at 60s.
    # Schedule: 2.5, 5, 10, 20, 40, 60, 60, 60, ...
    #
    # When max_retries is None (default): retry indefinitely — the process
    # owner (Slurm wall time, Ctrl-C) is the natural timeout. This is the
    # right default for batch jobs where burning a round on a transient 503
    # is far more expensive than waiting a few extra minutes.
    #
    # When max_retries is an integer: stop after that many total attempts
    # (e.g. max_retries=6 gives 1 initial + 5 retries, similar to the old
    # fixed schedule). Use this for interactive/lilab sessions.
    #
    # Catches 429 (rate limit), 5xx (server errors incl. Google 503 "high
    # demand"), and connection / timeout errors. Other 4xx errors (auth,
    # bad request, model not found) are raised immediately — they will
    # not heal on retry.
    _RETRY_INITIAL_WAIT = 2.5
    _RETRY_MAX_WAIT = 60.0

    @staticmethod
    def _parse_retry_delay(exc) -> Optional[float]:
        """Extract retryDelay seconds from a Google API 429 error body, if present.

        Google embeds a RetryInfo detail with a delay string like "28890s".
        Returns None if the field is absent or unparseable.
        """
        try:
            details = exc.body.get("error", {}).get("details", [])
            for d in details:
                if d.get("@type", "").endswith("RetryInfo"):
                    delay_str = d.get("retryDelay", "")
                    if delay_str.endswith("s"):
                        return float(delay_str[:-1])
        except Exception:
            pass
        return None

    def _call_with_retry(self, fn, label: str = "api_call"):
        """Call an OpenAI API function with the bridge's retry policy."""
        from openai import APIStatusError, APIConnectionError, APITimeoutError
        last_exc = None
        attempt = 0
        wait = self._RETRY_INITIAL_WAIT
        while True:
            try:
                return fn()
            except (APIConnectionError, APITimeoutError) as e:
                last_exc = e
            except APIStatusError as e:
                if e.status_code != 429 and not (500 <= e.status_code < 600):
                    raise
                last_exc = e
                # Honor the API-suggested retry delay for hard quota errors
                # (e.g. daily RPD reset). Overrides the exponential backoff
                # for this attempt only; next attempt resumes normal schedule.
                if e.status_code == 429:
                    suggested = self._parse_retry_delay(e)
                    if suggested is not None:
                        wait = suggested
            attempt += 1
            # Check if we've exhausted our retry budget
            if self.max_retries is not None and attempt >= self.max_retries:
                print(f"[LLMBridge.{label}] All {attempt} "
                      f"attempts failed; raising.", flush=True)
                raise last_exc
            print(f"[LLMBridge.{label}] Attempt {attempt} failed "
                  f"({type(last_exc).__name__}: {last_exc}); "
                  f"retrying in {wait}s...", flush=True)
            time.sleep(wait)
            wait = min(wait * 2, self._RETRY_MAX_WAIT)

    @staticmethod
    def _sanitize_json_text(text: str) -> str:
        """Best-effort cleanup of LLM-generated JSON text before parsing.

        Handles common LLM output quirks in a model-agnostic way:

        1. Markdown fence stripping — some models wrap the JSON in ```json...```
           despite being asked for raw JSON.
        2. Invalid escape sequences — JSON only permits \\", \\\\, \\/, \\b, \\f,
           \\n, \\r, \\t, \\uXXXX after a backslash. Any other \\X is illegal.
           LLMs sometimes escape characters that don't need escaping (e.g. \\`
           for backtick, \\' for apostrophe, \\( in math notation).

           We fix this iteratively using the JSON parser's own error position:
           each JSONDecodeError with "escape" in its message reports the exact
           character position of the offending \\X. We drop the backslash at
           pos-1 and keep the character at pos, then re-parse. Repeat until the
           JSON is valid or a non-escape error is encountered.

           This approach is model-agnostic — it doesn't assume which character
           follows the backslash, and handles multiple bad escapes in one pass.
        """
        import json as _json

        # 1. Strip markdown fences
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        # 2. Fix invalid escape sequences using parser error-position feedback.
        # The JSON parser reports the backslash position inconsistently across
        # versions (sometimes e.pos is the backslash, sometimes the char after it).
        # We probe both positions bidirectionally, so this works regardless.
        _MAX_FIXES = 100  # guard against pathological input
        for _ in range(_MAX_FIXES):
            try:
                _json.loads(text)
                break  # valid JSON — stop
            except _json.JSONDecodeError as e:
                if "escape" not in e.msg.lower():
                    break  # different error class; let caller handle it
                pos = e.pos
                # Probe both pos-1 and pos for the offending backslash.
                if pos > 0 and text[pos - 1] == "\\":
                    idx = pos - 1  # backslash is before the reported position
                elif pos < len(text) and text[pos] == "\\":
                    idx = pos      # backslash is at the reported position
                else:
                    break  # no backslash found near the error site; give up
                text = text[:idx] + text[idx + 1:]  # drop the backslash

        return text

    def _chat_json(self, client: OpenAI, model_name: str,
                   system_prompt: str, user_prompt: str) -> Dict:
        """
        Internal helper: send a system+user prompt through a specific client
        to a specific model, and return the parsed JSON response.

        Used by ``generate()`` (which always uses ``self.client`` and
        ``self.model_name``) and by ``reflect()`` (which uses
        ``self.reflect_client`` and ``self.reflect_model_name`` so callers
        can route the reflector to a cheaper/faster/different-quota model on
        the same OR a different provider than the main planner).

        The client and model are passed as explicit arguments so the helper
        is fully decoupled from any per-method state — easy to mock and easy
        to extend with future per-method routing.
        """
        response = self._call_with_retry(
            lambda: client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
            ),
            label="_chat_json",
        )
        text = response.choices[0].message.content.strip()
        text = self._sanitize_json_text(text)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            print(f"[LLMBridge._chat_json] Failed to parse JSON from model={model_name}: {text[:200]}", flush=True)
            raise ValueError(
                f"Model response was not valid JSON. Return ONLY a raw JSON object. "
                f"Your response started with: {text[:200]}"
            )

    def generate(self, system_prompt: str, user_prompt: str) -> Dict:
        """
        Call the main LLM (``self.client`` + ``self.model_name``) with a
        system prompt and a user prompt, return a JSON dict.

        Uses ``response_format={"type": "json_object"}`` via the unified
        OpenAI-compatible ``chat.completions.create`` endpoint for all providers.
        """
        return self._chat_json(self.client, self.model_name,
                               system_prompt, user_prompt)

    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        """
        Call the LLM with a system prompt and user prompt, return plain text.

        Used for free-form reasoning steps where JSON mode would constrain
        output quality.
        """
        response = self._call_with_retry(
            lambda: self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            ),
            label="generate_text",
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
        response = self._call_with_retry(
            lambda: self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                tools=tools,
                tool_choice="auto",
            ),
            label="tool_call",
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
