"""PR-02a commit C1 — the missing extraction baselines, captured BEFORE C2.

Design:
``docs/design/generic_framework_upgrade/step_02_dataset_sample_topology/pr_02a_dataset_profile_injection.md``
§4 (compatibility contract), §5a (CP0), §5d (ordering), §5e (encoding),
§6.1 (this commit).

**Why capture-first.** 02a routes topology, geometry, encoding and channel
identity through a resolved Dataset Profile. Every surface it touches must
have an oracle that exists BEFORE the production diff — a baseline captured
afterwards pins the already-changed behaviour and proves nothing (the S1-E
precedent). This module has **zero production diff** by construction.

**What is NOT re-pinned here.** §4 lists six MISSING rows, but an audit of
the existing suite found the "ordering semantics" row is already largely
covered and re-asserting it would be decoration:

===========================================  ==========================================
§5d ordering surface                         already pinned by
===========================================  ==========================================
shuffle ENABLEMENT + exact DataLoader kwargs  ``test_ordering_engine.py``
                                              ``::test_default_shuffle_path_is_unchanged``
deterministic ``sampler=epoch_indices`` order ``::test_sequential_path_uses_a_sampler_and_keeps_the_step_count``
``order_strategy`` resolution                 ``::test_unknown_strategy_is_rejected``
``file_order`` permutation validation         ``::test_file_order_must_permute_the_sample_set``
step count across strategies                  ``::test_step_count_is_identical_across_strategies``
===========================================  ==========================================

The genuine gap in that row is that **no test asserts the visited sequence
itself** — the ordered ``(filename, row_idx)`` list real data produces. That
gap is closed below.

Per §5d the exact emitted order under ``shuffle=True`` is deliberately NOT
pinned: ``train_engine_sandbox.py:864-866`` passes no ``generator`` and no
seed, and the module never calls ``torch.manual_seed``, so that order is not
deterministic today. Pinning it would manufacture a new compatibility
promise and tempt an implementer into adding seeding — a behaviour change
02a must not make.

Mutation/reachability evidence is per §5g **failure class**, not per test.
"""

from __future__ import annotations

import random
from typing import ClassVar

import h5py
import numpy as np
import pytest
import torch

import execute_tools.scoring_utils as su
import execute_tools.train_engine_sandbox as tes
from execute_tools.dataset_config import TIDMAD

# Tiny geometry. PSD_SEGMENT_LENGTH is monkeypatched to PSD_LEN so one PSD
# segment is exactly ML_PER_PSD rows — the real 10,000,000 would need a
# 100 MB fixture to assert one row.
SEG_SIZE = 8
ML_PER_PSD = 2
PSD_LEN = SEG_SIZE * ML_PER_PSD
PSD_PER_FILE = 3
SAMPLES_PER_FILE = PSD_LEN * PSD_PER_FILE

FILE_A = 4
FILE_B = 6


def _channel_payload(file_index: int, channel: int) -> np.ndarray:
    """Deterministic, per-(file, channel) DISTINCT int8 content.

    Distinctness is the point: it is what makes a channel swap observable.
    If both channels held the same bytes, a loader reading channel0002 into
    the input slot would pass every assertion below.
    """
    base = np.arange(SAMPLES_PER_FILE, dtype=np.int64)
    mixed = (base * (7 * channel + 1) + 13 * file_index + 29 * channel) % 251
    return (mixed - 125).astype(np.int8)


@pytest.fixture
def tiny_dataset(tmp_path, monkeypatch):
    """Two training files under the shrunk PSD geometry.

    Returns ``(data_dir, {file_index: {channel: payload}})`` so every
    expectation below is computed from TEST-owned data, never read back out
    of the code under test.
    """
    monkeypatch.setattr(tes, "PSD_SEGMENT_LENGTH", PSD_LEN)

    payloads: dict[int, dict[int, np.ndarray]] = {}
    for file_index in (FILE_A, FILE_B):
        ch1 = _channel_payload(file_index, 1)
        ch2 = _channel_payload(file_index, 2)
        payloads[file_index] = {1: ch1, 2: ch2}
        with h5py.File(tmp_path / TIDMAD.training_file_name(file_index), "w") as f:
            ts = f.create_group("timeseries")
            ts.create_group("channel0001").create_dataset("timeseries", data=ch1)
            ts.create_group("channel0002").create_dataset("timeseries", data=ch2)
    return str(tmp_path), payloads


