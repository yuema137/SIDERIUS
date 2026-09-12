# configs/health

Framework Health consequence policy lives in [`health_checks.yaml`](health_checks.yaml)
and [`health_checks_baseline_observe_mode.yaml`](health_checks_baseline_observe_mode.yaml).
The loader is `execute_tools.health_checks.config`; task rosters and thresholds
come from the task manifest. See [`Health gates`](../../docs/concepts/health-gates.md).

See [the parent guide](../README.md) for child ownership and the focused validation route.
