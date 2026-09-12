"""Argparse-level segment-integrity floor (Phase 1.5 Commit 4.1).

The Pydantic schemas ``ProposalInput.trial_portion`` and
``HyperparamTuningInput.{trial,eval}_portion`` all carry ``ge=0.01``.
That floor reflects the **statistical requirement** that a trial-mode
chain see at least two segments per file (``SEGMENTS_PER_FILE=200``;
``round(0.01 * 200) = 2``). Below 0.01 the sampler collapses to one
segment per file via the ``max(1, ...)`` floor in
``execute_tools.sample_set_builder`` — physically valid but too noisy
to discriminate architectures.

Until Phase 1.5 the runner accepted any ``float``, so a sub-0.01 value
spent tokens on Interpretation before crashing inside the Proposer's
Pydantic validator. The ``_portion_floor`` validator in
``src/workflows/run_one_iteration.py`` fails fast at argparse
time — see Phase 1.5 §1.5 of
``docs/audit_and_optimize_token_usage_and_growth.md``.

Pre-4.3.4 these tests parametrized over both the legacy in-process
runner and the chain runner. The legacy runner was retired in Commit
4.3.4; the surviving validator lives only on the chain runner.
"""

from __future__ import annotations

import argparse

import pytest

from workflows.run_one_iteration import (
    _portion_floor as roi_floor,
)
from workflows.run_one_iteration import (
    build_parser,
)


def test_floor_accepts_exactly_one_pct():
    """0.01 is the documented minimum and must be accepted."""
    assert roi_floor("0.01") == 0.01


def test_floor_accepts_typical_values():
    for s, expected in [("0.05", 0.05), ("0.1", 0.1), ("1.0", 1.0)]:
        assert roi_floor(s) == expected


def test_floor_rejects_just_below():
    """0.005 is the value that crashed the live T1 run on 2026-05-04."""
    with pytest.raises(argparse.ArgumentTypeError) as exc:
        roi_floor("0.005")
    msg = str(exc.value)
    assert "0.01" in msg
    # The message must explain *why*, so future operators don't think it's
    # an arbitrary floor — segment-integrity is the load-bearing reason.
    assert "segment" in msg.lower() or "sample_set_builder" in msg


def test_floor_rejects_zero_and_negative():
    for bad in ["0", "0.0", "-0.5"]:
        with pytest.raises(argparse.ArgumentTypeError):
            roi_floor(bad)


def test_floor_rejects_above_one():
    with pytest.raises(argparse.ArgumentTypeError):
        roi_floor("1.5")


def test_floor_rejects_non_numeric():
    with pytest.raises(argparse.ArgumentTypeError):
        roi_floor("abc")


def test_validator_name_is_portion_floor():
    """The chain-consistency suite (test_chain_consistency.py) compares
    ``type.__name__`` for argparse type-validators across layers — the
    chain runner must expose this helper as ``_portion_floor``."""
    assert roi_floor.__name__ == "_portion_floor"


def test_roi_argparse_rejects_subfloor_trial_portion():
    """End-to-end: argparse on the chain runner aborts before workflow start."""
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(
            [
                "--workspace",
                "/tmp/dummy_ws",
                "--seed_paths",
                "/tmp/dummy.json",
                "--start_iteration",
                "1",
                "--trial_portion",
                "0.005",
            ]
        )
    # argparse error → exit code 2 (Python's argparse default).
    assert exc.value.code == 2


def test_roi_argparse_rejects_subfloor_eval_portion():
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(
            [
                "--workspace",
                "/tmp/dummy_ws",
                "--seed_paths",
                "/tmp/dummy.json",
                "--start_iteration",
                "1",
                "--eval_portion",
                "0.005",
            ]
        )
    assert exc.value.code == 2
