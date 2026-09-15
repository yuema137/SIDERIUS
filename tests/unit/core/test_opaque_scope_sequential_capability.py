"""Sequential ordering is an explicit task-dataset capability.

These tests replace the old C12-P/B8 reachability sentinel. That sentinel
required composed tasks to lose their ordering controls at the subprocess
boundary in order to mask an unsafe attribute access. The production incident
made that masking behavior itself observable and harmful. The replacement
guards the real contract: opaque scopes may transport ordering, capable
datasets work, and incapable or malformed datasets fail with a named error.
"""

from __future__ import annotations

import pytest
from torch.utils.data import Dataset

from execute_tools.task_data_path import TrainingScopeError
from execute_tools.train_engine_sandbox import (
    resolve_sequential_file_row_ranges,
)


class _Dataset(Dataset):
    def __init__(self, ranges=None):
        if ranges is not None:
            self.file_row_ranges = ranges

    def __len__(self) -> int:
        return 6

    def __getitem__(self, index: int) -> int:
        return index


def test_sequential_dataset_capability_resolves_declared_groups() -> None:
    dataset = _Dataset({2: (0, 2), 0: (2, 4), 1: (4, 6)})
    assert resolve_sequential_file_row_ranges(dataset) == {
        2: (0, 2),
        0: (2, 4),
        1: (4, 6),
    }


def test_sequential_refuses_dataset_without_group_capability() -> None:
    with pytest.raises(TrainingScopeError, match="file_row_ranges"):
        resolve_sequential_file_row_ranges(_Dataset())


@pytest.mark.parametrize(
    "ranges",
    [
        {0: (0, 7)},  # outside dataset
        {0: (2, 2)},  # empty span
        {"0": (0, 2)},  # wrong group identity type
    ],
)
def test_sequential_refuses_malformed_group_capability(ranges) -> None:
    with pytest.raises(TrainingScopeError, match="invalid file_row_ranges"):
        resolve_sequential_file_row_ranges(_Dataset(ranges))


@pytest.mark.parametrize(
    "ranges",
    [
        {0: (0, 2), 1: (3, 6)},  # gap
        {0: (0, 4), 1: (3, 6)},  # overlap
        {0: (0, 2), 1: (2, 5)},  # uncovered tail
    ],
)
def test_sequential_refuses_groups_that_do_not_partition_dataset(ranges) -> None:
    with pytest.raises(TrainingScopeError, match="partition every materialized"):
        resolve_sequential_file_row_ranges(_Dataset(ranges))
