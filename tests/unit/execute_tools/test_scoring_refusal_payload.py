"""Child refusal bytes preserve absent-evaluation compatibility (#1388)."""

from types import SimpleNamespace

import pytest

from execute_tools import denoising_score_single as scoring
from execute_tools.evaluation_child import aggregate_child_outcome
from execute_tools.evaluation_metric import (
    NotScoreableResult,
    ScoreabilityFailure,
    ScoreabilityVerdict,
)
from tests.unit.execute_tools.test_evaluation_aggregation import composed, result

# Captured from the pre-#1377 emitter (a681c7da3^1); do not derive from current models.
LEGACY_REFUSAL = b"""{
    "retained": "parent",
    "denoising_score": null,
    "file_vector": null,
    "not_scoreable": {
        "metric_id": "accuracy",
        "direction": "higher",
        "verdict": {
            "contract_id": "presence/v1",
            "failures": [
                {
                    "requirement": "present",
                    "input_identity": null,
                    "detail": "missing prediction"
                }
            ]
        }
    }
}"""


@pytest.mark.parametrize("formula", [False, True])
def test_child_refusal_payload_preserves_legacy_bytes_without_evaluation(tmp_path, formula):
    """Nonempty secondaries must not leak; formula evidence must still survive exit 1."""
    import json

    spec, evaluation = composed()
    composition = SimpleNamespace(
        metric=SimpleNamespace(spec=spec), evaluation=evaluation if formula else None
    )
    refusal = NotScoreableResult(
        metric_id="accuracy",
        direction="higher",
        verdict=ScoreabilityVerdict(
            contract_id="presence/v1",
            failures=(ScoreabilityFailure(requirement="present", detail="missing prediction"),),
        ),
    )
    secondaries = {
        "secondary_metric_results": [result("error", "lower", 2.0).model_dump(mode="json")],
        "secondary_metric_refusals": [],
        "secondary_metric_errors": [],
    }
    outcome, payload = aggregate_child_outcome(composition, refusal, secondaries)
    output = tmp_path / "score.json"
    output.write_text('{"retained": "parent"}')
    with pytest.raises(SystemExit) as exited:
        scoring._emit_outcome(
            SimpleNamespace(output_json=str(output)), outcome, secondaries=payload
        )
    assert exited.value.code == 1
    if formula:
        emitted = json.loads(output.read_bytes())
        assert emitted["evaluation_result"]["failures"]
        assert emitted["secondary_metric_results"] == secondaries["secondary_metric_results"]
    else:
        assert output.read_bytes() == LEGACY_REFUSAL
