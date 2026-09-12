# `examples/quickstart/declared/`

Task-owned declarations bound by [`configs/task_composition/quickstart.yaml`](../../../configs/task_composition/quickstart.yaml):
[`task_config.yaml`](task_config.yaml) defines the description and forward
contract, [`dataset_profile.json`](dataset_profile.json) defines topology,
[`data_manifest.json`](data_manifest.json) pins generated shard identity, and
[`metric_accuracy.json`](metric_accuracy.json) declares the primary metric.
The framework reads these through composition; they are not generic defaults.

Only the generated data and run artifacts belong in an external caller-owned
workspace. The pack's integrity checks are in
[`test_quickstart_pack.py`](../../../tests/unit/examples/test_quickstart_pack.py).
