"""Boundary recorder for Step-00 prompt goldens (design §14, §4.1-4.2).

Captures the final ordered ``(system_prompt, user_prompt)`` string pair at
the last deterministic point before ``client.chat.completions.create`` —
the true LLM request boundary (design §4.1) — while executing the REAL
``LLMBridge`` render bodies.

Mechanism: subclass the production ``LLMBridge`` and override exactly the
three methods that own a ``chat.completions.create`` call site
(``_chat_json`` at agent/llm_bridge.py:1282, ``generate_text`` at :1489,
``tool_call`` at :1539). Everything above them — ``plan()``'s and
``reflect()``'s internal renders, ``generate()``'s pass-through body — runs
UNMODIFIED production code, so the recorded pair is byte-identical to what
the API would receive (§10.1's validation consequence: a render change is
observed, not just an argument change).

No-network guard (design §13.1/§14, review F14): both OpenAI clients are
replaced with a raising sentinel after construction, so any un-overridden
path that reaches a real client fails loudly offline instead of issuing a
billable call. Tests must additionally assert the recorder FIRED
(``len(captures) >= 1``).
"""

from __future__ import annotations

from typing import Any

from agent.llm_bridge import LLMBridge


class NetworkEscapeError(AssertionError):
    """A capture path reached the (neutered) OpenAI client object."""


class _RaisingClientProxy:
    """Stands in for ``openai.OpenAI``; any attribute access raises."""

    def __getattr__(self, name: str) -> Any:
        raise NetworkEscapeError(
            f"BoundaryRecorderBridge: attempted real-client access "
            f"({name!r}) — a capture path escaped the recorder overrides. "
            "No network is permitted in golden capture (design §14)."
        )


class BoundaryRecorderBridge(LLMBridge):
    """``LLMBridge`` whose API-boundary methods record instead of calling.

    Attributes:
        captures: list of ``(method, label, system_prompt, user_prompt)``
            tuples, one per intercepted would-be API call, in order.
        components_log: list of ``(label, sorted_component_keys | None)``
            per intercepted call — the ``components`` telemetry breakdown
            crossing the boundary (WF-3's second half; closure-audit F1).
            Kept as a parallel attribute so the 4-tuple ``captures`` shape
            every PB test unpacks stays stable.
    """

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("provider", "openai")
        kwargs.setdefault("model_id", "step00-capture")
        # Explicit dummy key: construction must not read developer env keys.
        kwargs.setdefault("api_key", "step00-no-network")
        super().__init__(**kwargs)
        self.client = _RaisingClientProxy()  # type: ignore[assignment]
        self.reflect_client = _RaisingClientProxy()  # type: ignore[assignment]
        self.captures: list[tuple[str, str, str, str]] = []
        self.components_log: list[tuple[str, list[str] | None]] = []

    def _log_components(self, label: str, components: dict | None) -> None:
        self.components_log.append((label, sorted(components) if components is not None else None))

    # --- the three create-owning methods (design §4.1) -----------------

    def _chat_json(
        self,
        client: Any,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        *,
        label: str = "unlabeled",
        provider: str | None = None,
        components: dict[str, int] | None = None,
    ) -> dict:
        self.captures.append(("_chat_json", label, system_prompt, user_prompt))
        self._log_components(label, components)
        return {}

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        label: str = LLMBridge._DEFAULT_LABEL,
        components: dict[str, int] | None = None,
    ) -> str:
        self.captures.append(("generate_text", label, system_prompt, user_prompt))
        self._log_components(label, components)
        return ""

    def tool_call(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: list[dict[str, Any]],
        *,
        label: str = LLMBridge._DEFAULT_LABEL,
        components: dict[str, int] | None = None,
    ) -> Any:
        self.captures.append(("tool_call", label, system_prompt, user_prompt))
        self._log_components(label, components)
        return None
