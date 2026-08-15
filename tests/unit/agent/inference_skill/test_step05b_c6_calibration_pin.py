"""Step 05b C6 — the one calibration value this PR could accidentally re-own.

Design:
``docs/design/generic_framework_upgrade/step_05b_tuner_resource_time.md``
§2 (a constant is not task configuration merely because it is a constant),
C6 (a preservation audit with a cheapest-sufficient evidence ladder, NOT a
repo-wide pin campaign).

This module exists because of the ladder's layer 4, and it is the only place
that layer applied. Every other §2 calibration value is already covered:

    _MAX_BATCH_TIMESTEPS (800,000)      test_compute_intensity.py — literal pin
    batch candidates (64…1)             test_batch_resolver.py    — literal pin
    _ROLE_DEFAULT_RSS_GB (40/60/24)     test_sandbox_rlimit.py    — literal pin
    SEG_SIZE_BOUNDS (2500, 40,000)      trigger_policy.py is untouched by this
                                        PR — static diff evidence

``_INFERENCE_VS_TRAINING_RATIO`` is the exception on both counts: no test in
the repository asserts its VALUE (several reference the symbol, which passes
for any number it holds), and Step 05b **edits the module it lives in** —
C5 made ``_total_inference_steps`` and ``estimate_wall_time_seconds`` take a
required Dataset Profile, three and a hundred-odd lines away respectively.

That combination is exactly what §2 forbids: an empirical median, measured
from V7 formal-success records and documented as a blunt constant awaiting a
wider calibration set, sitting in a file a genericization PR is editing. It
is CALIBRATION. It is not a task declaration, it does not move with the
dataset, and 05b must leave it alone.
"""

from __future__ import annotations

from agent.skills.inference_skill import estimator


def test_the_inference_vs_training_ratio_is_unchanged():
    """Hardcoded, never read back from the module it guards.

    ``assert estimator._INFERENCE_VS_TRAINING_RATIO == estimator.
    _INFERENCE_VS_TRAINING_RATIO`` would pass for any value; so would a
    comparison against anything else the module computes. 2.7 is the
    empirical median of the two-architecture calibration table recorded at
    ``estimator.py:60-79``, and it is written out here.
    """
    assert estimator._INFERENCE_VS_TRAINING_RATIO == 2.7


def test_the_ratio_still_scales_the_static_inference_formula():
    """Reachability, not decoration.

    A pinned constant that nothing multiplies by is a value, not a
    calibration: if a refactor stopped applying the ratio, the pin above
    would stay green while every inference forecast silently changed. This
    fails if the static formula stops depending on it.
    """
    args = (10**6, 16_000, 8)  # num_params, seg_size, inf_batch
    baseline = estimator._static_inference_ms_per_step(*args)
    assert baseline == 10**6 * 16_000 * 8 * estimator._STATIC_MS_PER_FLOP * 2.7
