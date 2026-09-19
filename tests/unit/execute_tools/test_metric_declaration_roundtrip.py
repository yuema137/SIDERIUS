"""Persisted task declarations reconcile without importing executable plugins."""

import json
from collections.abc import Mapping

import pytest

from execute_tools.evaluation_metric import (
    MetricIdentityConflictError,
    MetricSpec,
    PersistedScoreabilityContract,
    ScoreabilityContract,
    ScoreabilityVerdict,
    StampedMetricSpec,
    metric_spec_from_persisted_record,
    reconcile_metric_specs,
)


class ExternalContract(ScoreabilityContract):
    contract_id: str = "synthetic_external_signal"
    required_fields: tuple[str, ...] = ("signal", "units")
    minimum_samples: int = 4

    def check(self, deliverables: Mapping[int, str]) -> ScoreabilityVerdict:
        raise AssertionError("reconciliation must not execute scoreability")


def _spec() -> MetricSpec:
    return MetricSpec(
        id="synthetic_quality",
        direction="higher",
        aggregation="mean",
        transform="log",
        transform_params={"base": 2.0},
        references=("reference",),
        scoreability=ExternalContract(),
    )


def test_external_metric_json_roundtrip_reconciles_to_bound_executable_spec():
    bound = _spec()
    restored = metric_spec_from_persisted_record(json.loads(bound.model_dump_json()))
    assert isinstance(restored.scoreability, PersistedScoreabilityContract)
    assert restored != bound  # Pydantic compares Python types as well as values.
    result = reconcile_metric_specs([StampedMetricSpec("previous run", restored)], bound=bound)
    assert result is bound
    with pytest.raises(RuntimeError, match="not executable"):
        restored.scoreability.check({})


def test_without_bound_reconciliation_keeps_data_only_reference():
    live = _spec()
    restored = metric_spec_from_persisted_record(json.loads(live.model_dump_json()))
    result = reconcile_metric_specs(
        [StampedMetricSpec("saved", restored), StampedMetricSpec("live", live)]
    )
    assert result is restored


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("id", "other_quality"),
        ("direction", "lower"),
        ("aggregation", "median"),
        ("transform", "identity"),
        ("transform_params", {"base": 10.0}),
        ("references", ["other_reference"]),
        ("scoreability", {"contract_id": "other_contract"}),
        (
            "scoreability",
            {
                "contract_id": "synthetic_external_signal",
                "required_fields": ["signal"],
                "minimum_samples": 4,
            },
        ),
        (
            "scoreability",
            {
                "contract_id": "synthetic_external_signal",
                "required_fields": ["signal", "units"],
                "minimum_samples": 5,
            },
        ),
    ],
)
def test_changed_declaration_still_refused_and_names_changed_field(field, replacement):
    bound = _spec()
    payload = json.loads(bound.model_dump_json())
    payload[field] = replacement
    restored = metric_spec_from_persisted_record(payload)
    with pytest.raises(MetricIdentityConflictError) as exc:
        reconcile_metric_specs([StampedMetricSpec("previous run", restored)], bound=bound)
    assert "previous run" in str(exc.value)
    assert f"differing fields: {field}" in str(exc.value)
