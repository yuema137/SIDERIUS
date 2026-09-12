# `examples/synthetic_masked_regression/declared/`

Task-owned declarations bound by [`configs/task_composition/synthetic_masked_regression.yaml`](../../../configs/task_composition/synthetic_masked_regression.yaml):
[`task_config.yaml`](task_config.yaml) owns the `[B,3] → [B,1]` forward
contract and masked supervision note; [`dataset_profile.json`](dataset_profile.json)
owns shard topology; [`metric_masked_mse.json`](metric_masked_mse.json) and
[`metric_masked_mae.json`](metric_masked_mae.json) declare lower-is-better
metrics; [`task_health.yaml`](task_health.yaml) binds the task Health view and
gate roster. These declarations are example inputs, not framework defaults.

Generated data and run artifacts belong in a caller-owned workspace. Pack
coverage is checked by [`test_synthetic_masked_regression_pack.py`](../../../tests/unit/examples/test_synthetic_masked_regression_pack.py).
