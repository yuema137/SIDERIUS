# Bounded HDF5 reads

External task adapters can use `execute_tools.hdf5_reader.HDF5ReadCache`
for repeated small selections from immutable HDF5 datasets. The reader retains
**dataset** handles, because retaining the file alone does not retain each
raw chunk cache. Each cache holds at least one uncompressed chunk, derived from its
actual geometry and dtype. A preferred 8 MiB working cache also accommodates
multiple small chunks touched by multidimensional selections; it is clipped
to the shared byte budget. The default per-reader budget is 64 MiB and at most
16 open datasets; least recently used entries are closed before either bound
would be exceeded. These are process-local bounds, so loader workers multiply
the configured budget.

```python
from execute_tools.hdf5_reader import HDF5ReadCache

reader = HDF5ReadCache()
try:
    values = reader.read(file_path, dataset_name, slice(start, stop))
finally:
    reader.close()
```

The caller owns selection, ordering, encoding, tensor conversion and source
identity. The reader never widens a selection or casts returned values. It
resets open handles after fork; pickling transfers configuration only. Inputs
must remain immutable while their handles are cached. Instances are not
thread-safe. Returned arrays, HDF5 metadata and compression-filter scratch buffers are
additional to the raw-cache budget; this is not a total process-RSS bound. Variable-length data uses no raw cache because dtype.itemsize cannot
bound decoded elements.

If a chunk is larger than the entire budget, a RuntimeWarning names the file,
dataset, chunk bytes and budget. Access remains correct but uncached. Increase
the explicit budget or coalesce reads at the task adapter without changing
selected examples. This warning occurs on the first read, before a long pass
silently repeats that expensive access. It is not an automatic scientific
scope change or a global h5py monkeypatch.
