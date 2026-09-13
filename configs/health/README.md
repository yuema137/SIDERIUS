# configs/health

The generic default is packaged with `execute_tools.health_checks`; omit
`--health_checks_config` to use it. The old `configs/health/health_checks.yaml`
path was removed. Code needing its location calls
`execute_tools.health_checks.config.default_health_policy_path()`.

This directory retains only the optional
[`health_checks_baseline_observe_mode.yaml`](health_checks_baseline_observe_mode.yaml).
Select it explicitly with `--health_checks_config /absolute/path/to/policy.yaml`
and declare `--healthgate_mode observe_only --result_authority diagnostic`.
The mode flag alone does not select a file. Installed users supply their own
external policy; do not edit site-packages. Task rosters and thresholds remain
in the task manifest's Health declaration. See
[`Health gates`](../../docs/concepts/health-gates.md).

See [the parent guide](../README.md) for child ownership and the focused validation route.
