# Provenance — `tidmad`

## Data source

- **Dataset / paper**: *TIDMAD: Time Series Dataset for Discovering Dark
  Matter with AI Denoising* — J. T. Fry, X. H. Fu, Z. Fu, K. M. W. Pappas,
  L. Winslow, A. Li. arXiv: <https://arxiv.org/abs/2406.04378>.
- **Official distribution**: the paper's repository
  <https://github.com/jessicafry/TIDMAD> (its `download_data.py` /
  `filelist.dat` retrieve the HDF5 files from the OSDF caches). The repository
  states that both the TIDMAD dataset and the associated software are licensed
  under **CC BY 4.0** (verified 2026-08-15 from the repository README; consult
  the source for the authoritative current terms).
- **Files SIDERIUS reads**: `abra_training_{file_index:04d}.h5` and
  `abra_validation_{file_index:04d}.h5`, `file_index` 0–19 (see
  `resolved/identity.json`, generated from the profile's file patterns).

Raw data is NEVER committed to this repository (roadmap §22.23.10). Nothing in
`examples/tidmad/` fetches it.

## Machine-local data root (reference, no path recorded here)

The data directory is configured per machine in the gitignored
`tidmad_data_config.yaml` (template `tidmad_data_config.example.yaml` at the
repository root; keys `tidmad_data_dir`, `siderius_data_dir`), read by
`execute_tools/data_paths.py`. The launcher validates the directory before any
spend. Whether D14 generalizes this mechanism for the contrast packs is D14's
source-audited decision (roadmap §22.23.0).

## Frozen reference artifacts (already tracked under `reference_data/`)

| artifact | path | role |
|---|---|---|
| segment anchor map | `reference_data/segment_anchors.json` | scoring normalisation (`s_max` per anchor) |
| raw baseline | `reference_data/raw_baseline/` | metric floor (no denoising) |
| ground truth | `reference_data/ground_truth/` | metric ceiling |
| official paper-model scores | `reference_data/official_paper_result/README.md` | paper comparability |
| paper-spec baseline configs | `ml_models/legacy_baseline_configs.json` | paper-aligned hyperparameters |
| signal frequencies | `reference_data/tidmad_signal_frequencies.txt` | injected-signal reference |

## Snapshots in `resolved/` — provenance

Generated at PR0 (2026-08-15) from the production authorities named in
`resolved/README.md` by `tools/example_packs/projection.py`; each is
regenerated and deep-compared by `tests/unit/examples/test_tidmad_projection.py`.
They carry no independent provenance of their own — their provenance IS the
owning path.
