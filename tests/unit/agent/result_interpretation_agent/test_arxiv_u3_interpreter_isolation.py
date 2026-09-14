"""arXiv U3 (#260) — the REAL interpreter under baseline isolation.

The loader's refusal is unit-tested at the loader; what only THIS file
catches is the interpreter's half of claim (ii): the node forwards its
input flag to the loader, so under isolation a bundled description can
never be loaded — and therefore never enters the carried
``model_knowledge_cache`` ``_stats`` (the cache write sits AFTER the load
on the same path). The counterfactual run pins that the non-isolated
cache DOES carry the bundled prose, so the isolated assertion is not
vacuous; the inline-plugin run pins that isolation starves only the
bundled channel.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ml_models.model_descriptions import DescriptionSourcePolicy
from nodes.result_interpretation_agent import ResultInterpretationAgent
from tests.unit.agent.result_interpretation_agent.test_interpretation_agent import (
    PUNET_SUMMARY,
    _llm_dispatch,
    make_input,
)


def _agent() -> ResultInterpretationAgent:
    with patch("nodes.result_interpretation_agent.LLMBridge") as MockBridge:
        MockBridge.return_value.generate.side_effect = _llm_dispatch
        agent = ResultInterpretationAgent(provider="gemini", model_id="test-model")
        agent.bridge = MockBridge.return_value
    return agent


def test_isolation_refuses_the_bundled_description_before_any_cache_write(tmp_path):
    inp = make_input(PUNET_SUMMARY, workspace=str(tmp_path))
    inp.baseline_isolation = True
    with pytest.raises(FileNotFoundError, match="baseline_isolation"):
        _agent().run(inp)


def test_without_isolation_the_bundled_description_is_cached_the_counterfactual(tmp_path):
    output = _agent().run(make_input(PUNET_SUMMARY, workspace=str(tmp_path)))
    cached = output.model_knowledge_cache["punet"]["_stats"]["model_description"]
    assert cached.startswith("# PUNet"), (
        "the non-isolated cache no longer carries the bundled prose — the "
        "isolated refusal above would be vacuous"
    )


def test_isolation_still_caches_an_inline_plugin_description(tmp_path):
    summary = PUNET_SUMMARY.model_copy(
        update={"model_type": "my_plugin_tcn", "model_description": "# my_plugin_tcn body"}
    )
    inp = make_input(summary, workspace=str(tmp_path))
    inp.baseline_isolation = True
    output = _agent().run(inp)
    cached = output.model_knowledge_cache["my_plugin_tcn"]["_stats"]["model_description"]
    assert cached == "# my_plugin_tcn body"


def test_composed_absence_completes_without_empty_header_or_cache_prose(tmp_path):
    """Composed missing prose is a typed absence, not a loader failure."""
    inp = make_input(PUNET_SUMMARY, workspace=str(tmp_path))
    inp.description_source_policy = DescriptionSourcePolicy.COMPOSED
    output = _agent().run(inp)
    assert "punet" not in output.model_descriptions
    stats = output.model_knowledge_cache["punet"].get("_stats", {})
    assert "model_description" not in stats


def test_composed_inline_description_precedes_any_loader(tmp_path):
    """Current-iteration prose wins before workspace/generated/pack lookup."""
    summary = PUNET_SUMMARY.model_copy(update={"model_description": "# inline task prose"})
    inp = make_input(summary, workspace=str(tmp_path))
    inp.description_source_policy = DescriptionSourcePolicy.COMPOSED
    with patch(
        "nodes.result_interpretation_agent.get_model_description",
        side_effect=AssertionError("inline authority must bypass the loader"),
    ):
        output = _agent().run(inp)
    assert output.model_knowledge_cache["punet"]["_stats"]["model_description"] == (
        "# inline task prose"
    )
