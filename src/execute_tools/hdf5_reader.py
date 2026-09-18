"""Bounded, read-only HDF5 access for external dataset adapters.

Retain dataset handles, not just files: the raw chunk cache belongs to a
*dataset*. Size each cache to its physical chunk geometry, share a fixed byte
budget across handles, and evict least-recently-used handles. Selection,
encoding, ordering and tensor conversion remain owned by the caller.
"""

from __future__ import annotations

import math
import os
import warnings
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import h5py
import numpy as np
from pydantic import BaseModel, ConfigDict, Field


class HDF5ReadCacheConfig(BaseModel):
    """Raw chunk cache limits per reader/process, excluding returned arrays."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    max_cache_bytes: int = Field(default=64 * 1024**2, ge=0)
    max_open_datasets: int = Field(default=16, ge=1)
    target_cache_bytes: int = Field(
        default=8 * 1024**2,
        ge=0,
        description="Preferred per-dataset working cache, clipped to the shared byte budget.",
    )


@dataclass
class _Entry:
    file: h5py.File
    dataset: h5py.Dataset
    cache_bytes: int

    def close(self) -> None:
        self.dataset.id.close()
        self.file.close()


class HDF5ReadCache:
    """Read immutable inputs without repeatedly decompressing oversized chunks.

    The cache never expands the requested selection, casts values or loads the
    entire dataset. If a single chunk exceeds the whole budget, access remains
    correct but uncached and emits an actionable warning. The raw chunk cache
    is bounded, not total RSS: arrays, metadata and filter scratch buffers are
    additional. Instances are process-local, not thread-safe;
    pickle and fork reset handles. Call close() at the dataset lifecycle boundary.
    """

    def __init__(self, config: HDF5ReadCacheConfig | None = None) -> None:
        self.config = config or HDF5ReadCacheConfig()
        self._entries: OrderedDict[tuple[str, str], _Entry] = OrderedDict()
        self._pid = os.getpid()

    @property
    def allocated_cache_bytes(self) -> int:
        return sum(entry.cache_bytes for entry in self._entries.values())

    def _open(self, path: str, name: str) -> _Entry:
        handle = h5py.File(path, "r", rdcc_nbytes=0)
        try:
            obj = handle[name]
            if not isinstance(obj, h5py.Dataset):
                raise TypeError(f"HDF5 path {name!r} in {path!r} is not a dataset")
            chunk_bytes = math.prod(obj.chunks) * obj.dtype.itemsize if obj.chunks else 0
            # Variable-length elements cannot be bounded from dtype.itemsize.
            if obj.dtype.hasobject:
                chunk_bytes = 0
            # A tiny chunk must not shrink the working cache to one chunk:
            # multidimensional row selections can revisit several chunks.
            capacity = (
                max(chunk_bytes, min(self.config.target_cache_bytes, self.config.max_cache_bytes))
                if chunk_bytes
                else 0
            )
            if capacity > self.config.max_cache_bytes:
                warnings.warn(
                    f"HDF5 dataset {path}:{name} has a {chunk_bytes}-byte chunk, "
                    f"exceeding the {self.config.max_cache_bytes}-byte reader cache; "
                    "small repeated reads will decompress chunks repeatedly. Increase "
                    "the bounded cache or coalesce reads without changing selection.",
                    RuntimeWarning,
                    stacklevel=3,
                )
                capacity = 0
            obj.id.close()
            while self._entries and (
                len(self._entries) >= self.config.max_open_datasets
                or self.allocated_cache_bytes + capacity > self.config.max_cache_bytes
            ):
                self._entries.popitem(last=False)[1].close()
            access = h5py.h5p.create(h5py.h5p.DATASET_ACCESS)
            try:
                access.set_chunk_cache(521, capacity, 0.75)
                dataset_id = h5py.h5d.open(handle.id, name.encode("utf-8"), dapl=access)
            finally:
                access.close()
            return _Entry(handle, h5py.Dataset(dataset_id), capacity)
        except BaseException:
            handle.close()
            raise

    def read(self, path: str | Path, dataset: str, selection: Any) -> np.ndarray:
        """Return exactly the requested HDF5 selection in its original dtype."""
        if self._pid != os.getpid():
            self.close()
            self._pid = os.getpid()
        key = (os.path.abspath(os.fspath(path)), dataset)
        entry = self._entries.get(key)
        if entry is None:
            entry = self._open(*key)
            self._entries[key] = entry
        self._entries.move_to_end(key)
        return np.asarray(entry.dataset[selection])

    def close(self) -> None:
        entries = getattr(self, "_entries", {})
        for entry in entries.values():
            entry.close()
        entries.clear()

    def __getstate__(self) -> dict[str, object]:
        return {"config": self.config}

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__init__(state["config"])

    def __del__(self) -> None:
        self.close()
