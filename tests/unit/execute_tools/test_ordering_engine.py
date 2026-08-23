"""Training-engine data ordering: visit sequence, parity, and boundaries.

Ordering changes the sequence in which selected samples are visited and
nothing else. These tests assert the ACTUAL visited row sequence rather
than the configuration value, and pin the four-part default-``shuffle``
parity contract: same selection, same RNG behavior, same visited
sequence, same step count
(``docs/design/v19_priorities/pr2_data_ordering.md`` §3.1, §7.1).

Loader partitioning is explicitly NOT part of this: one global DataLoader
with the global ``drop_last``, so batches may span a file boundary and the
step count is identical across strategies (Decision 4a).
"""

from __future__ import annotations

import random

import h5py
import numpy as np
import pytest
from torch.utils.data import DataLoader, Dataset

import execute_tools.train_engine_sandbox as tes
from execute_tools.dataset_config import (
    TIDMAD_PROFILE,
    bind_dataset_profile,
    tidmad_topology,
)

SEG_SIZE = 1000


# ---- fixtures ----


@pytest.fixture
def multi_file_data(tmp_path):
    """Three tiny training files (indices 4, 5, 6), 2 PSD segments each.

    The declared psd_segment_length is shrunk to SEG_SIZE so one PSD segment
    is exactly one ML row — making row counts trivially predictable.

    Was ``monkeypatch.setattr(tes, "PSD_SEGMENT_LENGTH", SEG_SIZE)`` until
    PR-02a C3 moved the loaders onto the resolved Dataset Profile. Geometry
    is now declared, not patched; every assertion below is unchanged.
    """
    segments_per_file = 2
    rng = np.random.default_rng(0)
    for file_index in (4, 5, 6):
        # Build the name from the DECLARATION, not from whatever the
        # engine module happens to import — C3 removed the engine's
        # dependency on the TIDMAD singleton entirely.
        path = tmp_path / tidmad_topology(TIDMAD_PROFILE).dataset.training_file_name(file_index)
        n = segments_per_file * SEG_SIZE
        with h5py.File(path, "w") as f:
            ts = f.create_group("timeseries")
            ts.create_group("channel0001").create_dataset(
                "timeseries", data=rng.integers(-128, 127, size=n, dtype=np.int8)
            )
            ts.create_group("channel0002").create_dataset(
                "timeseries", data=rng.integers(-128, 127, size=n, dtype=np.int16)
            )
    sample_set = {"4": [0, 1], "5": [0, 1], "6": [0, 1]}
    tiny = TIDMAD_PROFILE.model_copy(
        update={
            "dataset": tidmad_topology(TIDMAD_PROFILE).dataset.model_copy(
                update={"psd_segment_length": SEG_SIZE}
            )
        }
    )
    with bind_dataset_profile(tiny):
        yield str(tmp_path), sample_set


class _IdentityDataset(Dataset):
    """Each item IS its index, so a captured batch reveals the visit order."""

    def __init__(self, n: int):
        self.n = n

    def __len__(self) -> int:
        return self.n

    def __getitem__(self, idx: int) -> int:
        return idx


def _visited(loader: DataLoader) -> list[int]:
    return [int(i) for batch in loader for i in batch]


# ---- build_sequential_indices: the visit order itself ----


def test_blocks_are_visited_in_file_order():
    ranges = {4: (0, 3), 5: (3, 6), 6: (6, 9)}
    indices = tes.build_sequential_indices(ranges, [6, 4, 5], random.Random(1))
    # Block membership, in order: file 6's rows, then 4's, then 5's.
    assert sorted(indices[0:3]) == [6, 7, 8]
    assert sorted(indices[3:6]) == [0, 1, 2]
    assert sorted(indices[6:9]) == [3, 4, 5]


def test_every_row_is_visited_exactly_once():
    """Ordering permutes; it must not drop or duplicate a single sample."""
    ranges = {4: (0, 3), 5: (3, 6), 6: (6, 9)}
    indices = tes.build_sequential_indices(ranges, [5, 6, 4], random.Random(2))
    assert sorted(indices) == list(range(9))


def test_none_file_order_visits_ascending_file_index():
    ranges = {6: (6, 9), 4: (0, 3), 5: (3, 6)}
    indices = tes.build_sequential_indices(ranges, None, random.Random(3))
    assert sorted(indices[0:3]) == [0, 1, 2]  # file 4 first
    assert sorted(indices[6:9]) == [6, 7, 8]  # file 6 last


def test_rows_are_shuffled_within_each_block():
    ranges = {4: (0, 20)}
    indices = tes.build_sequential_indices(ranges, [4], random.Random(4))
    assert sorted(indices) == list(range(20))
    assert indices != list(range(20)), "within-file order should be shuffled"


def test_within_file_order_varies_across_epochs_but_is_seed_deterministic():
    ranges = {4: (0, 20)}
    epoch0 = tes.build_sequential_indices(ranges, [4], random.Random("order:100"))
    epoch1 = tes.build_sequential_indices(ranges, [4], random.Random("order:101"))
    again = tes.build_sequential_indices(ranges, [4], random.Random("order:100"))
    assert epoch0 != epoch1, "different epoch seeds should reshuffle within file"
    assert epoch0 == again, "same seed must reproduce the same order"


