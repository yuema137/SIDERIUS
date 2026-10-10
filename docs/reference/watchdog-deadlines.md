# Watchdog deadline policies

## Owners and default

`core/runtime_control/watchdog_deadline.py` selects the elapsed-time deadline
for one training or inference subprocess. `WatchdogConfig` in `session.py`
owns its validated configuration. `RuntimeWatchdogDeadlinePolicy` declares the
selection vocabulary. Phase launch and supervision own enablement, polling,
termination signals, descendant cleanup and timeout reporting; those mechanisms
are unchanged.

The API watchdog default is disabled. Standard workflow launch retains its
existing CLI/profile enablement resolution. Whether enabled explicitly or by a
selected hardware profile, the default deadline policy is `budget-ceiling-v1`.
Profile safety factors do not implicitly select the legacy algorithm.

## Deadline semantics

| Policy | Deadline | Evidence and floor |
| --- | --- | --- |
| `budget-ceiling-v1` | Minimum of supplied watchdog budget, outer operator budget and emergency phase ceiling | Does not read predictions; does not apply a floor |
| `forecast-tightening-v1` | Original minimum of outer operator budget, emergency phase ceiling and eligible measured forecasts times the effective factor, then the floor | Explicit opt-in to the old algorithm, including partial-evidence behavior when no outer budget exists |

All times are seconds from subprocess start, not additional time after a
measurement. Native enabled execution requires at least one finite explicit
ceiling. Missing or nonfinite ceilings fail configuration validation; they do not
become unlimited execution or an inferred deadline. A disabled watchdog needs no
ceiling. The emergency ceiling is a valid explicit bound even without an
admission budget.

A native 5-second ceiling remains 5 seconds even if `floor_seconds=60`.
An explicit legacy policy can raise the selected ceiling to its floor; select
native policy when the declared ceiling must govern. The supervisor begins
termination at its polling boundary; grace and cleanup may extend total wall
time. Neither policy promises instantaneous termination.

## Budget transport and admission separation

`WatchdogConfig.budget_seconds` carries the resolved phase budget independently
of admission. The tuner populates it for enabled native execution from the same
resolved `chosen_time_budget` that includes any already-authorized Formal
adjustment. Forecast admission can leave the outer
`RuntimeControlPolicy.operator_budget_seconds` unset while the watchdog still
receives the declared phase budget. No admission calculation or safety factor
changes as a result.

Direct API callers may use the existing outer budget, the new watchdog-only
budget, or an emergency `max_phase_seconds`. Multiple supplied ceilings all
constrain native execution. Legacy selection rejects a non-null
`watchdog.budget_seconds`, because its old algorithm does not consume that field.
The optional field is omitted when null; the selected deadline policy remains
explicit in executable policy JSON. Loading that JSON must not silently select
a different algorithm.

Both launch CLIs expose `--runtime_watchdog_deadline_policy`; API and workflow
configuration use `runtime_watchdog_deadline_policy`; the multi-round chain
forwards the same flag. Tuner startup validates budgets for reachable Trial and
Formal modes through the existing shared mode-resolution rule, before setup or
LLM calls. Unused phases do not require a budget. A possible later Formal
extension cannot substitute for a missing base budget. Existing phase budget and
emergency ceiling options retain their roles. The validated policy follows the
existing runtime-policy JSON path into execution and runtime observations; no
parallel subprocess flag or policy file is introduced.

## Resume and paper compatibility

Enabled runs lock the effective deadline-policy selection. Disabled runs have no
active selection to lock. An enabled old workspace without that identity cannot
silently resume under the corrected policy. Keep old evidence unchanged and
select the intended policy in a new workspace.

Historical selections and any historical prompt projection belong in exp.
The four paper tasks explicitly disabled the watchdog; correcting enabled
semantics does not activate it for them. Nevertheless, added policy metadata can
change a historical prompt. Qualify experiment-owned rendering against the new
source before claiming exact message compatibility. Do not remove the selected
policy from executable JSON merely to recover old prompt formatting.

## Validation boundary

Offline regressions replay the three reported premature deadlines, explicit
legacy behavior, small and large ceilings, missing bounds, serialization,
launch transport and resume conflicts. Short CPU subprocess tests check progress
past an underestimated forecast and termination of an actual overrunning process
group. These are deterministic policy/supervision checks, not evidence of GPU
performance, training quality or stochastic artifact reproduction.
