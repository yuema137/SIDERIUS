"""Generic validation helpers for declared HDF5 deliverables."""

from __future__ import annotations

import h5py
import numpy as np

from execute_tools.deliverable_spec import DeliverableStorage


def is_complete_hdf5_deliverable(
    path: str,
    expected_samples: int,
    storage: DeliverableStorage,
) -> bool:
    """Return whether both declared vectors are complete and readable."""
    try:
        with h5py.File(path, "r") as handle:
            input_values = handle["timeseries"][storage.input_channel_group]["timeseries"]
            target_values = handle["timeseries"][storage.target_channel_group]["timeseries"]
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
