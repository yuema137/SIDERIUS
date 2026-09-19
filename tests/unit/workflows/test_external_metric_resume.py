"""Regression: external scoreability classes must survive the next process's Step 0.

Object equality rejected identical persisted/active declarations on 2026-09-19.
The fresh-process test fails at native reconciliation before the repair; mutation
controls prevent fixing it by comparing only metric id/direction.
"""

import json
import subprocess
import sys

import pytest

from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from execute_tools.evaluation_metric import (
    MetricIdentityConflictError,
    ScoreabilityContract,
    ScoreabilityVerdict,
    StampedMetricSpec,
    metric_spec_from_declaration,
    metric_spec_from_persisted_record,
    reconcile_metric_specs,
)


class ExternalContract(ScoreabilityContract):
    contract_id: str = "synthetic_resume_contract"
    required_marker: int = 7

    def check(self, deliverables):
        return ScoreabilityVerdict(contract_id=self.contract_id)


def declaration():
    return {
        "id": "external_quality",
        "direction": "higher",
        "aggregation": "mean",
        "transform": "log",
        "transform_params": {"log_base": 2.0},
        "references": ["anchor"],
        "scoreability": {"contract_id": "synthetic_resume_contract", "required_marker": 7},
    }


def active_spec():
    return metric_spec_from_declaration(
        declaration(), scoreability_contract_types={"synthetic_resume_contract": ExternalContract}
    )


def test_written_scored_output_is_consumable_by_next_process(tmp_path):
    output = HyperparamTuningOutput(
        run_name="iter_001",
        model_type="synthetic_model",
        file_index=0,
        status="completed",
        completed_rounds=1,
        total_attempts=1,
        started_at="2026-09-19T00:00:00Z",
        finished_at="2026-09-19T00:01:00Z",
        metric_spec=active_spec(),
        all_records=[
            {
                "exp_id": "synthetic_formal",
                "model_type": "synthetic_model",
                "status": "success",
                "timestamp": "2026-09-19T00:01:00Z",
                "params": {},
                "denoising_score": 3.0,
                "metric_result": {
                    "metric_id": "external_quality",
                    "direction": "higher",
                    "scalar": 3.0,
                },
                "health_gate_enabled": False,
            }
        ],
    )
    path = tmp_path / "run_output_iter_001.json"
    path.write_text(output.model_dump_json())
    # Import the fixture by filename, not PYTHONPATH; the actual loader and
    # reconciliation are the same two operations used at workflow Step 0.
    child = """
import runpy, sys
from workflows.model_exploration import load_tuning_outputs_from_paths
from nodes.result_interpretation_agent.evidence import reconcile_metric_spec
fixture = runpy.run_path(sys.argv[1])
active = fixture['active_spec']()
outputs = load_tuning_outputs_from_paths([sys.argv[2]])
assert outputs[0].all_records[0].denoising_score == 3.0
assert reconcile_metric_spec(outputs, bound=active) is active
try:
    outputs[0].metric_spec.scoreability.check({})
except RuntimeError as exc:
    assert 'not executable' in str(exc)
else:
    raise AssertionError('restored declaration acquired executable authority')
print('next-iteration-input-ready')
"""
    result = subprocess.run(
        [sys.executable, "-c", child, __file__, str(path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "next-iteration-input-ready" in result.stdout


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "other"),
        ("direction", "lower"),
        ("aggregation", "sum"),
        ("transform", None),
        ("transform_params", {"log_base": 3.0}),
        ("references", ["other_anchor"]),
        ("scoreability", {"contract_id": "synthetic_resume_contract", "required_marker": 8}),
        ("scoreability", {"contract_id": "other_contract", "required_marker": 7}),
    ],
)
def test_actual_declared_changes_still_refuse(field, value):
    payload = declaration()
    payload[field] = value
    restored = metric_spec_from_persisted_record(json.loads(json.dumps(payload)))
    with pytest.raises(MetricIdentityConflictError):
        reconcile_metric_specs([StampedMetricSpec("persisted", restored)], bound=active_spec())
