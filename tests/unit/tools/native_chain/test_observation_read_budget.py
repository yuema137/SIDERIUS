"""Large valid retained histories need independent input and projection allowances."""

import json
from pathlib import Path

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from tests.unit.scripts.test_inspect_run_state import _write_clean_chain_iter
from tests.unit.tools.native_chain.test_checkpoint_observation import stamp
from tools.native_chain.observation import ObservationBounds, observe_native_chain


def large_history(workspace: Path, iteration: int = 1) -> int:
    directory = _write_clean_chain_iter(workspace, iteration)
    manifest = directory / "manifest.json"
    output = Path(json.loads(manifest.read_text())["output_path"])
    data = json.loads(output.read_text())
    data["all_records"] = [
        {
            "exp_id": f"experiment-{index}",
            "status": "success",
            "model_type": "wavenet",
            "timestamp": "2026-10-25T00:00:00Z",
            "params": {"retained_note": "x" * 1400},
        }
        for index in range(1100)
    ]
    output.write_text(HyperparamTuningOutput.model_validate(data).model_dump_json())
    stamp(manifest)
    assert output.stat().st_size > 1048576
    return output.stat().st_size + manifest.stat().st_size


def limits(**changes):
    return ObservationBounds.model_validate(
        dict(
            final_iteration=2,
            input_max_bytes=16777216,
            max_observation_bytes=1048576,
            max_evidence_read_bytes=16777216,
        )
        | changes
    )


def test_large_history_compact_projection_and_independent_limits(tmp_path):
    consumed = large_history(tmp_path)
    result = observe_native_chain(tmp_path, "native", limits())
    assert result.availability == "available"
    assert result.checkpoints[0].artifact_verified
    assert len(result.model_dump_json().encode()) < 4096
    for changes in (
        {"max_evidence_read_bytes": None},
        {"max_evidence_read_bytes": consumed - 1},
        {"input_max_bytes": 1048576},
        {"max_observation_bytes": 10},
    ):
        assert (
            observe_native_chain(tmp_path, "native", limits(**changes)).availability
            == "limit_exceeded"
        )
    second = large_history(tmp_path, 2)
    assert (
        observe_native_chain(
            tmp_path, "native", limits(max_evidence_read_bytes=consumed + second + 256)
        ).availability
        == "available"
    )
    assert (
        observe_native_chain(
            tmp_path, "native", limits(max_evidence_read_bytes=consumed + second - 1)
        ).availability
        == "limit_exceeded"
    )


@pytest.mark.parametrize("policy,read_bytes", [(1, 4096), (2, 4096), (3, None)])
def test_explicit_policy_budget_mismatch_is_rejected(tmp_path, policy, read_bytes):
    with pytest.raises(ValueError, match="requires observation policy 3"):
        observe_native_chain(
            tmp_path, "native", limits(max_evidence_read_bytes=read_bytes), policy=policy
        )
