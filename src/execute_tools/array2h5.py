import os
import uuid
from contextlib import suppress

import h5py

from execute_tools.deliverable_spec import DeliverableStorage, default_deliverable_storage

"""
Create an HDF5 file with the ABRA data format.

Parameters:
- file_name (str): The name of the HDF5 file to be created. Default is 'example.h5'.
- array1 (array-like): The data array to be saved in the INPUT channel's 'timeseries' dataset.
- array2 (array-like, optional): The data array to be saved in the TARGET channel's 'timeseries'
  dataset. Default is None.
- storage (DeliverableStorage, optional): Step 05c — which in-file groups the two signals are
  written to. Every production call site supplies the run's value; ``None`` resolves the shipped
  TIDMAD identity, so a caller predating 05c writes exactly the same file.

Example usage:
1. Science data -- Create an HDF5 file with only the input channel:
    >>> array1 = [1, 2, 3, 4, 5]
    >>> create_abra_file('denoised_data.h5', array1)

2. Calibration data -- Create an HDF5 file with both channels:
    >>> array1 = [1, 2, 3, 4, 5]
    >>> array2 = [6, 7, 8, 9, 10]
    >>> create_abra_file('denoised_data.h5', array1, array2)
"""


def create_abra_file(
    file_name,
    array1,
    array2=None,
    indexed=True,
    *,
    storage: DeliverableStorage | None = None,
):
    # Step 05c — the channel-group identity is DERIVED, closing the write side
    # of the gap Step 02 left half-open: the read side already used
    # `profile_channels.input_channel` / `.target_channel`
    # (inference_single.py:661,664) while this writer contradicted it with two
    # hardcoded names. Under TIDMAD the derivation resolves to `channel0001` /
    # `channel0002`, so the written bytes do not move.
    #
    # NOT derived, by OD-05c-2: the five instrument attrs below, `N`, the split
    # mechanics and the `indexed` suffix rule. No production consumer reads the
    # attrs, so owning them would make 05c a format declaration rather than a
    # contract extraction. `sampling_frequency` here duplicates the already
    # declared `DatasetConfig.sampling_frequency` (10 MS/s) and is recorded as
    # debt for whoever wins final ownership.
    channels = storage if storage is not None else default_deliverable_storage()

    N = 2000000000

    # Check if the file name is valid
    if not file_name.endswith(".h5"):
        print("Invalid file name. File name must end with '.h5'")
        return
    num_files = (len(array1) + N - 1) // N
    print(num_files)

    for i in range(num_files):
        start_idx = i * N
        end_idx = min(start_idx + N, len(array1))

        indexed_file_name = f"{os.path.splitext(file_name)[0]}_{i}.h5"  # NEW
        if not indexed:
            indexed_file_name = f"{os.path.splitext(file_name)[0]}.h5"  # NEW

        _write_abra_file_atomic(
            indexed_file_name,
            array1[start_idx:end_idx],
            None if array2 is None else array2[start_idx:end_idx],
            channels,
        )
        print(f"HDF5 file '{indexed_file_name}' created successfully.")


def atomic_abra_auxiliary_patterns(final_pattern: str) -> tuple[str, ...]:
    """Name this writer's marker and interrupted-write files for exact outputs.

    ``final_pattern`` comes from the run's attempt-scoped deliverable naming
    authority. The caller enumerates these only after the inference process
    has exited, so an unfinished temporary file no longer has a writer.
    """

    if "/" in final_pattern or "\\" in final_pattern:
        raise ValueError("ABRA output pattern must be a basename")
    if not final_pattern.endswith(".h5"):
        return ()
    return (
        f"{final_pattern}.complete",
        f".{final_pattern}.*.tmp",
        f"{final_pattern}.complete.*.tmp",
    )


def _write_abra_file_atomic(
    destination: str,
    input_values,
    target_values,
    channels: DeliverableStorage,
) -> None:
    """Write one deliverable completely before publishing its final name."""
    parent = os.path.dirname(os.path.abspath(destination))
    os.makedirs(parent, exist_ok=True)
    token = uuid.uuid4().hex
    temporary = os.path.join(parent, f".{os.path.basename(destination)}.{token}.tmp")
    marker = f"{destination}.complete"
    marker_tmp = f"{marker}.{token}.tmp"
    try:
        with h5py.File(temporary, "w") as f:
            # Create timeseries group
            timeseries_group = f.create_group("timeseries")

            # Create the INPUT channel subgroup
            channel0001_group = timeseries_group.create_group(channels.input_channel_group)
            channel0001_group.attrs["file_first_sample_index"] = 100000000000000
            channel0001_group.attrs["input_coupling"] = 0
            channel0001_group.attrs["input_impedance_ohm"] = 50
            channel0001_group.attrs["sampling_frequency"] = 10000000
            channel0001_group.attrs["voltage_range_mV"] = 80

            # Save array1 to channel0001/timeseries dataset
            channel0001_group.create_dataset("timeseries", data=input_values, chunks=True)

            if target_values is not None:
                # Create the TARGET channel subgroup if it is a calibration dataset
                channel0002_group = timeseries_group.create_group(channels.target_channel_group)
                channel0002_group.attrs["file_first_sample_index"] = 100000000000000
                channel0002_group.attrs["input_coupling"] = 0
                channel0002_group.attrs["input_impedance_ohm"] = 50
                channel0002_group.attrs["sampling_frequency"] = 10000000
                channel0002_group.attrs["voltage_range_mV"] = 80

                # Save array2 to channel0002/timeseries dataset
                channel0002_group.create_dataset("timeseries", data=target_values, chunks=True)
            f.flush()
        os.replace(temporary, destination)
        with open(marker_tmp, "x", encoding="utf-8") as handle:
            handle.write("complete\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(marker_tmp, marker)
    except BaseException:
        for path in (temporary, marker_tmp):
            with suppress(FileNotFoundError):
                os.unlink(path)
        raise
