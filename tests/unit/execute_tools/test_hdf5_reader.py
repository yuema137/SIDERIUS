"""Prevent repeated chunk decompression without changing selections or dtype."""

import pickle

import h5py
import numpy as np
import pytest

from execute_tools.hdf5_reader import HDF5ReadCache, HDF5ReadCacheConfig


@pytest.mark.parametrize("chunks", [None, (16, 8)])
def test_exact_noncontiguous_selection_and_handle_reuse(tmp_path, chunks):
    path = tmp_path / "arrays.h5"
    values = np.arange(512, dtype=np.int16).reshape(64, 8)
    with h5py.File(path, "w") as f:
        f.create_dataset("x", data=values, chunks=chunks, compression="gzip" if chunks else None)
    reader = HDF5ReadCache()
    try:
        selected = ([0, 2, 17, 61], slice(1, 7))
        actual = reader.read(path, "x", selected)
        np.testing.assert_array_equal(actual, values[selected])
        assert actual.dtype == values.dtype
        entry = next(iter(reader._entries.values()))
        reader.read(path, "x", slice(1, 2))
        assert next(iter(reader._entries.values())) is entry
        if chunks:
            assert entry.dataset.id.get_access_plist().get_chunk_cache()[1] == 8 * 1024**2
    finally:
        reader.close()
    assert not entry.dataset.id.valid


def test_eviction_pickle_and_reopen_keep_memory_bounded(tmp_path):
    path = tmp_path / "arrays.h5"
    with h5py.File(path, "w") as f:
        for name in ("x", "y", "z"):
            f.create_dataset(name, data=np.arange(128), chunks=(16,), compression="gzip")
    reader = HDF5ReadCache(HDF5ReadCacheConfig(max_cache_bytes=256))
    reader.read(path, "x", slice(2))
    first = next(iter(reader._entries.values()))
    reader.read(path, "y", slice(2))
    reader.read(path, "z", slice(2))
    assert not first.dataset.id.valid
    assert reader.allocated_cache_bytes == 256
    restored = pickle.loads(pickle.dumps(reader))
    assert restored.allocated_cache_bytes == 0
    np.testing.assert_array_equal(restored.read(path, "x", slice(3)), [0, 1, 2])
    assert reader.allocated_cache_bytes == 256  # serializing never closes parent's handles
    restored.close()
    reader.close()


def test_oversize_chunk_warns_and_still_returns_exact_values(tmp_path):
    path = tmp_path / "oversize.h5"
    with h5py.File(path, "w") as f:
        f.create_dataset("x", data=np.arange(128), chunks=(128,), compression="gzip")
    reader = HDF5ReadCache(HDF5ReadCacheConfig(max_cache_bytes=128))
    with pytest.warns(RuntimeWarning, match="1024-byte chunk"):
        result = reader.read(path, "x", slice(4, 8))
    np.testing.assert_array_equal(result, [4, 5, 6, 7])
    assert reader.allocated_cache_bytes == 0
    reader.close()


def test_relative_paths_do_not_alias_after_working_directory_changes(tmp_path, monkeypatch):
    """A cache key must identify the file, not just a relative spelling."""
    for name, value in (("a", 11), ("b", 29)):
        directory = tmp_path / name
        directory.mkdir()
        with h5py.File(directory / "input.h5", "w") as handle:
            handle.create_dataset("x", data=[value])
    reader = HDF5ReadCache()
    try:
        monkeypatch.chdir(tmp_path / "a")
        np.testing.assert_array_equal(reader.read("input.h5", "x", slice(None)), [11])
        monkeypatch.chdir(tmp_path / "b")
        np.testing.assert_array_equal(reader.read("input.h5", "x", slice(None)), [29])
    finally:
        reader.close()
