"""
Build a SampleSet from trial parameters.

A SampleSet is the single source of truth for which segments from which
files to use in training, inference, and scoring. It is determined once
per experiment and passed consistently through all three stages.

    SampleSet = {file_index: [segment_indices], ...}

Normal mode (is_trial=False) is a special case:
    {file_index: [0, 1, ..., 199]}   (all segments of one file)

All functions are pure — no I/O, no side effects, fully deterministic
when a seed is provided.
"""

import random
from typing import Literal

from execute_tools.dataset_config import TIDMAD, DataScope
from execute_tools.scoring_utils import SEGMENTS_PER_FILE, SampleSet

# Files used by the "anchors" strategy: low, mid, high frequency extrema
ANCHOR_FILES = [0, 10, 19]


def build_sample_set(
    is_trial: bool,
    file_index: int = 6,
    trial_strategy: Literal["snapshot", "anchors", "target"] = "snapshot",
    trial_portion: float = 0.1,
    target_files: list[int] | None = None,
    seed: int | None = None,
    scope: DataScope | None = None,
) -> SampleSet:
    """
    Build a SampleSet from trial parameters.

    Constructive DataScope enforcement (docs/design/enable_partial_file_list.md):
    every SampleSet produced here satisfies the scope by construction. Under a
    partial scope only ``"snapshot"`` is legal — it samples uniformly across
    the allowed files. ``"anchors"`` / ``"target"`` are strategy-level illegal
    under a partial scope (even when ``target_files`` ⊆ scope); this hard stop
    fires only on operator/programming errors — the tuner normalizes LLM plans
    to ``"snapshot"`` before reaching here.

    Args:
        is_trial:        If False, return normal mode (all segments of ``file_index``).
        file_index:      File to use in normal mode. Ignored when ``is_trial=True``.
        trial_strategy:  One of ``"snapshot"``, ``"anchors"``, ``"target"``.
        trial_portion:   Fraction of segments to sample per file (0.0-1.0).
        target_files:    File indices to sample from (required for ``"target"`` strategy).
        seed:            Random seed for reproducible sampling. ``None`` = non-deterministic.
        scope:           DataScope restricting which files may be used.
                         ``None`` = complete dataset (behavior identical to
                         before scope existed).

    Returns:
        A ``SampleSet`` mapping file indices to lists of segment indices.

    Raises:
        ValueError: If ``trial_strategy="target"`` and ``target_files`` is empty.
        ValueError: If the scope is partial and ``trial_strategy`` is not
            ``"snapshot"``, or (normal mode) ``file_index`` is out of scope.
        ValueError: If ``trial_portion`` results in 0 segments per file.
    """
    resolved_scope = (scope or DataScope.default()).resolve(TIDMAD)
    scope_is_full = resolved_scope == list(range(TIDMAD.num_files))

    if not is_trial:
        return _build_normal(file_index, resolved_scope)

    # Determine which files to include
    if trial_strategy == "snapshot":
        files = list(resolved_scope)
    elif trial_strategy in ("anchors", "target"):
        if not scope_is_full:
            raise ValueError(
                f"trial_strategy={trial_strategy!r} is not allowed under a "
                f"partial DataScope {resolved_scope} — only 'snapshot' may be "
                f"used when the scope is a subset of the dataset "
                f"(strategy-level rule; see docs/design/enable_partial_file_list.md)."
            )
        if trial_strategy == "anchors":
            files = list(ANCHOR_FILES)
        else:
            if not target_files:
                raise ValueError("trial_strategy='target' requires non-empty target_files.")
            files = sorted(set(target_files))
    else:
        raise ValueError(f"Unknown trial_strategy: {trial_strategy!r}")

    # Compute number of segments to sample per file
    n_segments = max(1, round(trial_portion * SEGMENTS_PER_FILE))

    rng = random.Random(seed)
    sample_set: SampleSet = {}
    all_indices = list(range(SEGMENTS_PER_FILE))

    for fi in files:
        sampled = sorted(rng.sample(all_indices, min(n_segments, SEGMENTS_PER_FILE)))
        sample_set[fi] = sampled

    return sample_set


def _build_normal(file_index: int, resolved_scope: list[int]) -> SampleSet:
    """Normal mode: all segments of a single file (must be in scope).

    Raises:
        ValueError: If ``file_index`` is outside ``resolved_scope``.
    """
    if file_index not in resolved_scope:
        raise ValueError(f"file_index={file_index} is outside the DataScope {resolved_scope}.")
    return {file_index: list(range(SEGMENTS_PER_FILE))}
