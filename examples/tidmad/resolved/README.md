# `resolved/` — READ-ONLY resolved snapshots (GENERATED — DO NOT EDIT)

**GENERATED · DO NOT EDIT · the runtime does not read this file.**

Every file in this directory is a resolved SNAPSHOT of what SIDERIUS
production already derives for the TIDMAD task, written by
`tools/example_packs/projection.py`. It is a projection for humans, never a
second authority (roadmap §22.23.1):

- **The runtime does not read these files.** Editing them changes nothing at
  run time. To change the task, edit the OWNING path listed below.
- **CI regenerates and deep-compares them**
  (`tests/unit/examples/test_tidmad_projection.py`). If an authority changes
  intentionally, regenerate in the SAME commit:

  ```bash
  .venv/bin/python -m tools.example_packs.projection
  ```

| snapshot | generated from (owning authority) |
|---|---|
| `dataset_profile.json` | execute_tools/dataset_config.py (`resolve_dataset_profile`, `TIDMAD_PROFILE`) |
| `model_io_contract.json` | configs/task_config.yaml `forward_contract.model_io` via workflows/task_config.py (`run_bound_model_io_contract`) |
| `deliverable_spec.json` | execute_tools/deliverable_spec.py (`derive_tidmad_deliverable_spec`) |
| `metric_spec.json` | execute_tools/evaluation_metric.py (`derive_tidmad_metric_spec`) |
| `identity.json` | execute_tools/dataset_config.py (`DatasetConfig` file patterns / `num_files`) |

Migration rule (design §3.6): when a later Step introduces a real,
user-editable task binding for this pack, these snapshots must not coexist
with it as a second authoritative-looking config.
