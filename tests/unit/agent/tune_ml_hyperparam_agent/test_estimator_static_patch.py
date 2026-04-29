"""Unit tests for the static formula patch (Phase 6.8 Commit 11 §4.2).

Validates:
  - _STATIC_MS_PER_FLOP raised from 6e-10 to 3e-9 (5x)
  - _MIN_MS_PER_STEP floor at 2.0 ms
  - SAFETY_MULTIPLIER raised from 1.1 to 2.0
  - _static_ms_per_step applies the floor
"""
from __future__ import annotations

from agent.skills.training_skill.estimator import (
    SAFETY_MULTIPLIER,
    _MIN_MS_PER_STEP,
    _STATIC_MS_PER_FLOP,
    _static_ms_per_step,
)


def test_static_ms_per_flop_raised():
    assert _STATIC_MS_PER_FLOP == 3e-9


def test_safety_multiplier_raised():
    assert SAFETY_MULTIPLIER == 2.0


def test_min_ms_per_step_floor():
    assert _MIN_MS_PER_STEP == 2.0


def test_static_formula_applies_floor_for_tiny_model():
    """A tiny model (100 params, seg=100, bs=1) would compute
    100*100*1*3e-9 = 3e-5 ms — far below the 2.0 ms floor."""
    ms = _static_ms_per_step(num_params=100, seg_size=100, batch_size=1)
    assert ms == 2.0


def test_static_formula_above_floor_uses_computed():
    """A large model should exceed the floor and use the computed value."""
    ms = _static_ms_per_step(num_params=1_000_000, seg_size=2000, batch_size=8)
    computed = 1_000_000 * 2000 * 8 * 3e-9
    assert computed > 2.0
    assert ms == computed


def test_static_formula_5x_higher_than_old():
    """The new coefficient is exactly 5x the old one."""
    old_coeff = 6e-10
    assert _STATIC_MS_PER_FLOP / old_coeff == 5.0
