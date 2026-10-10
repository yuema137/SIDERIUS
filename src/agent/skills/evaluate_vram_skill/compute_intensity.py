"""Evaluate an explicitly selected batch/segmentation product rule.

A transport dimension does not establish kernel cost or GPU capacity. Native
preflight therefore has no universal product ceiling. A trusted, source-pinned
estimator profile may declare a workload rule; historical values belong in the
experiment package. Memory estimates, bounded measurement and execution resource
protection retain their own authorities.
"""

from core.preflight_estimation import active_workload_rule


def configured_limit() -> int | None:
    """The selected profile's limit; absence means this rule is inapplicable."""
    rule = active_workload_rule()
    return rule.limit if rule is not None else None


def compute_intensity(batch_size: int, segmentation_size: int) -> int:
    """Raw product, without claiming it measures computational cost."""
    return batch_size * segmentation_size


def passes(batch_size: int, segmentation_size: int) -> bool:
    """Check an explicit rule; absence does not establish measured feasibility."""
    limit = configured_limit()
    return limit is None or compute_intensity(batch_size, segmentation_size) <= limit


def require_limit() -> int:
    """A diagnostic cannot invent a limit when the selected profile has none."""
    limit = configured_limit()
    if limit is None:
        raise ValueError("No batch/segmentation workload rule is selected")
    return limit


def describe_violation(batch_size: int, segmentation_size: int) -> str:
    """Name the explicit constraint without claiming task-locked values can change."""
    product = compute_intensity(batch_size, segmentation_size)
    limit = require_limit()
    return (
        f"Current batch_size × segmentation_size = {batch_size} × "
        f"{segmentation_size} = {product:,}, which exceeds the selected workload "
        f"limit of {limit:,}. Check task-supported batch_size and segmentation_size "
        "settings; do not reduce task-locked dimensions or data coverage."
    )
