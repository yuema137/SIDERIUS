"""Check observed rate blocks before accepting a later measurement window.

A reference block establishes observed support, not a stable prediction.
Retain its observed upper support and compare whole blocks:
recurring expensive observations are not by themselves evidence of a shift.
This is a conservative observed-evidence guard, not a statistical guarantee.
"""

import statistics
from dataclasses import dataclass

from core.runtime_control.steady_state import SteadyStateConfig


@dataclass(frozen=True)
class DistributionShift:
    reference_start: int
    split: int
    previous_median_ms: float
    current_median_ms: float


def relative_median_change(rates: list[float]) -> float:
    """Compare two nonempty halves of validated positive observations."""
    half = len(rates) // 2
    return abs(statistics.median(rates[half:]) / statistics.median(rates[:half]) - 1)


def find_distribution_shift(
    rates: list[float], *, steady: SteadyStateConfig, pathological_factor: float
) -> DistributionShift | None:
    """Find disjoint rate regimes using positive, validated observations.

    Both blocks require at least the policy's detection-window length. Start
    from the first observation window without a pathological upper
    tail, extending backward through contiguous ordinary observations. This
    excludes an initial warm-up outlier without selecting a minimum median
    across the run. Every later observation remains in the comparison.

    Refuse only when ALL observations after a split exceed the earlier observed
    maximum and the block median exceeds the configured factor. Overlapping
    distributions are inconclusive here; the ordinary detector and budgets
    still apply. This cannot anticipate changes after verification ends.
    """
    width = steady.min_steps_to_detect
    reference = None
    for end in range(width, len(rates) - width + 1):
        window = rates[end - width : end]
        ceiling = pathological_factor * statistics.median(window)
        if max(window) <= ceiling:
            start = end - width
            while start > 0 and rates[start - 1] <= ceiling:
                start -= 1
            reference = (start, end)
            break
    if reference is None:
        return None

    start, end = reference
    suffix_min = list(rates)
    for index in range(len(rates) - 2, -1, -1):
        suffix_min[index] = min(rates[index], suffix_min[index + 1])
    previous_max = max(rates[start:end])
    for split in range(end, len(rates) - width + 1):
        previous_max = max(previous_max, rates[split - 1])
        if suffix_min[split] <= previous_max:
            continue
        before = statistics.median(rates[start:split])
        after = statistics.median(rates[split:])
        if after > pathological_factor * before:
            return DistributionShift(start, split, before, after)
    return None
