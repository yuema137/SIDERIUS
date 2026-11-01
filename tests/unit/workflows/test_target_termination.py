"""Target decisions preserve metric direction and require ranked evidence."""

import pytest

from execute_tools.metric_order import MetricOrder
from tests.helpers.metric_fixtures import direction_only_spec
from workflows.termination import target_reached, workflow_stop_reason


@pytest.mark.parametrize("incumbent, expected", [(0.1, True), (0.2, True), (0.3, False)])
def test_lower_metric_target(incumbent, expected):
    """An inverted comparison would stop the worse result and miss the better one."""
    assert target_reached(incumbent, 0.2, MetricOrder(direction_only_spec())) is expected


def test_unranked_restored_incumbent_does_not_claim_target():
    """A restored number alone cannot establish direction or target success."""
    assert not target_reached(0.1, 0.2, None)
    assert workflow_stop_reason([], 0.1, 0.2, None) == "iterations_exhausted"
