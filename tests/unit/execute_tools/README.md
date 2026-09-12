# tests/unit/execute_tools

Execute-tools unit tests pin metric arithmetic/order, dataset scope, scoring,
training sentinels, and declared deliverables using synthetic data.

## Focused route

`.venv/bin/python -m pytest tests/unit/execute_tools/test_accuracy_metric.py -q`

Owner: `src/execute_tools/`; no provider, GPU, or live training is implied.
`goldens/` preserves ordering/resolution outputs and `step12_pr12e_fixtures/`
preserves health/metric chain inputs; higher-level execute-tools tests consume
both without treating them as fresh results.
