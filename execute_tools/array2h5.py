import h5py
import os

"""
Create an HDF5 file with the ABRA data format.

Parameters:
- file_name (str): The name of the HDF5 file to be created. Default is 'example.h5'.
- array1 (array-like): The data array to be saved in 'channel0001/timeseries' dataset.
- array2 (array-like, optional): The data array to be saved in 'channel0002/timeseries' dataset. Default is None.

Example usage:
1. Science data -- Create an HDF5 file with only channel0001:
    >>> array1 = [1, 2, 3, 4, 5]
    >>> create_abra_file('denoised_data.h5', array1)

2. Calibration data -- Create an HDF5 file with both channel0001 and channel0002:
    >>> array1 = [1, 2, 3, 4, 5]
    >>> array2 = [6, 7, 8, 9, 10]
    >>> create_abra_file('denoised_data.h5', array1, array2)
"""

def create_abra_file(file_name, array1, array2 = None, indexed=True):
    N = 2000000000

    # Check if the file name is valid
    if not file_name.endswith('.h5'):
        print("Invalid file name. File name must end with '.h5'")
        return
    num_files = (len(array1) + N - 1) // N
    print(num_files)

    for i in range(num_files):
        start_idx = i * N
        end_idx = min(start_idx + N, len(array1))

        indexed_file_name = f"{os.path.splitext(file_name)[0]}_{i}.h5"  # NEW
        if indexed == False:
            indexed_file_name = f"{os.path.splitext(file_name)[0]}.h5"  # NEW

        # Create HDF5 file
        with h5py.File(indexed_file_name, 'w') as f:
            # Create timeseries group
            timeseries_group = f.create_group('timeseries')
        
            # Create channel0001 subgroup
            channel0001_group = timeseries_group.create_group('channel0001')
            channel0001_group.attrs['file_first_sample_index'] = 100000000000000
            channel0001_group.attrs['input_coupling'] = 0
            channel0001_group.attrs['input_impedance_ohm'] = 50
            channel0001_group.attrs['sampling_frequency'] = 10000000
            channel0001_group.attrs['voltage_range_mV'] = 80
        
            # Save array1 to channel0001/timeseries dataset
            channel0001_group.create_dataset('timeseries', data=array1[start_idx:end_idx], chunks=True)

            if array2 is not None:
                # Create channel0002 subgroup if it is a calibration dataset
                channel0002_group = timeseries_group.create_group('channel0002')
                channel0002_group.attrs['file_first_sample_index'] = 100000000000000
                channel0002_group.attrs['input_coupling'] = 0
                channel0002_group.attrs['input_impedance_ohm'] = 50
                channel0002_group.attrs['sampling_frequency'] = 10000000
                channel0002_group.attrs['voltage_range_mV'] = 80
        
                # Save array2 to channel0002/timeseries dataset
                channel0002_group.create_dataset('timeseries', data=array2[start_idx:end_idx], chunks=True)
        
            print(f"HDF5 file '{indexed_file_name}' created successfully.")