def test_file_order_may_name_a_file_that_contributed_no_rows():
    """A file missing on disk is skipped during construction (warn+continue);
    naming it in file_order must not break the epoch."""
    ranges = {4: (0, 3), 6: (3, 6)}  # file 5 was skipped
    indices = tes.build_sequential_indices(ranges, [4, 5, 6], random.Random(5))
    assert sorted(indices) == list(range(6))


def test_file_order_omitting_a_loaded_file_is_rejected():
    """Silently never visiting a loaded file would change selection."""
    ranges = {4: (0, 3), 5: (3, 6)}
    with pytest.raises(ValueError) as exc:
        tes.build_sequential_indices(ranges, [4], random.Random(6))
    assert "omits loaded training file(s) [5]" in str(exc.value)


# ---- the loader visits exactly what the sampler says ----


def test_loader_iterates_in_sampler_order():
    order = [7, 3, 0, 9, 1, 4, 8, 2, 6, 5]
    loader = DataLoader(_IdentityDataset(10), batch_size=2, sampler=order, drop_last=True)
    assert _visited(loader) == order


def test_batches_may_span_a_file_boundary():
    """Decision 4a: one global loader, so a batch straddling two file blocks
    is expected and acceptable — the step count stays identical to shuffle."""
    ranges = {4: (0, 3), 5: (3, 6)}  # 3-row blocks, batch of 2
    indices = tes.build_sequential_indices(ranges, [4, 5], random.Random(7))
    loader = DataLoader(_IdentityDataset(6), batch_size=2, sampler=indices, drop_last=True)
    batches = [[int(i) for i in b] for b in loader]
    block_of = lambda row: 4 if row < 3 else 5  # noqa: E731
    assert any(len({block_of(r) for r in batch}) == 2 for batch in batches), (
        "expected at least one batch spanning the file boundary"
    )


@pytest.mark.parametrize("batch_size", [1, 2, 3, 4])
def test_step_count_is_identical_across_strategies(batch_size):
    """The load-bearing parity property: matched-budget comparisons compare
    equal numbers of optimizer steps."""
    n = 9
    shuffle_loader = DataLoader(
        _IdentityDataset(n), batch_size=batch_size, shuffle=True, drop_last=True
    )
    indices = tes.build_sequential_indices(
        {4: (0, 3), 5: (3, 6), 6: (6, 9)}, [6, 5, 4], random.Random(8)
    )
    sequential_loader = DataLoader(
        _IdentityDataset(n), batch_size=batch_size, sampler=indices, drop_last=True
    )
    assert len(sequential_loader) == len(shuffle_loader) == n // batch_size


# ---- dataset block layout ----


def test_file_row_ranges_cover_the_dataset_contiguously(multi_file_data):
    data_dir, sample_set = multi_file_data
    dataset = tes.TIDMADEpochDataset(
        data_dir=data_dir, sample_set=sample_set, seg_size=SEG_SIZE, rng=random.Random(0)
    )
    assert dataset.file_row_ranges == {4: (0, 2), 5: (2, 4), 6: (4, 6)}
    assert len(dataset) == 6


def test_file_row_ranges_skip_a_missing_file(multi_file_data, capsys):
    data_dir, sample_set = multi_file_data
    sample_set = {**sample_set, "7": [0, 1]}  # file 7 does not exist on disk
    dataset = tes.TIDMADEpochDataset(
        data_dir=data_dir, sample_set=sample_set, seg_size=SEG_SIZE, rng=random.Random(0)
    )
    assert 7 not in dataset.file_row_ranges
    assert "not found, skipping" in capsys.readouterr().out
    assert len(dataset) == 6


def test_selection_is_identical_regardless_of_ordering(multi_file_data):
    """Ordering must not change WHICH samples are selected — the datasets
    built for either strategy are byte-identical under the same seed."""
    data_dir, sample_set = multi_file_data
    a = tes.TIDMADEpochDataset(
        data_dir=data_dir,
        sample_set=sample_set,
        seg_size=SEG_SIZE,
        train_portion=0.5,
        rng=random.Random(11),
    )
    b = tes.TIDMADEpochDataset(
        data_dir=data_dir,
        sample_set=sample_set,
        seg_size=SEG_SIZE,
        train_portion=0.5,
        rng=random.Random(11),
    )
    assert np.array_equal(a.inputs, b.inputs)
    assert np.array_equal(a.targets, b.targets)
    assert a.file_row_ranges == b.file_row_ranges


# ---- boundary validation ----


def test_shuffle_with_a_file_order_is_rejected():
    with pytest.raises(ValueError) as exc:
        tes.validate_ordering_against_scope("shuffle", [4, 5], {"4": [0], "5": [0]})
    assert "meaningful only for sequential" in str(exc.value)


