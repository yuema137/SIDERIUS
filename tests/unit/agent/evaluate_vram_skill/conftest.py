"""Explicit historical workload selection for calibrated regression witnesses."""

from dataclasses import replace

import pytest

from core.preflight_estimation import (
    BatchSegmentationLimit,
    bind_preflight_estimator,
    resolve_preflight_estimator,
)


@pytest.fixture
def historical_workload_rule():
    """Keep the old incident tests without restoring a native implicit ceiling."""
    profile = replace(
        resolve_preflight_estimator(), workload_rule=BatchSegmentationLimit(limit=800_000)
    )
    with bind_preflight_estimator(profile):
        yield
