"""Regression tests pinning ``StubLLMBridge.__init__`` against the exact
keyword sets every agent passes through ``self._bridge_factory(...)``.

C5 of the Stage 3 / Commit 4.5 ladder caught a wiring gap: PR #74's stub
took only ``max_retries`` while every agent's factory call passes
``provider`` / ``model_id`` (and the tuner additionally passes
``reflect_provider`` / ``reflect_model_id``). The smoke run crashed with
``TypeError: StubLLMBridge.__init__() got an unexpected keyword argument
'provider'`` mid-chain.

These tests instantiate ``StubLLMBridge`` with the same call shapes the 5
agent constructors use today, plus a few defensive cases. If a future
agent introduces a new bridge kwarg, this file is where the contract
breaks first — not in production.

Agent → call shape (kwargs the factory receives):
  * ``ResultInterpretationAgent``  → provider, model_id, max_retries
  * ``MLModelProposalAgent``       → provider, model_id, max_retries
  * ``MLModelImplementor``         → provider, model_id, max_retries
  * ``MLCodeValidatorAgent``       → provider, model_id, max_retries
  * ``HyperparamTuningAgent``      → provider, model_id, reflect_provider,
                                     reflect_model_id, max_retries
"""
from __future__ import annotations

from agent.llm_bridge import StubLLMBridge


def test_4_agents_call_shape_provider_model_id_max_retries():
    """Interpretation / Proposer / Implementor / Validator all use this shape."""
    bridge = StubLLMBridge(
        provider="gemini",
        model_id="gemini-3.1-flash-lite-preview",
        max_retries=3,
    )
    assert bridge.provider == "stub"
    assert bridge.model_name == "stub_model"
    assert bridge.max_retries == 3


def test_tuner_call_shape_with_reflect_pair():
    """``HyperparamTuningAgent`` passes the 5-kwarg shape with reflect_*."""
    bridge = StubLLMBridge(
        provider="gemini",
        model_id="gemini-3.1-pro-preview",
        reflect_provider="openai",
        reflect_model_id="gpt-5-mini",
        max_retries=2,
    )
    assert bridge.provider == "stub"
    assert bridge.reflect_provider == "stub"
    assert bridge.max_retries == 2


def test_no_kwargs_still_works():
    """All call kwargs are optional — the stub remains constructible bare
    so unit tests that don't care about the LLM identity stay terse."""
    bridge = StubLLMBridge()
    assert bridge.provider == "stub"
    assert bridge.model_name == "stub_model"


def test_caller_provider_is_ignored_by_design():
    """The stub is a single black-box; caller-supplied ``provider`` /
    ``model_id`` must be silently dropped, not propagated. Anything else
    would let the smoke harness pretend to multiplex providers it cannot
    actually serve."""
    bridge = StubLLMBridge(provider="anthropic", model_id="claude-opus-4-7")
    assert bridge.provider == "stub"
    assert bridge.model_name == "stub_model"


def test_max_retries_default_is_zero():
    """No HTTP calls means retries are nonsensical — default to 0, not None,
    to make absent-vs-disabled obvious in any caller's introspection."""
    bridge = StubLLMBridge()
    assert bridge.max_retries == 0