def test_unknown_strategy_is_rejected():
    with pytest.raises(ValueError) as exc:
        tes.validate_ordering_against_scope("round_robin", None, {"4": [0]})
    assert "not recognized" in str(exc.value)


@pytest.mark.parametrize(
    "file_order, fragment",
    [
        ([4, 5], "missing [6]"),
        ([4, 5, 6, 7], "outside the sample set [7]"),
        ([4, 5, 5, 6], "duplicated [5]"),
    ],
)
def test_file_order_must_permute_the_sample_set(file_order, fragment):
    sample_set = {"4": [0], "5": [0], "6": [0]}
    with pytest.raises(ValueError) as exc:
        tes.validate_ordering_against_scope("sequential", file_order, sample_set)
    assert "not a permutation" in str(exc.value)
    assert fragment in str(exc.value)


def test_valid_permutation_and_defaults_pass():
    sample_set = {"4": [0], "5": [0], "6": [0]}
    tes.validate_ordering_against_scope("sequential", [6, 4, 5], sample_set)
    tes.validate_ordering_against_scope("sequential", None, sample_set)
    tes.validate_ordering_against_scope("shuffle", None, sample_set)


# ---- default-shuffle parity: the ordering code must not touch that path ----


def _tiny_configs():
    from ml_models.models_format_sandbox import LossConfig, TrainConfig, WaveNetConfig

    return (
        WaveNetConfig(
            segmentation_size=SEG_SIZE,
            input_channels=4,
            residual_channels=8,
            gate_channels=8,
            skip_channels=8,
            kernel_size=2,
            num_blocks=1,
        ),
        TrainConfig(lr=1e-4, epochs=1, batch_size=1, optimizer_type="adam", device="cpu"),
        LossConfig(),
    )


def _run_engine(tmp_path, data_dir, sample_set, monkeypatch, **ordering):
    """Run the real engine on the tiny CPU setup, capturing DataLoader kwargs."""
    model_cfg, train_cfg, loss_cfg = _tiny_configs()
    sandbox_dirs = {
        "models": str(tmp_path / "cached_models"),
        "results": str(tmp_path / "records"),
    }
    for d in sandbox_dirs.values():
        __import__("os").makedirs(d, exist_ok=True)

    captured: list[dict] = []
    real_dataloader = tes.DataLoader

    def spy(dataset, **kwargs):
        captured.append(kwargs)
        return real_dataloader(dataset, **kwargs)

    monkeypatch.setattr(tes, "DataLoader", spy)

    summary = tes.run_experiment_streaming(
        model_cfg,
        train_cfg,
        loss_cfg,
        sample_set=sample_set,
        data_dir=data_dir,
        sandbox_dirs=sandbox_dirs,
        exp_id="ordering_parity",
        train_base_seed=42,
        **ordering,
    )
    return summary, captured


def test_default_shuffle_path_is_unchanged(tmp_path, multi_file_data, monkeypatch, capsys):
    """Four-part parity contract, default path: the engine still builds
    DataLoader(shuffle=True) with no sampler, so selection, RNG source, and
    visited sequence are exactly the pre-PR2 ones."""
    data_dir, sample_set = multi_file_data
    summary, captured = _run_engine(tmp_path, data_dir, sample_set, monkeypatch)

    assert summary is not None
    assert len(captured) == 1
    assert captured[0]["shuffle"] is True
    assert "sampler" not in captured[0]
    assert captured[0]["drop_last"] is True
    assert "[data_order] resolved=shuffle file_order=none epoch=0" in capsys.readouterr().out


def test_sequential_path_uses_a_sampler_and_keeps_the_step_count(
    tmp_path, multi_file_data, monkeypatch, capsys
):
    """Sequential swaps the sampler in — and nothing else. Same global
    drop_last, same number of optimizer steps as the shuffle run above."""
    data_dir, sample_set = multi_file_data
    summary, captured = _run_engine(
        tmp_path,
        data_dir,
        sample_set,
        monkeypatch,
        order_strategy="sequential",
        file_order=[6, 4, 5],
    )

    assert summary is not None
    kwargs = captured[0]
    assert "shuffle" not in kwargs
    assert kwargs["drop_last"] is True
    assert sorted(kwargs["sampler"]) == list(range(6)), "every row visited exactly once"
    # File 6 occupies rows 4-5, and it is visited first.
    assert sorted(kwargs["sampler"][0:2]) == [4, 5]

    out = capsys.readouterr().out
    assert "[data_order] resolved=sequential file_order=[6, 4, 5] epoch=0" in out


def test_engine_rejects_a_file_order_that_is_not_a_permutation(
    tmp_path, multi_file_data, monkeypatch
):
    """Defense in depth: the tuner validated already, but the engine has its
    own CLI and must not trust its input."""
    data_dir, sample_set = multi_file_data
    with pytest.raises(ValueError) as exc:
        _run_engine(
            tmp_path,
            data_dir,
            sample_set,
            monkeypatch,
            order_strategy="sequential",
            file_order=[4, 5],  # omits 6
        )
    assert "not a permutation" in str(exc.value)
