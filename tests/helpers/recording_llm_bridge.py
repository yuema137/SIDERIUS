"""``RecordingLLMBridge`` — drop-in test double for ``agent.llm_bridge.LLMBridge``.

Returns predefined responses (one per call) and records every call so tests
can assert on the prompts the agent would have sent. Used by pseudo-mode
integration tests; never used in production.

Design principles (see ``docs/pseudo_test_infra.md`` §4B for the full story):
  * Drop-in: ``__init__`` accepts ``**kwargs`` so the agent can construct it
    via the same factory call it uses for the real ``LLMBridge``, with no
    test-side translation. Real-bridge constructor params (provider, model_id,
    reflect_provider, reflect_model_id, ...) are silently ignored.
  * Predefined responses are plain post-parse dicts (or strings, for the
    plain-text ``generate_text`` path). The recording bridge does not parse,
    transform, or synthesize anything — schema fidelity is the test author's
    responsibility, maintained as a project invariant.
  * Per-method FIFO queue: register one or more responses per method; each
    call pops the next. Queue exhaustion raises a loud ``RuntimeError`` so a
    test that forgot to register a response fails fast at the call site.
  * Public ``calls`` list for direct test inspection. No helper methods, no
    convenience assertion DSL — tests assert on ``bridge.calls[i]`` directly.
"""

from __future__ import annotations

from typing import Any, Optional

from tests.helpers._pseudo_data import load_pseudo_data


class RecordingLLMBridge:
    """Test double for :class:`agent.llm_bridge.LLMBridge`.

    Attributes:
        calls: List of recorded calls. Each entry is a tuple
            ``(method_name, *args)`` capturing what the agent invoked. Tests
            inspect this list directly to assert on prompt content, call
            count, and call order. The contents of each tuple match the
            corresponding method's signature.
    """

    def __init__(
        self,
        responses: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        # **kwargs accepts (and silently ignores) the real LLMBridge constructor
        # parameters: provider, model_id, base_url, reflect_provider,
        # reflect_model_id, etc. This makes RecordingLLMBridge a drop-in
        # replacement — the agent's `self._bridge_factory(**real_kwargs)` call
        # works without any test-side translation.
        self._queues: dict[str, list[Any]] = {}
        for method, value in (responses or {}).items():
            self._queues[method] = list(value) if isinstance(value, list) else [value]
        self.calls: list[tuple[Any, ...]] = []

    # ------------------------------------------------------------------
    # Public LLM-call interface (mirrors LLMBridge)
    # ------------------------------------------------------------------

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Mirror of :meth:`LLMBridge.generate`. Returns a parsed-dict response.

        ``**kwargs`` swallows real-bridge keyword args (``label``, ``components``,
        and any future optional kwarg) so adding telemetry/labeling parameters
        to the real bridge doesn't require touching every test fixture.
        """
        self.calls.append(("generate", system_prompt, user_prompt))
        return self._pop("generate")

    def reflect(
        self,
        exp_id: str,
        hypothesis: str,
        results: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Mirror of :meth:`LLMBridge.reflect`. Returns a parsed-dict reflection."""
        self.calls.append(("reflect", exp_id, hypothesis, results, context))
        return self._pop("reflect")

    def plan(
        self,
        memory_history,
        expert_advice="None",
        force_model="auto",
        config_manual=None,
        model_description=None,
        exploration_checklist="",
        plugin_source_excerpt="",
        current_round=None,
        max_rounds=None,
        trial_allowed=True,
        **kwargs,
    ) -> dict[str, Any]:
        """Mirror of :meth:`LLMBridge.plan`. In the real bridge, ``plan``
        assembles a prompt and calls ``generate``. Here we record the call
        and pop from the ``"generate"`` queue (since the predefined response
        is the ExperimentPlan dict that ``plan`` would have returned).

        The 5th tuple element is a dict of every remaining kwarg the agent
        forwarded. Tests that need to assert on K.6-style fields
        (``trial_vram_budget_gb``, ``last_vram_estimate_gb``, ``last_mode``,
        ...) read it as ``bridge.calls[i][4][key]``. Existing tests that
        only inspect ``calls[i][0]`` continue to work unchanged.

        ``**kwargs`` swallows any new optional planner arg (e.g.
        ``plan_overrides``, ``max_epochs``) so adding one to the real bridge
        doesn't require touching every fixture."""
        recorded_kwargs = {
            "config_manual": config_manual,
            "model_description": model_description,
            "exploration_checklist": exploration_checklist,
            "plugin_source_excerpt": plugin_source_excerpt,
            "current_round": current_round,
            "max_rounds": max_rounds,
            "trial_allowed": trial_allowed,
            **kwargs,
        }
        self.calls.append(("plan", memory_history, expert_advice, force_model, recorded_kwargs))
        return self._pop("generate")

    def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        """Mirror of :meth:`LLMBridge.generate_text`. Returns a plain string."""
        self.calls.append(("generate_text", system_prompt, user_prompt))
        return self._pop("generate_text")

    def tool_call(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: list[dict[str, Any]],
    ) -> Any:
        """Mirror of :meth:`LLMBridge.tool_call`. Returns whatever the test
        registered (typically a ToolCallResult-shaped object or a dict)."""
        self.calls.append(("tool_call", system_prompt, user_prompt, tools))
        return self._pop("tool_call")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pop(self, method: str) -> Any:
        """Pop and return the next predefined response for ``method``.

        Raises ``RuntimeError`` if no response has been registered for the
        method or if the queue has been exhausted. The loud failure is
        intentional — silent fallback would mask test-setup bugs.
        """
        if not self._queues.get(method):
            raise RuntimeError(
                f"RecordingLLMBridge: no canned response left for {method!r}. "
                f"Registered methods: {sorted(self._queues.keys())}. "
                f"Total calls so far: {len(self.calls)}. "
                f"Did the test forget to register a response, or is the agent "
                f"making more calls than expected?"
            )
        return self._queues[method].pop(0)

    # ------------------------------------------------------------------
    # Convenience constructors
    # ------------------------------------------------------------------

    @classmethod
    def for_agent(cls, agent_name: str) -> RecordingLLMBridge:
        """Build a bridge pre-loaded with the canned outputs for an agent.

        Loads every ``*.json`` file under
        ``tests/pseudo_data/api_call_outputs/{agent_name}/`` and uses each
        file's stem as the method name. For example, files
        ``generate.json`` and ``reflect.json`` produce a bridge whose
        ``generate()`` and ``reflect()`` calls return the parsed contents of
        those files (one per call, FIFO).

        Args:
            agent_name: the agent's CLAUDE.md taxonomy name, e.g.
                ``"ml_hyperparameter_tune_agent"``.

        Raises:
            FileNotFoundError: if no pseudo-data directory exists for the
                given agent. See ``docs/pseudo_test_infra.md`` for the
                directory layout.
        """
        responses = load_pseudo_data("api_call_outputs", agent_name)
        return cls(responses=responses)
