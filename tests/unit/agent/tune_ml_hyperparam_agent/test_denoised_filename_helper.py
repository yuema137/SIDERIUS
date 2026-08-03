"""Unit tests for _build_denoised_filename (Bug A fix, PR #101 Gate 2).

The helper was introduced to make the denoised-HDF5 filename construction
unit-testable in isolation from the tuner's per-round loop. Prior to the
fix, the inline closure returned a bare filename with no directory
prefix; downstream consumers that used the string verbatim (HealthGate
context per execute_tools/health_checks/_peek.py:20-24 path contract)
then failed to open the file at CWD.

These tests would have caught the missing-directory bug.
"""

from __future__ import annotations

import os

from nodes.ml_hyperparameter_tune_agent.ml_hyperparameter_tune_agent import (
    _build_denoised_filename,
)


def test_returned_path_is_absolute():
    """The core Bug A assertion — a caller can open the returned path
    directly without needing to know a base directory.
    """
    path = _build_denoised_filename(
        model_type="wavenet",
        run_name="iter_001",
        exp_id="wavenet_iter_001_002",
        file_index=0,
        base_dir="/tmp/checkpoint_workspace",
    )
    assert os.path.isabs(path), (
        f"denoised filename must be an absolute path (Bug A: peek helper "
        f"opens the string verbatim at CWD if not absolute). Got: {path!r}"
    )


def test_returned_path_starts_with_base_dir():
    """The returned path is composed under the sandbox output dir the
    caller supplies — no other implicit resolution.
    """
    base_dir = "/tmp/checkpoint_workspace"
    path = _build_denoised_filename(
        model_type="wavenet",
        run_name="iter_001",
        exp_id="wavenet_iter_001_002",
        file_index=0,
        base_dir=base_dir,
    )
    assert path.startswith(base_dir + os.sep), (
        f"path must start with base_dir + sep. base_dir={base_dir!r} path={path!r}"
    )


def test_filename_component_encodes_all_identifiers():
    """The filename portion still contains every identifier the writer
    (execute_tools/inference_single.py:311-313) uses, so writer and reader
    agree on the filename.
    """
    path = _build_denoised_filename(
        model_type="wavenet",
        run_name="iter_001",
        exp_id="wavenet_iter_001_002",
        file_index=7,
        base_dir="/tmp/checkpoint_workspace",
    )
    fname = os.path.basename(path)
    assert fname.startswith("abra_validation_denoised_")
    assert "wavenet" in fname
    assert "iter_001" in fname
    assert "wavenet_iter_001_002" in fname
    assert fname.endswith("_0007.h5"), f"file_index must be 4-digit zero-padded; got {fname}"


def test_file_index_zero_padded_to_four_digits():
    """The file_index component must be exactly 4 digits so it round-trips
    with the writer's format string. Regression guard.
    """
    path_0 = _build_denoised_filename(
        model_type="wavenet",
        run_name="r",
        exp_id="e",
        file_index=0,
        base_dir="/tmp",
    )
    path_19 = _build_denoised_filename(
        model_type="wavenet",
        run_name="r",
        exp_id="e",
        file_index=19,
        base_dir="/tmp",
    )
    assert os.path.basename(path_0).endswith("_0000.h5")
    assert os.path.basename(path_19).endswith("_0019.h5")


# NOTE: a `test_absolute_path_is_safe_for_downstream_join` case was removed on
# 2026-08-02. It asserted that os.path.join(base, <absolute>) discards the
# base -- a documented property of the standard library, not of
# `_build_denoised_filename`. Given the test above pinning that the returned
# path starts with base_dir, no edit to production could fail it without
# already failing that one.
