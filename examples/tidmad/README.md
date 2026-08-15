# Example pack — `tidmad` (Track A: SQUID / TIDMAD time-series denoising)

The original SIDERIUS scientific task, projected as a user-facing example
pack (roadmap `docs/design/siderius_generic_framework_upgrade.md` §22.9 Track A,
§22.23.2). It is the persistent scientific-compatibility control: every later
Step keeps its strongest Stage-A evidence on this task.

## Task

Full-spectrum 1-D time-series denoising of SQUID dark-matter detector data
(ABRACADABRA / TIDMAD): map a noisy `[B, T] int64` signal to a clean
`[B, 256, T] float32` per-timestep class reconstruction, decoded by argmax.

| aspect | value | owning path (edit THERE, never here) |
|---|---|---|
| task description / forward contract | prose + `model_io` declaration | `configs/task_config.yaml` (single runtime task authority; Steps 03/04) |
| model I/O contract | `[B, T] int64 → [B, 256, T] float32`, `class` axis fixed 256 → categorical | `configs/task_config.yaml` → `workflows/task_config.py::run_bound_model_io_contract` |
| dataset profile | 20 validation files, 200 × 10 000 000-sample segments per file, 10 MS/s, `channel0001` input / `channel0002` truth, int8 storage +128 offset, 256 classes | `execute_tools/dataset_config.py::TIDMAD_PROFILE` / `resolve_dataset_profile()` |
| deliverable | per-file HDF5 `abra_validation_denoised_{file_index:04d}.h5` | `execute_tools/deliverable_spec.py::derive_tidmad_deliverable_spec` |
| golden metric | `tidmad_denoising_score` · direction **higher** · anchor-normalised linear grand mean, log base 5.27 (frozen paper-comparable formula) | `execute_tools/evaluation_metric.py::derive_tidmad_metric_spec` (arithmetic in `execute_tools/scoring_utils.py`) |
| health policy | HealthGate checks at tuner round boundaries | `configs/health_checks.yaml` (applicability semantics: Step 08) |
| data root | machine-local, gitignored `tidmad_data_config.yaml` | `execute_tools/data_paths.py` — see `data/README.md` |
| reference artifacts | anchors, raw baseline, ground truth, official paper scores | `reference_data/` |

## What this pack demonstrates at PR0

`resolved/` holds **READ-ONLY resolved snapshots** of the five contracts above
(`dataset_profile`, `model_io_contract`, `deliverable_spec`, `metric_spec`,
`identity`), **GENERATED** from the production authorities by
`tools/example_packs/projection.py`. **DO NOT EDIT them — the runtime does not
read these files.** To change the task, edit the owning path in the table;
CI (`tests/unit/examples/test_tidmad_projection.py`) regenerates every
snapshot and deep-compares it, so a drift is a red test resolved by
regenerating in the same commit as the authority change
(`.venv/bin/python -m tools.example_packs.projection`).

The task description, forward-contract prose and health config are
**referenced**, not copied: their owning YAML files are the authority and a
copy here would be the parallel authority roadmap §22.23.1 forbids.

## Running the task

Runs go through the normal SIDERIUS interfaces documented for operators
(`README.md` at the repository root, `docs/running_chain_test.md`,
`scripts/run_comparison.py`); this pack does not add a launcher — see
`STATUS.md` for what is and is not projected here yet.

## Files

```text
README.md          this file
PROVENANCE.md      data source, licence, reference artifacts, data-root mechanism
STATUS.md          honest maturity + the seams not yet projected (mirror of the roadmap)
data/README.md     how the machine-local data root is configured (no data here)
resolved/          GENERATED read-only snapshots + DO-NOT-EDIT banner
```