def _expected_rows(payload: np.ndarray, psd_indices: list[int]) -> np.ndarray:
    """The ML rows a loader must produce for ``psd_indices``, computed here."""
    chunks = [
        payload[p * PSD_LEN : (p + 1) * PSD_LEN].reshape(ML_PER_PSD, SEG_SIZE) for p in psd_indices
    ]
    return np.concatenate(chunks, axis=0)


# ---------------------------------------------------------------------------
# §4 row: VISITED SEQUENCE  +  STEP COUNT
# Failure class: ordering / step-count semantics silently change.
# ---------------------------------------------------------------------------


class TestVisitedSequenceAndStepCount:
    """``TIDMADDataset.train_events`` — the ordered list every step derives from.

    ``train_engine_sandbox.py:86`` sets ``self.size = len(self.train_events)``,
    so this sequence IS the step count. Nothing pinned it before 02a: a
    migration that changed file visit order, dropped a PSD segment, or
    reshaped a chunk differently would have gone unnoticed.
    """

    # Non-contiguous PSD indices on FILE_A so a loader that ignored the index
    # and read from offset 0 twice would be caught.
    SAMPLE_SET: ClassVar[dict[str, list[int]]] = {str(FILE_A): [0, 2], str(FILE_B): [1]}

    def test_train_events_is_the_exact_ordered_sequence(self, tiny_dataset):
        """The sequence, hardcoded — not its length, not a set."""
        data_dir, _ = tiny_dataset
        dataset = tes.TIDMADDataset(
            data_dir, [], segmentation_size=SEG_SIZE, sample_set=self.SAMPLE_SET
        )

        assert dataset.train_events == [
            ("abra_training_0004.h5", 0),
            ("abra_training_0004.h5", 1),
            ("abra_training_0004.h5", 2),
            ("abra_training_0004.h5", 3),
            ("abra_training_0006.h5", 0),
            ("abra_training_0006.h5", 1),
        ]

    def test_step_count_derives_from_the_sequence(self, tiny_dataset):
        """Hardcoded, so a change to either side of ``size = len(events)`` reds.

        Asserting ``size == len(train_events)`` would compare the code under
        test to itself and pass for any value.
        """
        data_dir, _ = tiny_dataset
        dataset = tes.TIDMADDataset(
            data_dir, [], segmentation_size=SEG_SIZE, sample_set=self.SAMPLE_SET
        )

        assert dataset.size == 6
        assert len(dataset) == 6
        # Steps/epoch at the engine's own drop_last=True contract.
        assert len(dataset) // 4 == 1
        assert len(dataset) // 2 == 3

    def test_files_are_visited_in_ascending_index_order(self, tiny_dataset):
        """``sorted(sample_set.items())`` at :158 — a dict-order regression
        would reorder training data without changing any count."""
        data_dir, _ = tiny_dataset
        dataset = tes.TIDMADDataset(
            data_dir,
            [],
            segmentation_size=SEG_SIZE,
            # Insertion order deliberately reversed against index order.
            sample_set={str(FILE_B): [0], str(FILE_A): [0]},
        )

        assert [name for name, _ in dataset.train_events] == [
            "abra_training_0004.h5",
            "abra_training_0004.h5",
            "abra_training_0006.h5",
            "abra_training_0006.h5",
        ]

    def test_a_missing_file_is_warned_and_skipped(self, tiny_dataset, capsys):
        """``:162-165`` warn-and-skip. 02a must preserve it, so it is pinned
        before the migration rather than rediscovered by a failing run."""
        data_dir, _ = tiny_dataset
        dataset = tes.TIDMADDataset(
            data_dir,
            [],
            segmentation_size=SEG_SIZE,
            sample_set={str(FILE_A): [0], "17": [0]},
        )

        assert "abra_training_0017.h5" in capsys.readouterr().out
        assert dataset.train_events == [
            ("abra_training_0004.h5", 0),
            ("abra_training_0004.h5", 1),
        ]


