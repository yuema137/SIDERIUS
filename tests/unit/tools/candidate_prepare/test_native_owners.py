"""Pin extraction against captured pre-change output, not compatibility aliases."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from agent.schemas.interpretation import InterpretationInput
from nodes.result_interpretation_agent import (
    ResultInterpretationAgent,
    build_cold_start_interpretation,
)
from tools.candidate_worker.layout import candidate_proposal_dir
from workflows.llm_config import WorkflowLLMConfig
from workflows.proposal_pipeline import get_reasoning_pipeline

ORACLE = json.loads(
    (
        Path(__file__).resolve().parents[3] / "fixtures/candidate_prepare/native_baseline.json"
    ).read_text()
)


@pytest.mark.parametrize("case", ORACLE["cold_start"], ids=lambda case: case["name"])
def test_cold_start_frozen_output_and_production_reachability(case):
    """Loss of narrative, metric, memory or retention changes the pinned output."""
    inp = InterpretationInput.model_validate(case["input"])
    assert build_cold_start_interpretation(inp).model_dump(mode="json") == case["output"]
    bridge = Mock()
    bridge.generate.side_effect = AssertionError("unexpected model call")
    with patch(
        "nodes.result_interpretation_agent.build_cold_start_interpretation",
        wraps=build_cold_start_interpretation,
    ) as helper:
        agent = ResultInterpretationAgent(bridge_factory=lambda **kwargs: bridge)
        assert agent.run(inp).model_dump(mode="json") == case["output"]
        helper.assert_called_once_with(inp)


@pytest.mark.parametrize("case", ORACLE["pipelines"], ids=lambda case: case["name"])
def test_pipeline_frozen_configuration(case):
    """Stage order, defaults and explicit overrides survive the owner move."""
    pipeline = get_reasoning_pipeline(
        WorkflowLLMConfig.model_validate(case["config"]), **case["kwargs"]
    )
    assert (pipeline.model_dump(mode="json") if pipeline else None) == case["output"]


def test_explicit_cold_start_and_noncreating_layout(tmp_path):
    inp = InterpretationInput.model_validate(ORACLE["cold_start"][0]["input"])
    with pytest.raises(ValueError, match="explicit cold_start"):
        build_cold_start_interpretation(inp.model_copy(update={"cold_start": False}))
    assert (
        candidate_proposal_dir(tmp_path / "run", "named")
        == tmp_path / "run/named/iteration_001/attempt_001"
    )
    assert not (tmp_path / "run").exists()
