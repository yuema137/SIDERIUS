"""Runtime persistence dispatch regressions from issue #1111."""

from typing import Any

import pytest
from pydantic import BaseModel

from tools.candidate_worker.record_json import artifact_json


def test_unknown_artifact_class_refuses_instead_of_projecting_to_null():
    """A dynamic caller typo must not silently choose the lossy record path."""

    class Record(BaseModel):
        score: float = float("-inf")

    kind: Any = "internl"
    with pytest.raises(ValueError, match="unknown artifact class"):
        artifact_json(Record(), kind=kind)


def test_published_request_uses_reread_encoding(prepared, tmp_path, monkeypatch):
    """The child's input file must use the internal artifact class (#1096)."""
    from tools.candidate_worker import launch

    seen = []
    original = launch.artifact_json

    def observe(value, *, kind, **kwargs):
        seen.append(kind)
        return original(value, kind=kind, **kwargs)

    monkeypatch.setattr(launch, "artifact_json", observe)
    path = tmp_path / "request.json"
    launch.publish(path, prepared)
    assert seen == ["internal"]
    assert type(prepared).model_validate_json(path.read_bytes()) == prepared


@pytest.mark.parametrize("number", [float("inf"), float("-inf"), float("nan")])
def test_required_prediction_round_trips_and_legacy_capture_preserves_bytes(
    prepared, tmp_path, number
):
    """Required float nulls made a real proposal unreadable on its second capture."""
    import json
    import math

    from agent.schemas.proposal import ProposalOutput
    from execute_tools.scoring_utils import coerce_nonfinite_to_none
    from tools.candidate_worker.artifacts import capture_record

    from .test_native import Provider

    raw = {**Provider().generate("", ""), "expert_advice": {}}
    raw["falsifiable_prediction"] = {
        "metric": "accuracy",
        "current_value": 0.0,
        "predicted_value": number,
        "threshold_for_refutation": -0.5,
        "rationale": "serialization witness",
    }
    output = ProposalOutput.model_validate(raw)
    path = tmp_path / "proposal.json"
    capture_record(path, output)
    before = path.read_bytes()
    saved = ProposalOutput.model_validate_json(before)
    assert saved.falsifiable_prediction is not None
    result = saved.falsifiable_prediction.predicted_value
    assert math.isnan(result) if math.isnan(number) else result == number
    capture_record(path, output)
    assert path.read_bytes() == before
    legacy = json.dumps(coerce_nonfinite_to_none(output.model_dump())).encode()
    path.write_bytes(legacy)
    capture_record(path, output)
    assert path.read_bytes() == legacy


@pytest.mark.parametrize("number", [float("inf"), float("-inf"), float("nan")])
def test_native_tuner_required_aggregate_round_trips(synthetic_dataset_profile, tmp_path, number):
    """The native writer and worker must share the required-float encoding."""
    import math

    from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
    from agent.schemas.score_table import AggregateScalars, PerFileRow, ScoreComparisonTable
    from execute_tools.dataset_config import resolve_dataset_profile
    from nodes.ml_hyperparameter_tune_agent.records import publish_run_output
    from tests.unit.workflows.test_model_exploration import _make_tuning_output
    from tools.candidate_worker.artifacts import capture_record

    count = resolve_dataset_profile().partition_count
    table = ScoreComparisonTable(
        rows=[
            PerFileRow(
                file_index=i,
                raw_baseline=0.0,
                ground_truth=1.0,
                model=number,
                gain_vs_raw=number,
                headroom_vs_gt=None,
            )
            for i in range(count)
        ],
        aggregate=AggregateScalars(
            raw_baseline_scalar=0.0,
            ground_truth_scalar=1.0,
            model_scalar=number,
            percent_of_ceiling_log=number,
            num_sampled_files=count,
        ),
        s_max_global=1.0,
        reference_source="synthetic",
        rendered_markdown="synthetic",
    )
    output = _make_tuning_output().model_copy(update={"best_valid_score_table": table})
    path = tmp_path / "run_output.json"
    publish_run_output(str(path), output)
    before = path.read_bytes()
    saved = HyperparamTuningOutput.model_validate_json(before)
    assert saved.best_valid_score_table is not None
    result = saved.best_valid_score_table.aggregate.model_scalar
    assert math.isnan(result) if math.isnan(number) else result == number
    capture_record(path, output)
    assert path.read_bytes() == before


def test_internal_artifacts_do_not_lose_nonfinite_any_values():
    """JSON-mode Any projection must not null a reread worker input either."""
    import math

    class Input(BaseModel):
        data: dict[str, Any]

    value = Input(data={"score": float("nan"), "label": "NaN"})
    restored = Input.model_validate_json(artifact_json(value, kind="internal"))
    assert math.isnan(restored.data["score"])
    assert restored.data["label"] == "NaN"


def test_receipt_control_encoding_preserves_typed_values_and_reads_legacy(prepared, tmp_path):
    from core.control_json import encode_control
    from tools.candidate_worker.launch import publish
    from tools.candidate_worker.models import CandidateRunReceipt

    from .test_graph import initial

    receipt = initial(prepared)
    legacy = receipt.model_dump_json().encode()
    assert CandidateRunReceipt.model_validate_json(legacy) == receipt
    route = receipt.selected_constructor_routes[0]
    updated = route.model_copy(
        update={"bridge_arguments": {"score": float("-inf"), "text": "-Infinity"}}
    )
    receipt = receipt.model_copy(update={"selected_constructor_routes": (updated,)})
    path = tmp_path / "receipt.json"
    publish(path, receipt, bounded=True)
    assert path.read_bytes() == encode_control(receipt)
    restored = CandidateRunReceipt.model_validate_json(path.read_bytes())
    assert restored.selected_constructor_routes[0].bridge_arguments == {
        "score": float("-inf"),
        "text": "-Infinity",
    }
