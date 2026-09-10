"""Generic validation helpers for declared HDF5 deliverables."""

from __future__ import annotations

import h5py
import numpy as np

from execute_tools.deliverable_spec import DeliverableStorage


def _declared_vector(
    handle: h5py.File,
    channel_group: str,
) -> h5py.Dataset | None:
    """Resolve one declared vector while rejecting non-dataset HDF5 nodes."""
    timeseries = handle.get("timeseries")
    if not isinstance(timeseries, h5py.Group):
        return None
    channel = timeseries.get(channel_group)
    if not isinstance(channel, h5py.Group):
        return None
    values = channel.get("timeseries")
    return values if isinstance(values, h5py.Dataset) else None


def is_complete_hdf5_deliverable(
    path: str,
    expected_samples: int,
    storage: DeliverableStorage,
) -> bool:
    """Return whether both declared vectors are complete and readable."""
    try:
        with h5py.File(path, "r") as handle:
            input_values = _declared_vector(handle, storage.input_channel_group)
            target_values = _declared_vector(handle, storage.target_channel_group)
            if input_values is None or target_values is None:
                return False
            expected_shape = (expected_samples,)
            expected_dtype = np.dtype(storage.storage_dtype)
            if (
                input_values.shape != expected_shape
                or target_values.shape != expected_shape
                or input_values.dtype != expected_dtype
                or target_values.dtype != expected_dtype
            ):
                return False
            if expected_samples:
                input_values[0]
                input_values[-1]
                target_values[0]
                target_values[-1]
        return True
    except (KeyError, OSError, ValueError):
        return False
