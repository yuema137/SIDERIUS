"""Shared HDF5-peek primitives — choose_peek_file_index + peek_int8_at_path.

Covers the two functions in ``execute_tools/health_checks/_peek.py``:
    * ``choose_peek_file_index(ctx)`` — file_index selection (AMB-4-5 → A)
    * ``peek_int8_at_path(path, peek_samples)`` — pure HDF5 read;
      raises OSError / KeyError on failure so the caller can construct
      an informative failure result.

See ``docs/design/pluggable_health_checks.md`` §9 for the peek design.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import ClassVar

import h5py
import numpy as np
import pytest

from execute_tools.dataset_config import resolve_dataset_profile, tidmad_topology
from execute_tools.deliverable_spec import default_deliverable_storage
from execute_tools.health_checks._peek import (
    choose_peek_file_index,
    peek_int8_at_channel,
    peek_int8_at_path,
)
from execute_tools.health_checks.schemas import HealthCheckContext
from tests.helpers.two_family_profile import write_bound_timeseries


def _write_denoised_h5(path, ch1: np.ndarray) -> None:
    """Write a minimal deliverable using the bound output-channel name."""
    channel = tidmad_topology(resolve_dataset_profile()).channels.input_channel
    with h5py.File(str(path), "w") as f:
        ts = f.create_group("timeseries")
        c1 = ts.create_group(channel)
        c1.create_dataset("timeseries", data=ch1, chunks=True)


def _write_two_channel_h5(path, ch1: np.ndarray, ch2: np.ndarray) -> None:
    """Write an HDF5 with both channel0001 and channel0002 populated —
    matches the shape of ground-truth validation files used for pearson."""
    with h5py.File(str(path), "w") as f:
        ts = f.create_group("timeseries")
        c1 = ts.create_group("channel0001")
        c1.create_dataset("timeseries", data=ch1, chunks=True)
        c2 = ts.create_group("channel0002")
        c2.create_dataset("timeseries", data=ch2, chunks=True)


def _ctx(**overrides) -> HealthCheckContext:
    base = {"model_name": "m", "run_name": "r", "round_index": 1}
    base.update(overrides)
    return HealthCheckContext(**base)


# ---------------------------------------------------------------------------
# choose_peek_file_index
# ---------------------------------------------------------------------------


class TestChoosePeekFileIndex:
    def test_defaults_to_zero_when_paths_empty(self):
        assert choose_peek_file_index(_ctx()) == 0

    def test_min_key_when_paths_non_empty(self):
        ctx = _ctx(denoised_paths={7: "a.h5", 3: "b.h5", 5: "c.h5"})
        assert choose_peek_file_index(ctx) == 3

    def test_zero_key_wins_when_present(self):
        ctx = _ctx(denoised_paths={0: "a.h5", 5: "b.h5"})
        assert choose_peek_file_index(ctx) == 0


# ---------------------------------------------------------------------------
# peek_int8_at_path
# ---------------------------------------------------------------------------


class TestPeekInt8AtPath:
    def test_returns_int8_samples_for_valid_hdf5(self, tmp_path):
        p = tmp_path / "d.h5"
        _write_denoised_h5(p, np.arange(-10, 10, dtype=np.int8).repeat(100))
        samples = peek_int8_at_path(str(p), peek_samples=500)
        assert samples.dtype == np.int8
        assert samples.shape[0] == 500

    def test_bounded_by_dataset_size(self, tmp_path):
        """Request more than the dataset holds — get the dataset."""
        p = tmp_path / "d.h5"
        _write_denoised_h5(p, np.zeros(100, dtype=np.int8))
        samples = peek_int8_at_path(str(p), peek_samples=100_000)
        assert samples.shape[0] == 100

    def test_peek_zero_returns_empty(self, tmp_path):
        p = tmp_path / "d.h5"
        _write_denoised_h5(p, np.zeros(100, dtype=np.int8))
        samples = peek_int8_at_path(str(p), peek_samples=0)
        assert samples.shape[0] == 0

    def test_missing_file_raises_oserror(self, tmp_path):
        bogus = str(tmp_path / "does_not_exist.h5")
        with pytest.raises(OSError):
            peek_int8_at_path(bogus, peek_samples=100)

    def test_missing_dataset_raises_keyerror(self, tmp_path):
        """Valid HDF5 but ``timeseries/channel0001/timeseries`` walk fails."""
        p = tmp_path / "wrong_shape.h5"
        with h5py.File(str(p), "w") as f:
            f.create_group("wrong_group")
        with pytest.raises(KeyError):
            peek_int8_at_path(str(p), peek_samples=100)

    def test_partial_dataset_structure_raises_keyerror(self, tmp_path):
        """Second step of the walk fails (top-level ``timeseries`` exists
        but ``channel0001`` under it does not)."""
        p = tmp_path / "partial.h5"
        with h5py.File(str(p), "w") as f:
            f.create_group("timeseries")  # missing channel0001 subgroup
        with pytest.raises(KeyError):
            peek_int8_at_path(str(p), peek_samples=100)


# ---------------------------------------------------------------------------
# peek_int8_at_channel — generalised primitive (M8 §3.4)
# ---------------------------------------------------------------------------


class TestPeekInt8AtChannel:
    def test_reads_bound_output_channel_matching_wrapper(self, tmp_path):
        p = tmp_path / "d.h5"
        ch1 = np.arange(-5, 5, dtype=np.int8).repeat(50)
        write_bound_timeseries(p, ch1, np.zeros(500, dtype=np.int8))
        channel = tidmad_topology(resolve_dataset_profile()).channels.input_channel
        s = peek_int8_at_channel(str(p), channel, peek_samples=500)
        wrapped = peek_int8_at_path(str(p), peek_samples=500)
        np.testing.assert_array_equal(s, wrapped)

    def test_reads_channel0002_distinct_data(self, tmp_path):
        p = tmp_path / "d.h5"
        ch1 = np.full(500, 1, dtype=np.int8)
        ch2 = np.full(500, -50, dtype=np.int8)
        _write_two_channel_h5(p, ch1=ch1, ch2=ch2)
        s = peek_int8_at_channel(str(p), "channel0002", peek_samples=500)
        assert s.dtype == np.int8
        assert s.shape[0] == 500
        assert int(s[0]) == -50
        assert int(s[-1]) == -50

    def test_missing_channel_key_raises_keyerror(self, tmp_path):
        p = tmp_path / "only_ch1.h5"
        _write_denoised_h5(p, np.zeros(100, dtype=np.int8))
        with pytest.raises(KeyError):
            peek_int8_at_channel(str(p), "channel0002", peek_samples=100)

    def test_peek_zero_returns_empty(self, tmp_path):
        p = tmp_path / "d.h5"
        _write_two_channel_h5(p, np.zeros(100, dtype=np.int8), np.zeros(100, dtype=np.int8))
        s = peek_int8_at_channel(str(p), "channel0002", peek_samples=0)
        assert s.shape[0] == 0

    def test_missing_file_raises_oserror(self, tmp_path):
        bogus = str(tmp_path / "does_not_exist.h5")
        with pytest.raises(OSError):
            peek_int8_at_channel(bogus, "channel0001", peek_samples=100)


# ---------------------------------------------------------------------------
# Step 08a C5 — reads route through the Deliverable Contract, byte-identically
# ---------------------------------------------------------------------------


def _known_stream(n: int, seed: int) -> np.ndarray:
    """A deterministic int8 stream whose bytes we can predict independently."""
    rng = np.random.default_rng(seed)
    return rng.integers(-128, 127, size=n, dtype=np.int8)


def _write_two_channel_file(path, ch1: np.ndarray, ch2: np.ndarray) -> None:
    write_bound_timeseries(path, ch1, ch2)


# Hashes of the first 4096 samples of each seeded stream, computed from the
# GENERATOR — not captured from the peek. An oracle that the implementation
# did not author: if C5's re-plumbing changed which bytes are read, or how
# many, or from which channel, these fail.
_CH1_SHA = hashlib.sha256(_known_stream(10_000, seed=11)[:4096].tobytes()).hexdigest()
_CH2_SHA = hashlib.sha256(_known_stream(10_000, seed=22)[:4096].tobytes()).hexdigest()


class TestContractRoutedPeekReadsTheSameBytes:
    """C5 moves WHERE the channel names come from, not WHAT is read.

    The risk C5 carries is disjoint from verdict semantics: a re-plumbed
    read could silently swap channels, truncate, or change dtype, and every
    verdict test would still pass because the numbers would merely be
    different-but-plausible. These assertions are on the bytes.
    """

    def test_channel_reads_are_byte_identical_to_the_independent_oracle(self, tmp_path):
        path = tmp_path / "two_channel.h5"
        _write_two_channel_file(path, _known_stream(10_000, 11), _known_stream(10_000, 22))
        channels = tidmad_topology(resolve_dataset_profile()).channels

        ch1 = peek_int8_at_channel(str(path), channels.input_channel, 4096)
        ch2 = peek_int8_at_channel(str(path), channels.target_channel, 4096)

        assert ch1.dtype == np.int8 and ch2.dtype == np.int8
        assert ch1.shape == (4096,) and ch2.shape == (4096,)
        assert hashlib.sha256(ch1.tobytes()).hexdigest() == _CH1_SHA
        assert hashlib.sha256(ch2.tobytes()).hexdigest() == _CH2_SHA
        assert np.array_equal(ch1, _known_stream(10_000, 11)[:4096])
        assert np.array_equal(ch2, _known_stream(10_000, 22)[:4096])

    def test_the_two_channels_are_actually_distinguishable(self, tmp_path):
        """Guards the guard: identical channels would make a swap invisible."""
        assert _CH1_SHA != _CH2_SHA

    def test_deliverable_contract_channel_names_match_the_bound_profile(self):
        """The storage adapter must project the active declaration."""
        storage = default_deliverable_storage()
        channels = tidmad_topology(resolve_dataset_profile()).channels
        assert storage.input_channel_group == channels.input_channel
        assert storage.target_channel_group == channels.target_channel
        assert storage.storage_dtype == "int8"

    def test_contract_resolved_name_reads_the_declared_output_bytes(self, tmp_path):
        """The contract-routed wrapper reads the independently seeded output."""
        path = tmp_path / "two_channel.h5"
        _write_two_channel_file(path, _known_stream(10_000, 11), _known_stream(10_000, 22))
        storage = default_deliverable_storage()

        by_contract = peek_int8_at_channel(str(path), storage.input_channel_group, 4096)
        assert np.array_equal(by_contract, _known_stream(10_000, 11)[:4096])
        assert hashlib.sha256(by_contract.tobytes()).hexdigest() == _CH1_SHA


class TestNoChannelLiteralsSurviveInHealthCode:
    """C5's structural claim: the channel identity has ONE owner.

    A literal that agrees with the contract today is exactly the hazard —
    it keeps agreeing until a task binds different channel groups, at which
    point the peek reads the wrong group and every verdict is computed from
    the wrong signal while looking entirely healthy.

    The persisted record label ``sampling_method`` is whitelisted. That is a
    recorded VALUE in historical artifacts, not a lookup — changing it would
    rewrite what old records claim about themselves, which 08a explicitly
    does not do.

    **Step 10 / P4 narrowed the exemption rather than widening it.** The label
    moved from a single central literal in ``evaluation.py`` onto each check's
    ``sampling_method_label`` declaration (each check states how IT sampled),
    so the exemption now has to reach the check modules. Instead of exempting
    those files, it is exempted by SYNTACTIC POSITION: the literal is legal
    only on a ``sampling_method_label=`` declaration line. Anywhere else in
    the same file — in particular any use as a lookup key — is still an
    offender, which is a stricter rule than the file-level whitelist it
    replaces.
    """

    PRODUCTION_FILES = (
        "_peek.py",
        "_multi_file_peek.py",
        "output_diversity.py",
        "output_std.py",
        "amplitude_collapse.py",
        "per_file_output_std.py",
        "spectral_peak_ratio.py",
        "pearson_dispersion.py",
    )
    #: The check modules that declare the persisted label. Step 10 / P4 (C2)
    #: moved it here from a single central literal in ``evaluation.py`` — each
    #: check now states how IT sampled — so the anchor moved with it.
    LABEL_DECLARED_BY: ClassVar[frozenset[str]] = frozenset(
        {
            "output_diversity.py",
            "output_std.py",
            "amplitude_collapse.py",
            "per_file_output_std.py",
            "spectral_peak_ratio.py",
            "pearson_dispersion.py",
        }
    )

    @staticmethod
    def _health_checks_dir() -> Path:
        return Path(__file__).resolve().parents[4] / "execute_tools" / "health_checks"

    #: The ONE syntactic position where the persisted label may appear.
    LABEL_DECLARATION: ClassVar[str] = "sampling_method_label="

    def test_the_peek_path_names_no_channel(self):
        offenders: list[str] = []
        for name in self.PRODUCTION_FILES:
            for lineno, line in enumerate(
                (self._health_checks_dir() / name).read_text().splitlines(), start=1
            ):
                if "channel0001" not in line and "channel0002" not in line:
                    continue
                if line.strip().startswith(self.LABEL_DECLARATION):
                    continue  # persisted record label, declared by its owner
                offenders.append(f"{name}:{lineno}: {line.strip()}")
        assert not offenders, "channel literals survive in the peek path:\n  " + "\n  ".join(
            offenders
        )

    def test_the_label_exemption_does_not_cover_a_lookup(self):
        """Anti-widening: the exemption is positional, not per-file.

        A channel literal used as a LOOKUP inside an exempted check module is
        still an offender — that is the hazard the class exists to catch, and
        moving the label must not have bought an amnesty for it.
        """
        legal = '        sampling_method_label="channel0001_prefix_peek",'
        illegal = '        data = f["timeseries"]["channel0001"]'
        assert legal.strip().startswith(self.LABEL_DECLARATION)
        assert not illegal.strip().startswith(self.LABEL_DECLARATION)
        assert "channel0001" in illegal

    def test_the_exempted_label_is_real_and_the_scanner_can_see_it(self):
        """Guards the exemption: if the label vanished, it is stale.

        It also proves this scanner finds literals at all — without it, a
        broken reader would make the test above pass vacuously. Step 10 / P4
        moved the anchor from ``evaluation.py`` to the checks that declare the
        label; both properties are unchanged, and the exemption now has to
        describe something real in SIX files rather than one.
        """
        for name in sorted(self.LABEL_DECLARED_BY):
            source = (self._health_checks_dir() / name).read_text()
            assert f'{self.LABEL_DECLARATION}"channel0001_prefix_peek"' in source, name
            assert name in self.PRODUCTION_FILES, name

    def test_the_central_literal_is_gone_from_the_persistence_adapter(self):
        """Step 10 / P4 (C2): one TIDMAD-shaped label applied to EVERY check's
        rows is exactly the per-check-name coupling this child removes, and
        `evaluation.py` joining the generic census partition depends on it."""
        source = (self._health_checks_dir() / "evaluation.py").read_text()
        assert "channel0001" not in source
        assert "channel0002" not in source


pytestmark = pytest.mark.usefixtures("synthetic_dataset_profile")
