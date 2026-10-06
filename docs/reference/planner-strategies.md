# Planner strategy providers

Status: issue #372 implementation and targeted offline verification complete.
The experiment-owned package records the controlled TESS comparison and scoped
paper prompt checks. These do not claim full historical scientific replay.

## Ownership and selection

The framework owns execution constraints, timing-fact transport, provider
loading, and run identity checks. The experiment repository owns historical
search strategies and their default declarations. Providers supply planner
prompts; they do not alter scoring, parameter validation, execution, or the
reflector.

`LLMBridge.plan(planner_strategy=...)`, `HyperparamTuningInput.planner_strategy`,
and `WorkflowLLMConfig.tune.planner_strategy` select the same provider. The
standalone tuner exposes `--planner_strategy`. Workflow callers use their
`--llm_config` JSON; selection travels through `local_validated_model`.

- `native-timing-v1` explicitly selects the framework's timing-aware renderer.
- Other explicit names resolve through installed Python entry points in
  `siderius.planner_strategies`.
- Omission resolves exactly one entry point in
  `siderius.planner_strategy_defaults`. There is no inferred scientific default.
- Missing or ambiguous providers refuse before the planner request. Discovery
  never downloads or installs anything. Install the experiment's declared
  compatibility distribution, or explicitly select an available provider.

An explicit selection bypasses default discovery. The default is a deployment
choice, not an inference from task names or prior scores. Providers are trusted
installed Python code, with the same trust requirements as other task plugins.
The framework's `configs/llm/*.json` examples explicitly select
`native-timing-v1`; they do not require an installed experiment package.

## Provider interface

An entry point is a zero-argument factory returning
`agent.planner_strategy.PlannerStrategy`. Its fields are:

| Field | Contract |
| --- | --- |
| `identity` | `PlannerStrategyIdentity`: provider name, version and content SHA-256 |
| `system_template` | Planner system template using the existing task substitution tokens |
| `user_renderer` | Callable accepting the planner rendering keyword arguments and returning text |
| `uses_timing_context` | Whether the renderer accepts the new `timing_context` keyword |
| `task_renderer` | Optional transformation of task description using supplied timing context |
| `system_renderer` | Optional `(system_template, TunerTaskRender) -> str` transformation before shared fact substitution |

The compatibility provider uses `task_renderer` to preserve the original
agent-owned Formal appendix. It must not add the new timing section and claim
byte-compatible historical prompts. The reflector continues on its existing
path. The compatibility provider also uses `system_renderer` to render its
archived conditional loss strategy from the supplied task facts. Its archived
helper is owned and fingerprinted by exp; the framework supplies only native
loss eligibility text and does not carry legacy search or recovery advice.
The bridge calls the provider transformation before substituting task/metric
facts; a non-string result refuses before the provider request.

Providers fingerprint their implementation and helper sources. The framework
adds `assembly_sha256` for the shared planner assembly and rendering source
files. Fingerprints use labelled bytes rather than installation paths. The
assembly hash is deliberately conservative: some neighboring rendering edits
can require a new workspace even when a particular prompt would be unchanged.
The assembly hash covers `llm_bridge.py`, `prompts.py`, the provider loader,
`timing_attribution.py`, and the tuner prompt-template directory. It does not
cover upstream timing-fact producers or every schema/default dependency. Use
the exact qualified infra revision as well; this hash is not a full-framework
reproducibility fingerprint. These hashes do not replace pinned environment dependencies, task composition
identity, or archived final prompts. Installed code must remain immutable while
its process is running; hot reloading is unsupported.

## Run and resume contract

Startup records the resolved identity as the canonical
`planner_strategy_identity` field in `run_invariants_lock.json`. Workflow
preflight, workflow execution and the standalone tuner resolve their declared
selection. The tuner also passes the startup identity to `LLMBridge.plan` as
`expected_planner_strategy`; mismatch refuses before its provider call.

A previous lock without this field remains readable as historical evidence.
It does not authorize a pinned run in that workspace. The ordinary invariant
comparison refuses the missing-versus-present identity without modifying the
old lock. A changed provider digest or shared assembly digest likewise refuses
resume. No implicit lock upgrade is performed.

Migration must use a new workspace and an independently verified experiment
migration record. Retain the original workspace, receipts and revision pins.
Missing provenance is not replaced with the installation default. An
unverified historical run remains on its original infra revision. The migration
export/import procedure and all historical bindings remain qualification work;
there is no automatic migration command in this change yet.

Direct bridge callers may omit `expected_planner_strategy`; they then have no
workspace resume guarantee. They may omit `timing_context`; the native renderer
explicitly reports incomplete constraints and never infers unknown controls to
be adjustable.

## Timing facts

The tuner builds `PlannerTimingContext` from existing owners. It describes
supplied overrides, task/workflow parameter rules, candidate roles, epoch
ceilings, role workload sources, selected winner inheritance and its recovery
exceptions, partial-scope normalization, and validation/cooperative settings.
The source and inheritance helpers are shared with execution. Building context
does not select a winner, construct a speculative plan, or execute a plugin.

This is bounded timing information, not a proof that all model/plugin inputs
are feasible. Execution still validates the authored plan and applies the
existing precedence. An epoch ceiling is not a fixed epoch assignment, and
absence from `plan_overrides` is not proof of freedom after downstream rules.

## Evidence and limitations

Focused tests cover discovery refusal, explicit selection, lock immutability,
preflight-to-provider checking, role-source parity, and real tuner-to-bridge
transport with an offline provider recorder. Separate historical captures
compare final system/user bytes; they are not API calls or scientific runs.

The pending experiment-owned qualification must distinguish source preservation,
final prompt parity, archived-response replay, and fresh stochastic reruns.
Equal prompts cannot guarantee equal new LLM responses or GPU results. No
scientific score improvement is an acceptance condition for issue #372.
