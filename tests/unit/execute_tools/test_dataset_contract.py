"""Indexed-dataset contract tests (PR 2 commit A).

The genericity contract (``docs/design/genericity_contract.md``) says a
training loader resolves ``file_index -> readable path`` through
``DatasetConfig``, never through an inlined dataset-specific template. These
tests are the guardrail-3 evidence for that seam: without them the refactor
would be a rename, not a decoupling.

Two things are proven here:

1. the path a loader actually builds comes from the config's pattern (probed
   by swapping the pattern and observing the loader's own path), and
2. no dataset-specific filename literal survives in the training engine.

The loader still reads the module-level ``TIDMAD`` singleton — commit A moves
the *template* behind the config seam, not the *choice of dataset*, which
stays a later step in the genericity ladder.
"""

import random
import re
from pathlib import Path

import pytest

from execute_tools import train_engine_sandbox
from execute_tools.dataset_config import (
    TIDMAD,
    TIDMAD_PROFILE,
    DatasetConfig,
    DatasetProfile,
    bind_dataset_profile,
)


def _profile_with_pattern(pattern: str) -> DatasetProfile:
    """TIDMAD's profile declaring a different training-file pattern.

    UPGRADED at Step 12 / PR-12bc B2. These probes used to
    ``monkeypatch.setattr(TIDMAD, "training_file_pattern", ...)``, which
    worked only because ``TIDMAD_PROFILE.dataset`` WAS the ``TIDMAD``
    singleton — patching one patched the other. B2 makes the topology an
    opaque payload, so that aliasing is gone and a monkeypatch on the
    singleton would silently probe nothing. Declaring the pattern and BINDING
    the profile exercises the production resolution path instead, which is
    what the claim was always about.
    """
    wire = TIDMAD_PROFILE.to_wire()
    wire["dataset"]["training_file_pattern"] = pattern
    return DatasetProfile.model_validate(wire)


SYNTHETIC_PATTERN = "run_{file_index:02d}.hdf5"


@pytest.fixture
def second_dataset() -> DatasetConfig:
    """A minimal non-TIDMAD dataset: different pattern, file count, segments."""
    return DatasetConfig(
        psd_segment_length=1000,
        segments_per_file=4,
        num_files=3,
        sampling_frequency=50.0,
        training_file_pattern=SYNTHETIC_PATTERN,
        validation_file_pattern="val_{file_index:02d}.hdf5",
    )


# ---- the seam itself is config-driven ----


def test_second_dataset_resolves_its_own_filenames(second_dataset):
    """No TIDMAD literal is involved in resolving a second dataset's names."""
    names = [second_dataset.training_file_name(i) for i in range(second_dataset.num_files)]
    assert names == ["run_00.hdf5", "run_01.hdf5", "run_02.hdf5"]
    assert not any("abra" in name for name in names)


def test_tidmad_and_second_dataset_disagree(second_dataset):
    """Sanity: the two configs genuinely produce different paths for one index."""
    assert TIDMAD.training_file_name(1) != second_dataset.training_file_name(1)


# ---- the loader consumes the seam (not merely renamed) ----


def test_epoch_dataset_path_follows_the_configured_pattern(tmp_path, capsys):
    """Swap the pattern; the loader's own resolved path must follow it.

    Probed via the missing-file warning, which prints the exact path the
    loader built — no HDF5 fixture needed, and the skip path is unchanged
    behavior this commit must preserve.
    """
    with bind_dataset_profile(_profile_with_pattern(SYNTHETIC_PATTERN)):
        train_engine_sandbox.TIDMADEpochDataset(
            data_dir=str(tmp_path),
            sample_set={"1": [0]},
            seg_size=1000,
            rng=random.Random(0),
        )

    warning = capsys.readouterr().out
    assert "run_01.hdf5" in warning
    assert "abra_training_" not in warning


def test_sample_set_loader_path_follows_the_configured_pattern(tmp_path, capsys):
    """Same probe for TIDMADDataset's sample-set branch (the other loader)."""
    with bind_dataset_profile(_profile_with_pattern(SYNTHETIC_PATTERN)):
        train_engine_sandbox.TIDMADDataset(
            str(tmp_path),
            [],
            segmentation_size=1000,
            sample_set={"2": [0]},
        )

    warning = capsys.readouterr().out
    assert "run_02.hdf5" in warning
    assert "abra_training_" not in warning


def test_default_pattern_preserves_legacy_paths(tmp_path, capsys):
    """Default behavior is unchanged: the loader still resolves TIDMAD names."""
    train_engine_sandbox.TIDMADEpochDataset(
        data_dir=str(tmp_path),
        sample_set={"6": [0]},
        seg_size=1000,
        rng=random.Random(0),
    )
    assert "abra_training_0006.h5" in capsys.readouterr().out


# ---- no dataset-specific literal survives in the engine ----


def test_training_engine_has_no_inlined_training_filename_literal():
    """Anti-regression: re-inlining the template would silently re-couple the
    engine to TIDMAD and bypass the pattern validator."""
    source = Path(train_engine_sandbox.__file__).read_text()
    offenders = [
        line.strip()
        for line in source.splitlines()
        if re.search(r"abra_training_\{|f\"abra_training_", line)
    ]
    assert offenders == []
