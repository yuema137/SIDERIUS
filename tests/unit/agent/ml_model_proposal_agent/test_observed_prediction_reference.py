"""Only typed measured proposal inputs can supply the comparison baseline."""

import pytest

from agent.schemas.proposal import ProposalInput
from agent.schemas.proposer_evidence import ProposerInterpretationEvidence
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from execute_tools.evaluation_metric import MetricIdentityKey
from nodes.ml_model_proposal_agent.prediction_reference import observed_prediction_reference


@pytest.mark.parametrize("direction", ["higher", "lower"])
@pytest.mark.parametrize("cold_start", [False, True])
@pytest.mark.parametrize("valid_score", [None, -3.0])
def test_reference_uses_valid_observation_and_honors_explicit_cold_start(
    tmp_path, direction, cold_start, valid_score
):
    inp = ProposalInput(
        interpretation_evidence=ProposerInterpretationEvidence(
            metric_identity=MetricIdentityKey("synthetic_quality", direction),
            best_denoising_score=99.0,
            best_valid_denoising_score=valid_score,
        ),
        cold_start=cold_start,
        storage=StorageConfig(
            backend="local", local=LocalStorageConfig(workspace=str(tmp_path), run_name="test")
        ),
    )
    reference = observed_prediction_reference(inp, "synthetic_quality")
    if cold_start or valid_score is None:
        assert reference is None
    else:
        assert reference is not None
        assert reference.value == valid_score
        assert reference.direction == direction
    assert observed_prediction_reference(inp, "synthetic_quality on some files") is None


@pytest.mark.parametrize("pipeline", [False, True])
@pytest.mark.parametrize("cold_start", [False, True])
def test_run_overwrites_forged_reference_before_return_and_persistence(
    tmp_path, monkeypatch, pipeline, cold_start
):
    """Catch either execution route bypassing the framework-owned stamping boundary."""
    import json

    from agent.schemas.proposal import ProposalOutput

    from .test_boldness_enforcement import (
        _make_agent,
        _make_pipeline_input,
        _make_proposing_output,
        _make_reasoning_output,
    )

    inp = _make_pipeline_input(tmp_path)
    inp.cold_start = cold_start
    if not pipeline:
        inp.reasoning_pipeline = None
    payload = _make_proposing_output()
    payload["falsifiable_prediction"] = _make_reasoning_output(999.0, 6.5)["falsifiable_prediction"]
    payload["observed_prediction_reference"] = {
        "metric_id": "denoising_score",
        "direction": "higher",
        "value": 999.0,
        "source": "interpretation_best_valid",
    }
    forged = ProposalOutput.model_validate(payload)
    agent, bridge = _make_agent([])
    selected = "_run_pipeline" if pipeline else "_run_legacy"
    monkeypatch.setattr(agent, selected, lambda *args: forged)
    output = agent.run(inp)
    assert bridge.generate.call_count == 0
    stored = json.loads((tmp_path / "proposal_test.json").read_text())
    expected = None if cold_start else 5.5
    assert output.falsifiable_prediction.current_value == expected
    assert stored["falsifiable_prediction"]["current_value"] == expected
    if cold_start:
        assert output.observed_prediction_reference is None
        assert stored.get("observed_prediction_reference") is None
    else:
        assert output.observed_prediction_reference.value == 5.5
        assert stored["observed_prediction_reference"] == {
            "metric_id": "denoising_score",
            "direction": "higher",
            "value": 5.5,
            "source": "interpretation_best_valid",
        }


def test_grounded_no_change_prediction_retries_its_causal_owner(
    tmp_path, synthetic_dataset_profile
):
    """Grounding 999 to the observed 5.5 must not persist a no-change prediction."""
    from .test_boldness_enforcement import (
        _make_agent,
        _make_comparison_output,
        _make_pipeline_input,
        _make_proposing_output,
        _make_reasoning_output,
    )

    agent, bridge = _make_agent(
        [
            _make_comparison_output(),
            _make_reasoning_output(999.0, 5.5),
            _make_reasoning_output(5.5, 6.5),
            _make_proposing_output(),
        ]
    )
    result = agent.run(_make_pipeline_input(tmp_path))
    assert bridge.generate.call_count == 4
    assert (
        bridge.generate.call_args_list[2].kwargs["label"] == "proposer.causal_reasoning.correction"
    )
    assert result.falsifiable_prediction.current_value == 5.5
    assert result.falsifiable_prediction.predicted_value == 6.5
