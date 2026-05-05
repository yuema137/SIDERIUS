"""Argparse-level segment-integrity floor (Phase 1.5 Commit 4.1).

The Pydantic schemas ``ProposalInput.trial_portion`` and
``HyperparamTuningInput.{trial,eval}_portion`` all carry ``ge=0.01``.
That floor reflects the **statistical requirement** that a trial-mode
chain see at least two segments per file (``SEGMENTS_PER_FILE=200``;
``round(0.01 * 200) = 2``). Below 0.01 the sampler collapses to one
segment per file via the ``max(1, ...)`` floor in
``execute_tools.sample_set_builder`` — physically valid but too noisy
to discriminate architectures.

Until Phase 1.5 the runners accepted any ``float``, so a sub-0.01 value
spent tokens on Interpretation before crashing inside the Proposer's
Pydantic validator. The ``_portion_floor`` validator added in
``run_exploration_adaptive.py`` and ``sdsc_submission_scripts/run_one_iteration.py``
fails fast at argparse time — see Phase 1.5 §1.5 of
``docs/audit_and_optimize_token_usage_and_growth.md``.
"""
from __future__ import annotations

import argparse

import pytest

from run_exploration_adaptive import _portion_floor as adaptive_floor
from sdsc_submission_scripts.run_one_iteration import (
    _portion_floor as roi_floor,
)


VALIDATORS = pytest.mark.parametrize(
    "validator",
    [adaptive_floor, roi_floor],
    ids=["adaptive", "roi"],
)


@VALIDATORS
def test_floor_accepts_exactly_one_pct(validator):
    """0.01 is the documented minimum and must be accepted."""
    assert validator("0.01") == 0.01


@VALIDATORS
def test_floor_accepts_typical_values(validator):
    for s, expected in [("0.05", 0.05), ("0.1", 0.1), ("1.0", 1.0)]:
        assert validator(s) == expected


@VALIDATORS
def test_floor_rejects_just_below(validator):
    """0.005 is the value that crashed the live T1 run on 2026-05-04."""
    with pytest.raises(argparse.ArgumentTypeError) as exc:
        validator("0.005")
    msg = str(exc.value)
    assert "0.01" in msg
    # The message must explain *why*, so future operators don't think it's
    # an arbitrary floor — segment-integrity is the load-bearing reason.
    assert "segment" in msg.lower() or "sample_set_builder" in msg


@VALIDATORS
def test_floor_rejects_zero_and_negative(validator):
    for bad in ["0", "0.0", "-0.5"]:
        with pytest.raises(argparse.ArgumentTypeError):
            validator(bad)


@VALIDATORS
def test_floor_rejects_above_one(validator):
    with pytest.raises(argparse.ArgumentTypeError):
        validator("1.5")


@VALIDATORS
def test_floor_rejects_non_numeric(validator):
    with pytest.raises(argparse.ArgumentTypeError):
        validator("abc")


def test_both_validators_share_the_same_name():
    """The chain-consistency parity test compares ``type.__name__`` —
    both runners must expose ``_portion_floor`` so parity stays green."""
    assert adaptive_floor.__name__ == roi_floor.__name__ == "_portion_floor"


def test_adaptive_argparse_rejects_subfloor_trial_portion(tmp_path):
    """End-to-end: argparse on the real runner aborts before workflow start."""
    import importlib
    import sys
    import run_exploration_adaptive as mod
    importlib.reload(mod)

    saved = sys.argv
    try:
        sys.argv = [
            "run_exploration_adaptive.py",
            "--run_name", "dummy",
            "--trial_portion", "0.005",
        ]
        with pytest.raises(SystemExit) as exc:
            mod.parse_args()
        # argparse error → exit code 2 (Python's argparse default).
        assert exc.value.code == 2
    finally:
        sys.argv = saved


def test_adaptive_argparse_rejects_subfloor_eval_portion():
    import importlib
    import sys
    import run_exploration_adaptive as mod
    importlib.reload(mod)

    saved = sys.argv
    try:
        sys.argv = [
            "run_exploration_adaptive.py",
            "--run_name", "dummy",
            "--eval_portion", "0.005",
        ]
        with pytest.raises(SystemExit) as exc:
            mod.parse_args()
        assert exc.value.code == 2
    finally:
        sys.argv = saved
