# `data/` — TIDMAD data root (nothing is stored here)

No dataset lives in this directory, and nothing in this pack downloads one
(roadmap §22.23.10). The TIDMAD HDF5 files are acquired from the official
distribution named in `../PROVENANCE.md` into a **machine-local** directory
that the framework finds through its existing data-root mechanism:

```bash
cp tidmad_data_config.example.yaml tidmad_data_config.yaml   # at the repository root, gitignored
# edit tidmad_data_dir   -> directory holding abra_training_0000..0019.h5 + abra_validation_0000..0019.h5
# edit siderius_data_dir -> where run outputs are written
```

The keys are read by `execute_tools/data_paths.py`; the chain launcher
validates the directory before any run spends compute. Which files exist and
how they are named is projected read-only in `../resolved/identity.json`
(generated from the profile's file patterns — the authority is
`execute_tools/dataset_config.py`).

Prepared/derived data, caches and run artifacts belong to the workspace
(`--workspace`, default `./siderius_workspace`, gitignored) — never to the
tracked example tree.
