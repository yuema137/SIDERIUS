# Task-dependent setup settings contract

## Entry and scope

`check_task(TaskCheckRequest)` accepts `resolve_task_settings=True`;
`python -m tools.setup_review.check_task` exposes `--resolve-task-settings`.
False is the default and is omitted from serialized requests. The ordinary
declaration inspector never invokes the child, and ordinary launchers never
require these reports. Only fresh standard single-iteration requests are supported.

`inspection.inspect_parsed_declaration` returns the declaration and its one fresh,
normalized argparse Namespace. `inspect_declaration` retains its declaration-only
return. Parent argument normalization, advice, launch identity and LLM configuration
resolution happen once; the child never reparses argv or reloads advice/LLM files.

`task_settings_inputs.project_task_settings` constructs `TaskSettingsInputs` from
that parse and saved typed LLM settings. It defines no launch defaults. Nonempty
explicit Health paths are made absolute against the request working directory;
None and empty-string owner defaults are retained. External Health source roots
require explicit read-only exposure. Data/source overlap remains refused.

## Child and production owners

The optional inputs enter the existing `CompositionJob`, whose digest binds the
serialized values. None is omitted, preserving composition-only job bytes.
After composition and planner-provider identity resolution, the child enters the
composed code package and calls `task_settings_child.resolve_task_settings`:

1. `validate_formal_launch` checks declared mode/authority, role/action agreement
   and the enabled formal-delta policy.
2. DataScope resolves against the task's real partition count. The existing
   `validate_scope_settings` checks partial-scope/formal-strategy compatibility,
   the declared file-index topology capability and required monitored-file list.
   Only the existing dataset-profile context is bound for that guard. No fake
   physical data root or whole-run initialization is needed.
3. `resolve_analysis_binding` resolves the treatment against the actual task
   binding. `standard_llm_routes` projects routes using that resolved boolean.
4. Enabled Health uses `materialize_effective_config` with actual task binding,
   scope, monitored files and partition count. Its output is written below
   `scratch/task-settings`; the child reads that known artifact through the
   Health loader. Resolved gates, stored binding/plugin identities and canonical
   body SHA are returned. Disabled Health has no config or digest.

The two pure workflow decisions live in `workflows.task_settings`; the ordinary
workflow invokes them at its previous control-flow positions. Existing private
analysis/topology names remain aliases in model_exploration. This is shared rule
ownership, not a second workflow or scientific policy. The extracted module is
included in the existing estimator assembly source closure. Source identity
changes even though decision behavior is preserved; exp qualifies historical
estimators explicitly rather than bypassing the assembly guard.

## Numeric fidelity

The runtime deliberately ignores `skip_formal_min_delta` and
`bypass_formal_time_budget_min_delta` when formal gates are disabled. Their
task-settings transport is a finite strict float or the exact JSON string token
`nan`, `+inf`, or `-inf`. Parameter rows use the same encoding for those two fields
only. `decode_formal_delta` restores the number once before the actual validator;
enabled gates still refuse nonfinite numbers. Tokens have distinct job digests,
never JSON null, a replacement zero or nonstandard bare JSON Infinity.
Other preview nonfinite-value checks remain unchanged.

## Results, failures and boundaries

`CompositionResult.task_settings` is optional and omitted when absent. Requested
successful checks require that summary; transport refuses a passed result whose
presence does not match the request. A settings exception yields a task_settings
failure, retaining the already-composed task facts. Existing timeout, known-path
no-follow/nonblocking reads, byte bound, identity matching and write-once report
publication remain unchanged. Parent code never follows child-returned paths.

HTML names the resolved scope, analysis routes and each Health gate, with complete
technical values in a details section. The original declaration page remains a
declaration snapshot. Requested-but-failed resolution is distinct from completed
Health materialization. Neither means Health evaluation or training occurred.

Semantic review consumes these saved facts through its inert projection, even
after scratch/source removal. Packets with task settings use setup-review/v2;
previous composition-only packets retain v1. The allowlist includes scope,
analysis, Health enablement, gate role/cadence/actions and typed routes. Arbitrary
Health parameters, plugin source, reasons and wrappers are excluded.
V2 keeps earlier declaration-stage limitations under
`historical_declaration_limitations`. Its current `unresolved` list reflects the
completed task-settings check while retaining hardware, data, authentication,
budget and launch-freshness limitations. V1 packets remain unchanged.

Hardware/watchdog resolution, data loading/split verification, authentication,
resource measurement, future agent-selected values and report-to-launch freshness
remain unresolved. No hardware names or local host profiles are inferred. The
existing sandbox exposes only declared source/runtime roots; trusted factories
can read/print those files. Child timeout and result byte bounds are not whole-host
memory/disk quotas or a hostile-code security guarantee.
