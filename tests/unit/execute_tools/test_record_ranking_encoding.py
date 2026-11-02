"""Raw persisted ranking must return decoded scientific data."""

import math

import pytest

from core.record_encoding import METADATA, encoded_record
from execute_tools.persisted_ranking import best_by_declared_metric, partition_by_metric_identity


@pytest.mark.parametrize("score", [float("-inf"), float("inf"), float("nan")])
def test_raw_record_ranking_decodes_values_and_does_not_leak_metadata(score):
    values = [
        {
            "exp_id": str(index),
            "denoising_score": value,
            "metric_result": {"metric_id": "test", "direction": "higher", "scalar": value},
        }
        for index, value in enumerate((0.5, score, 0.4))
    ]
    raw = [encoded_record(value) for value in values]
    best = best_by_declared_metric(raw, context="encoding regression")
    assert best is not None
    # A non-finite record is decoded evidence, never the best record (#1316):
    # with ``is not None`` ranking, +inf wins here and the equality fails.
    assert best["denoising_score"] == 0.5
    rankable, _ = partition_by_metric_identity(raw)
    assert all(METADATA not in row for row in rankable)
    value = rankable[1]["denoising_score"]
    assert math.isnan(value) if math.isnan(score) else value == score
