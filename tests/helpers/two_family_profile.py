"""Synthetic two-family physical profile for trainer tests.

A small Dataset Profile with both training and validation file families.
Their payloads are distinct, so an R3 observed on the validation family cannot
coincide with an R2 observed on the training family by accident.

This is a framework fixture, not a scientific task: its neutral filenames,
channels, geometry, and values exist only to exercise the legacy indexed-file
execution contract while that contract remains supported.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import h5py
import numpy as np

from execute_tools.dataset_config import (
    ChannelIdentity,
    DatasetConfig,
    DatasetProfile,
    ValueEncoding,
    tidmad_topology,
)

DEFAULT_SEG_SIZE = 1000


def _base_profile() -> DatasetProfile:
    dataset = DatasetConfig(
        psd_segment_length=2000,
        segments_per_file=4,
        num_files=3,
        sampling_frequency=1000.0,
        training_file_pattern="training_{file_index:04d}.h5",
        validation_file_pattern="validation_{file_index:04d}.h5",
    )
    channels = ChannelIdentity(input_channel="input", target_channel="target")
    encoding = ValueEncoding(
        storage_dtype="int8",
        compute_dtype="int16",
        value_offset=128,
        num_classes=256,
    )
    return DatasetProfile(
        partition_count=dataset.num_files,
        topology={
            "dataset": dataset.model_dump(),
            "channels": channels.model_dump(),
            "encoding": encoding.model_dump(),
        },
        anchor_selection_files=[0, 1, 2],
        health_peek_files=[0, 1, 2],
    )


@dataclass(frozen=True)
class TwoFamilyFixture:
    """The written fixture: where it lives and how it is declared."""

    data_dir: str
    profile: DatasetProfile
    seg_size: int
    num_files: int
    segments_per_file: int
    ml_segs_per_psd: int
    written: dict[str, list[str]] = field(default_factory=dict)

    def full_sample_set(self) -> dict[str, list[int]]:
        """Every declared PSD segment of every declared file (string keys,
        the JSON-transport form the trainer receives)."""
        return {str(i): list(range(self.segments_per_file)) for i in range(self.num_files)}

    def training_path(self, file_index: int) -> str:
        return os.path.join(
            self.data_dir, tidmad_topology(self.profile).dataset.training_file_name(file_index)
        )

    def validation_path(self, file_index: int) -> str:
        return os.path.join(
            self.data_dir, tidmad_topology(self.profile).dataset.validation_file_name(file_index)
        )


def make_two_family_profile(
    *,
    num_files: int = 3,
    psd_segment_length: int = 2000,
    segments_per_file: int = 4,
) -> DatasetProfile:
    """Build a neutral two-family profile with varied count and geometry.

    Built through ``model_validate`` (not ``model_copy``) so the result is
    exactly what the subprocess boundary reloads from JSON — a profile that
    only validates in-process would let a rung pass while the real child
    refuses it. The task-owned file sets (anchor / peek) are re-declared
    inside the smaller index space, as any bound task with ``num_files``
    files would declare them.
    """
    payload = _base_profile().to_wire()
    payload["dataset"].update(
        {
            "psd_segment_length": psd_segment_length,
            "segments_per_file": segments_per_file,
            "num_files": num_files,
        }
    )
    payload["anchor_selection_files"] = list(range(min(num_files, 3)))
    payload["health_peek_files"] = list(range(min(num_files, 3)))
    return DatasetProfile.model_validate(payload)


def _write_file(path: str, profile: DatasetProfile, n_samples: int, seed: int) -> None:
    ch, enc = tidmad_topology(profile).channels, tidmad_topology(profile).encoding
    rng = np.random.default_rng(seed)
    a = rng.integers(-128, 127, size=n_samples).astype(enc.storage_dtype)
    b = rng.integers(-128, 127, size=n_samples).astype(enc.storage_dtype)
    with h5py.File(path, "w") as f:
        ts = f.create_group("timeseries")
        ts.create_group(ch.input_channel).create_dataset("timeseries", data=a)
        ts.create_group(ch.target_channel).create_dataset("timeseries", data=b)


def write_two_family_fixture(
    tmp_path,
    *,
    num_files: int = 3,
    psd_segment_length: int = 2000,
    segments_per_file: int = 4,
    seg_size: int = DEFAULT_SEG_SIZE,
    families: tuple[str, ...] = ("training", "validation"),
) -> TwoFamilyFixture:
    """Write the fixture under ``tmp_path`` and return its description.

    Each family / file gets its own deterministic seed
    (``1000 * family_salt + file_index``), so payloads are distinct across
    families AND across files, and identical across test runs.
    """
    profile = make_two_family_profile(
        num_files=num_files,
        psd_segment_length=psd_segment_length,
        segments_per_file=segments_per_file,
    )
    data_dir = str(tmp_path)
    n_samples = psd_segment_length * segments_per_file
    written: dict[str, list[str]] = {}
    for family in families:
        salt = 1 if family == "training" else 2
        names: list[str] = []
        for i in range(num_files):
            name = (
                tidmad_topology(profile).dataset.training_file_name(i)
                if family == "training"
                else tidmad_topology(profile).dataset.validation_file_name(i)
            )
            _write_file(os.path.join(data_dir, name), profile, n_samples, 1000 * salt + i)
            names.append(name)
        written[family] = names
    return TwoFamilyFixture(
        data_dir=data_dir,
        profile=profile,
        seg_size=seg_size,
        num_files=num_files,
        segments_per_file=segments_per_file,
        ml_segs_per_psd=psd_segment_length // seg_size,
        written=written,
    )
