"""Task-neutral ordering primitives: visit sequence, parity, and boundaries.

Ordering changes the sequence in which selected samples are visited and
nothing else. These tests assert the actual visited row sequence rather
than merely checking a configuration value, plus the invariant that shuffle
and sequential strategies execute the same number of optimizer steps.

Loader partitioning is explicitly NOT part of this: one global DataLoader
with the global ``drop_last``, so batches may span a file boundary and the
step count is identical across strategies (Decision 4a).

Task-owned dataset construction and runtime execution belong to external task
qualification. This module protects only the reusable ordering mechanism.
"""

from __future__ import annotations

import random

import pytest
from torch.utils.data import DataLoader, Dataset

import execute_tools.train_engine_sandbox as tes


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


def test_sequential_indices_refuse_repeated_loaded_group():
    with pytest.raises(ValueError, match="repeats loaded training group"):
        tes.build_sequential_indices({4: (0, 3), 5: (3, 6)}, [4, 4, 5], random.Random(9))


def test_valid_permutation_and_defaults_pass():
    sample_set = {"4": [0], "5": [0], "6": [0]}
    tes.validate_ordering_against_scope("sequential", [6, 4, 5], sample_set)
    tes.validate_ordering_against_scope("sequential", None, sample_set)
    tes.validate_ordering_against_scope("shuffle", None, sample_set)
