"""Single-route node constructors accept exactly their named parameters (#1597).

What only these tests catch:

* an unknown or misspelled keyword (``max_retry=3``) is refused with
  ``TypeError`` instead of being silently dropped, which would leave the node
  on a default the caller never chose;
* the removal of ``**kwargs`` stays safe for production: every key the
  workflow's ``NodeLLMConfig`` flattening can emit for these routes (provider,
  model id, retry limit, output-token limit, reasoning effort, transport) is a
  named parameter, so ``Node(**config.get(route))`` keeps working.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nodes.ml_code_validator_agent.ml_code_validator_agent import MLCodeValidatorAgent
from nodes.ml_model_implementor.ml_model_implementor import MLModelImplementor
from nodes.result_interpretation_agent.result_interpretation_agent import (
    ResultInterpretationAgent,
)
from workflows.llm_config import NodeLLMConfig, WorkflowLLMConfig

_NODES = {
    "interpret": ResultInterpretationAgent,
    "implement": MLModelImplementor,
    "validate": MLCodeValidatorAgent,
}


@pytest.mark.parametrize("route", sorted(_NODES))
def test_unknown_keyword_is_refused(route):
    """Fails if the constructor swallows a misspelled keyword again."""
    with pytest.raises(TypeError, match="max_retry"):
        _NODES[route](bridge_factory=MagicMock(), max_retry=3)


@pytest.mark.parametrize("route", sorted(_NODES))
def test_every_flattened_route_key_is_a_named_parameter(route):
    """Fails if a key the workflow config can emit for this route is not a
    named constructor parameter (production would then raise TypeError)."""
    full = NodeLLMConfig(
        provider="openai",
        model_id="test-model",
        max_retries=2,
        max_output_tokens=1024,
        reasoning_effort="low",
        openai_background={"completion_window": "8h", "max_wait_seconds": 36000},
    )
    slot = "validate_model" if route == "validate" else route
    config = WorkflowLLMConfig(**{slot: full})
    kwargs = config.get(route)
    assert set(kwargs) == {
        "provider",
        "model_id",
        "max_retries",
        "max_output_tokens",
        "reasoning_effort",
        "transport",
    }
    factory = MagicMock()
    _NODES[route](**kwargs, bridge_factory=factory)
    assert factory.call_count == 1