# ---------------------------------------------------------------------------
# §4 row: CHANNEL IDENTITY
# Failure class: encoding / channel authority disconnect.
# ---------------------------------------------------------------------------


class TestChannelIdentity:
    """channel0001 is the model INPUT, channel0002 is the TRUTH.

    ~15 production sites address these by hardcoded HDF5 path with no
    declaration (parent §1.6). 02a makes the pair a declared dataset fact,
    so the pre-migration binding is captured here — including its
    detectability, since a pin that cannot see a swap proves nothing.
    """

    SAMPLE_SET: ClassVar[dict[str, list[int]]] = {str(FILE_A): [0, 1]}

    def test_sample_set_loader_binds_input_to_ch1_and_target_to_ch2(self, tiny_dataset):
        data_dir, payloads = tiny_dataset
        dataset = tes.TIDMADDataset(
            data_dir, [], segmentation_size=SEG_SIZE, sample_set=self.SAMPLE_SET
        )
        fname = TIDMAD.training_file_name(FILE_A)

        np.testing.assert_array_equal(
            dataset.idict[fname], _expected_rows(payloads[FILE_A][1], [0, 1])
        )
        np.testing.assert_array_equal(
            dataset.tdict[fname], _expected_rows(payloads[FILE_A][2], [0, 1])
        )

    def test_epoch_loader_binds_input_to_ch1_and_target_to_ch2(self, tiny_dataset):
        """The OTHER production loader (``TIDMADEpochDataset``, built by
        ``run_experiment_streaming`` at :837) reads the same two channels in
        its own code. Both must be pinned or C3 could migrate one and leave
        the other addressing the raw literal."""
        data_dir, payloads = tiny_dataset
        dataset = tes.TIDMADEpochDataset(
            data_dir=data_dir,
            sample_set={str(FILE_A): [0, 1]},
            seg_size=SEG_SIZE,
            rng=random.Random(0),
        )

        np.testing.assert_array_equal(dataset.inputs, _expected_rows(payloads[FILE_A][1], [0, 1]))
        np.testing.assert_array_equal(dataset.targets, _expected_rows(payloads[FILE_A][2], [0, 1]))

    def test_the_two_channels_are_distinguishable(self, tiny_dataset):
        """Reachability of the two pins above: if the fixture's channels were
        equal, a loader reading ch2 into the input slot would satisfy them."""
        _, payloads = tiny_dataset
        assert not np.array_equal(payloads[FILE_A][1], payloads[FILE_A][2])


# ---------------------------------------------------------------------------
# §4 row: ENCODING
# Failure class: encoding / channel authority disconnect.
# ---------------------------------------------------------------------------


class TestEncodingDeclaration:
    """int8 → int16 + 128, and the 256-class bincount.

    §5e scopes the claim narrowly: 02a proves the declaration is LIVE and
    that TIDMAD reproduces byte-identical tensors. It claims nothing about
    arbitrary dtypes — Step 03 owns model-I/O derivation.
    """

    SAMPLE_SET: ClassVar[dict[str, list[int]]] = {str(FILE_A): [0]}

    def test_served_tensors_are_int16_shifted_by_128(self, tiny_dataset):
        """``__getitem__`` at :95 — the offset that maps int8 onto [0, 256)."""
        data_dir, payloads = tiny_dataset
        dataset = tes.TIDMADDataset(
            data_dir, [], segmentation_size=SEG_SIZE, sample_set=self.SAMPLE_SET
        )

        served_input, served_target = dataset[0]
        expected_in = _expected_rows(payloads[FILE_A][1], [0])[0].astype(np.int16) + 128
        expected_tg = _expected_rows(payloads[FILE_A][2], [0])[0].astype(np.int16) + 128

        np.testing.assert_array_equal(served_input, expected_in)
        np.testing.assert_array_equal(served_target, expected_tg)
        assert served_input.dtype == np.int16
        assert served_target.dtype == np.int16
        # The offset lands every int8 value inside the class alphabet.
        assert served_input.min() >= 0
        assert served_input.max() < 256

    def test_class_count_is_a_256_bin_histogram_over_shifted_targets(self, tiny_dataset):
        """``:195-197`` — ``minlength=256`` and the ``torch.ones(256)`` prior.

        ``get_class_weight`` divides by this vector, so a shifted or
        wrong-length histogram silently reweights the loss.
        """
        data_dir, payloads = tiny_dataset
        dataset = tes.TIDMADDataset(
            data_dir, [], segmentation_size=SEG_SIZE, sample_set=self.SAMPLE_SET
        )

        targets = _expected_rows(payloads[FILE_A][2], [0])
        expected = torch.ones(256) + torch.Tensor(
            np.bincount(targets.flatten().astype(np.int16) + 128, minlength=256)
        )

        assert dataset.class_count.shape == (256,)
        torch.testing.assert_close(dataset.class_count, expected)


