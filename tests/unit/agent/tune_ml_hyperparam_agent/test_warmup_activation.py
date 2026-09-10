"""Unit test: verify data_dir plumbing activates the warmup path (Phase 6.8 §4.2).

The warmup code lives in evaluate_time_skill.wrapper._measure_ms_per_step.
This test verifies that:
  1. When data_dir is None, the warmup is skipped (static formula used).
  2. When data_dir is a valid path, the warmup path is entered.
  3. The static formula fallback uses the patched constants.

We mock torch/CUDA to avoid needing real hardware.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from execute_tools.task_data_path import bind_task_data_path
from tests.helpers.two_family_profile import make_two_family_profile

_PROFILE = make_two_family_profile(
    num_files=3,
    psd_segment_length=1_600_000,
    segments_per_file=20,
)


def test_warmup_skipped_when_data_dir_is_none():
    """_measure_ms_per_step returns (None, ...) when data_dir is None."""
    from agent.skills.evaluate_time_skill.wrapper import _measure_ms_per_step

    ms, breakdown = _measure_ms_per_step(
        model_type="punet",
        model_config={"segmentation_size": 1000},
        train_config={"batch_size": 1, "epochs": 1},
        loss_config={},
        data_dir=None,
        sample_set={"0": list(range(100))},
        profile=_PROFILE,
    )
    assert ms is None
    assert breakdown["aggregator"] is None


def test_warmup_skipped_when_data_dir_is_empty_string():
    """Empty string should also skip warmup."""
    from agent.skills.evaluate_time_skill.wrapper import _measure_ms_per_step

    ms, _breakdown = _measure_ms_per_step(
        model_type="punet",
        model_config={"segmentation_size": 1000},
        train_config={"batch_size": 1, "epochs": 1},
        loss_config={},
        data_dir="",
        sample_set={"0": list(range(100))},
        profile=_PROFILE,
    )
    assert ms is None


def test_warmup_skipped_when_data_dir_does_not_exist():
    """Non-existent data_dir should skip warmup."""
    from agent.skills.evaluate_time_skill.wrapper import _measure_ms_per_step

    ms, _breakdown = _measure_ms_per_step(
        model_type="punet",
        model_config={"segmentation_size": 1000},
        train_config={"batch_size": 1, "epochs": 1},
        loss_config={},
        data_dir="/nonexistent/path/that/does/not/exist",
        sample_set={"0": list(range(100))},
        profile=_PROFILE,
    )
    assert ms is None


def test_static_formula_uses_patched_constants():
    """estimate_wall_time_seconds with ms_per_step=None uses the 3e-9 coefficient
    and the SAFETY_MULTIPLIER currently in force. Phase 6.8 raised the
    multiplier from 1.1 to 2.0; it was subsequently relaxed to 1.3 once
    novel-arch overshoot data showed 2.0 was over-conservative."""
    from agent.skills.training_skill.estimator import (
        _STATIC_MS_PER_FLOP,
        SAFETY_MULTIPLIER,
        estimate_wall_time_seconds,
    )

    assert _STATIC_MS_PER_FLOP == 3e-9
    assert SAFETY_MULTIPLIER == 1.3

    num_params = 500_000
    seg = 1000
    bs = 4

    with patch(
        "agent.skills.training_skill.estimator._count_params",
        return_value=num_params,
    ):
        result = estimate_wall_time_seconds(
            model_type="punet",
            model_config={"segmentation_size": seg},
            train_config={"batch_size": bs, "epochs": 1},
            sample_set={"0": list(range(100))},
            ms_per_step=None,
            num_params=num_params,
            dataset_profile=_PROFILE,
        )

    bd = result["breakdown"]
    assert bd["ms_source"] == "static_uncalibrated"
    assert bd["safety_multiplier"] == 1.3
    # ms_per_step should be max(num_params * seg * bs * 3e-9, 2.0)
    expected_ms = max(num_params * seg * bs * 3e-9, 2.0)
    assert bd["ms_per_step"] == round(expected_ms, 4)


def test_warmup_path_entered_with_valid_data_dir(tmp_path, capsys):
    """With a real data_dir AND CUDA available, the entry guards must not
    fire -- control reaches the measurement block.

    This test used to assert only `assert ms is None`, which is what EVERY
    guard-rejection test in this file asserts: `_measure_ms_per_step`
    returns an identical `(None, empty_breakdown)` from every early return.
    Verified on 2026-08-02 by replacing the data_dir guard with `if True:`
    so the warmup could never be entered -- all five tests stayed green.

    The return value cannot distinguish the cases, but the emitted log can:
    each guard prints its own reason (`wrapper.py:309` no data_dir, `:317`
    CUDA not available) and a post-entry failure prints `[warmup failed]`
    (`:454`). Asserting on those is what makes entry observable without a
    production change.
    """
    mock_torch = MagicMock()
    mock_torch.cuda.is_available.return_value = True
    mock_torch.cuda.get_device_name.return_value = "Mock GPU"

    with patch.dict("sys.modules", {"torch": mock_torch}):
        from agent.skills.evaluate_time_skill.wrapper import _measure_ms_per_step

        ms, _breakdown = _measure_ms_per_step(
            model_type="punet",
            model_config={"segmentation_size": 1000},
            train_config={"batch_size": 1, "epochs": 1},
            loss_config={},
            data_dir=str(tmp_path),
            sample_set={"0": list(range(100))},
            profile=_PROFILE,
            task_scope=object(),
        )

    out = capsys.readouterr().out

    # The two ENTRY guards, each with its own reason string.
    assert "no data_dir" not in out, "the data_dir guard rejected a valid directory"
    assert "CUDA not available" not in out, "the CUDA guard rejected an available device"

    # Something only reachable AFTER both guards. Which one fires depends on
    # how far the environment gets (no HDF5 files here, so dataset
    # construction is the usual stop); asserting any of them proves entry
    # without pinning this test to one environment's failure mode. Note the
    # post-entry messages also say "[warmup skipped]", so the absence of that
    # phrase cannot be the signal.
    post_entry = ("mini dataset too small", "unknown model_type", "[warmup failed]")
    assert any(marker in out for marker in post_entry), (
        "control never reached the measurement block -- it was turned away by "
        f"an entry guard. Emitted: {out[-400:]!r}"
    )

    # Without a real dataset the measurement cannot complete; the point of
    # this test is WHERE it stopped, not that it produced a number.
    assert ms is None


def test_composed_warmup_materializes_the_task_owned_scope(monkeypatch, tmp_path):
    """Catch the external composed-scope identity failure from issue #392."""
    import torch

    from agent.skills.evaluate_time_skill.wrapper import _measure_ms_per_step

    external_scope = object()
    observed = []

    class ExternalDataPath:
        task_data_path_id = "external_warmup_test"

        def training_dataset(self, scope, params):
            observed.append((scope, params.max_samples))
            return [(torch.tensor([0]), torch.tensor([0]))]

    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    with bind_task_data_path(ExternalDataPath()):
        measured, _breakdown = _measure_ms_per_step(
            model_type="unregistered_warmup_model",
            model_config={"segmentation_size": 1000},
            train_config={"batch_size": 1, "epochs": 1},
            loss_config={},
            data_dir=str(tmp_path),
            sample_set={"0": [0]},
            profile=_PROFILE,
            task_scope=external_scope,
            n_warmup_batches=0,
            n_timed_batches=1,
        )

    assert measured is None
    assert observed == [(external_scope, 1)]