# ---------------------------------------------------------------------------
# §4 row: VALIDATION FILENAME
# Failure class: filename authority disconnect.
# ---------------------------------------------------------------------------


class TestRawValidationFilename:
    """The scorer's inlined raw name and the profile pattern must agree.

    ``scoring_utils.py:389`` and ``:444`` build
    ``f"abra_validation_{file_index:04d}.h5"`` inline;
    ``TIDMAD.validation_file_pattern`` renders the same string and has ZERO
    production consumers (roadmap §0.8's seam-without-consumer). Nothing
    compares them today, so C4 would be routing the scorer onto an
    unverified equivalence.

    The equivalence is the invariant, and it holds on BOTH sides of C4 —
    which is exactly what makes C4 safe.
    """

    @pytest.fixture
    def captured_raw_names(self, monkeypatch):
        """Capture the filename the REAL scorer worker builds.

        ``get_one_sec_psd``/``get_snr`` are replaced so no HDF5 is needed;
        the name under test is built by production code before either is
        called.
        """
        seen: list[str] = []

        def fake_psd(file_path, files, ch, start=0):
            if ch == 2:
                seen.append(files)
            return np.zeros(4), np.zeros(4)

        monkeypatch.setattr(su, "get_one_sec_psd", fake_psd)
        monkeypatch.setattr(su, "get_snr", lambda freq, pwr, target=None: (1.0, 1.0))
        return seen

    def test_collect_raw_pairs_builds_the_pattern_render(self, captured_raw_names):
        """``_collect_raw_pairs`` — the worker ``score_vector`` actually uses."""
        su._collect_raw_pairs((".", "denoised.h5", 7, [0, 1], "."))

        assert captured_raw_names == ["abra_validation_0007.h5"] * 2
        assert captured_raw_names[0] == TIDMAD.validation_file_pattern.format(file_index=7)

    def test_score_segments_builds_the_pattern_render(self, captured_raw_names):
        """``score_segments`` — the anchor-mode worker, a second inline copy."""
        su.score_segments(
            data_dir=".",
            denoised_filename="denoised.h5",
            file_index=13,
            segment_indices=[0],
            anchor_map={"13": [1.0]},
            s_max=1.0,
            raw_data_dir=".",
        )

        assert captured_raw_names == ["abra_validation_0013.h5"]
        assert captured_raw_names[0] == TIDMAD.validation_file_pattern.format(file_index=13)

    def test_the_pattern_renders_identically_across_the_whole_index_space(self):
        """Two DIFFERENT constructions are inlined in production —
        ``f"{i:04d}"`` (``scoring_utils``, ``denoising_score_single:137``)
        and ``str(i).zfill(4)`` (``inference_single:782``). They agree only
        for non-negative ints, and both must equal the pattern render, or
        C4 would unify two subtly different names into one.
        """
        for file_index in range(TIDMAD.num_files):
            rendered = TIDMAD.validation_file_pattern.format(file_index=file_index)
            assert rendered == f"abra_validation_{file_index:04d}.h5"
            assert rendered == f"abra_validation_{str(file_index).zfill(4)}.h5"

    def test_raw_and_denoised_names_stay_distinct(self):
        """§1's boundary, as an executable guard: the raw validation name is
        Step-02 topology and C4 routes it; every denoised name is the
        Deliverable Contract's and must NOT be reachable from the profile.
        A profile pattern that ever rendered a denoised name would be a
        scope leak."""
        rendered = TIDMAD.validation_file_pattern.format(file_index=6)
        assert "denoised" not in rendered
