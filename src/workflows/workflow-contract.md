# `workflows/` — deterministic graph traversals + task composition

Technical inventory for this module. Start with [the directory guide](README.md)
for navigation. Source and tests determine current behavior.

## Purpose

The pre-designed, deterministic paths through the node graph, and the
task-composition manifest that binds a whole run to one task's declarations.
A workflow is a script with a fixed sequence — *"a workflow, not an
orchestrator"* — never an agent choosing its own tools. This package contains
no shell entrypoints: the chain launchers live in
  [`scripts/launch/`](../../scripts/launch/README.md), which call
into here one iteration at a time.

## Public interface

| file | surface |
|---|---|
| `model_exploration.py` | `run_workflow(*, launch, workspace, run_name, …) -> list[HyperparamTuningOutput]` — THE workflow: per iteration interpret → workflow-selected scientific evidence stage → propose → implement → validate → tune. Also a module CLI (`python src/workflows/model_exploration.py --help`) accepting `--task_composition` |
| `scientific_evidence_stage.py` | Workflow-owned optional traversal of the independent Data Analysis and Literature Review capabilities in either `analysis_then_literature` or `literature_then_analysis` order. Nodes never call each other. |
| `task_composition.py` | `compose_run_task_bindings(manifest_path) -> RunTaskComposition` (resolve the manifest) · `bind_run_task_composition(composition, *, physical_data_root)` (the run-scoped binding contextmanager) · `verify_composition_is_bound` · `active_composition_fingerprint` / `active_task_manifest_path` |
| `plugin_staging.py` | Internal `stage_native_plugins(ImplementorOutput, model_name, dest_plugin_dirs, dest_loss_dirs=None) -> None`: model/loss staging composition using native copy/binding/registration owners |
| `tuner_preparation.py` | Internal `prepare_native_tuner_input(...) -> HyperparamTuningInput`: native launch/bindings/iteration context projection into the validator-to-tuner protocol |
| `run_config.py` | `WorkflowLaunchConfig` — the pure-transit launch config |
| `llm_config.py` | `WorkflowLLMConfig` — per-node LLM routing, loaded from a `--llm_config` JSON |
| `run_bindings.py` | `WorkflowRunBindings` — run-scoped authorities settled at startup; refuses mutable chain state by construction |
| `strategy_modes.py` | the `Literal` vocabularies for exploration/strategy/formal-round modes |

## Inputs

`workspace` + `run_name`; a `WorkflowLaunchConfig`; a required composition
manifest (with a **mandatory** `--data_dir`); LLM routing
JSON; a `RestoredState` when resuming; pseudo-mode factories for $0 smokes.

## Outputs

A list of `HyperparamTuningOutput`; the workspace record tree
(`{workspace}/{run_name}/…` — layout in
[workspaces and resume](../../docs/guides/workspaces-and-resume.md)); the run
invariants lock and effective health config (written via `core` /
`execute_tools.health_checks` authorities at startup).

## Owned semantics

- **The fixed iteration path** and its retry loop (proposal attempts, tuner
  invocation, record persistence).
- **Scientific-evidence composition**: `WorkflowLaunchConfig.scientific_evidence_order`
  selects which independent capability runs first. Typed target-owned edges
  carry bounded evidence to the second capability, and Proposal receives
  Literature Review and Data Analysis through distinct fields. The order is
  canonical run identity and changing it refuses resume into the same workspace.
- **Data Analysis treatment transport**: `data_analysis_enabled=None` retains the
  task composition's legacy behavior. Explicit `True` requires its existing
  analysis binding; explicit `False` suppresses both AnalysisBrief generation
  and the analysis stage. The launch value is canonical resume identity and
  does not create asset authority or a second experiment treatment schema.
- **Manifest resolution**: the typed composition schema owns section names and
  requiredness; an unknown key is *refused, not ignored*; `file:` plugin refs
  resolve against the manifest's own directory and their content sha joins the
  semantic fingerprint.
- **Run-scoped binding**: a composed run binds data path, profile, metric,
  secondaries, deliverable naming, task config for the whole run; an
  explicitly composed run **never falls back to TIDMAD**.
- Plugin registration and generated sources are rooted in the caller-owned
  workspace (`plugins/{run_name}/` and its generated-library paths); the
  workflow does not make the checkout a hidden task workspace.

## Candidate request enrichment

`candidate_requests.enrich_implementation_request` and
`enrich_validation_request` mutate already constructed native requests in place.
They accept typed, resolved values and perform no I/O, task resolution, provider
construction, request cloning or post-assignment validation. They are shared
request-enrichment helpers, not a graph executor or complete request builder.

The caller retains the ordering: create attempt storage; call `local_full_spec`
(the proposal-to-implementation field-mapping authority); assign plugin, test
and loss directories; load task configuration, description, `ForwardContract`
and implementor blocks through their existing owners; then enrich the request.
Protocol/storage failures therefore precede task-resolution failures. Candidate
identity, custom loss and task-composition reference remain protocol-owned.
The validator caller similarly calls `local_all_fields` first; model I/O and
probe context travel from the implementor through that protocol. Validator
routing stays in both the protocol arguments and agent constructor.

Implementation enrichment assigns resolved task/hardware/budget fields,
including absent optional values. Advice and prior validation failure overwrite
only when not `None` (an empty string is an explicit value); reference code
replaces only when nonempty. Validation advice follows the same `None` rule;
lineage replaces only when nonempty. Helpers do not mutate upstream proposal or
implementation outputs. Retry sequencing, failure feedback, artifact ownership
and capability admission remain in the workflow. An alternative caller must
establish those authorities itself before invoking the helpers.

The preflight estimation assembly includes both the workflow and the extracted
helper's source. A changed assembly changes the task composition fingerprint;
this extraction does not authorize resuming a workspace with an older identity.
Historical estimator profiles must explicitly qualify the selected assembly.
Prompt-render parity on frozen inputs does not establish full historical replay.

## Native tuner input preparation

`prepare_native_tuner_input` consumes typed validator/proposal outputs, tuner
storage, `WorkflowLaunchConfig`, established `WorkflowRunBindings`, the existing
`RunInvariants` object, current constraints and the formal incumbent. It calls
`local_validated_model` once with explicit named arguments; that protocol remains
the node-output mapping authority. Standard tuner routing uses the existing
resolver, including its distinction between omitted and empty tuner blocks.
Missing routing bindings violate the existing startup precondition; no fallback
configuration is invented. Transit-only portions restore schema-derived defaults;
`frozen_portion_overrides` still owns executed portion locks and conflicts.

The helper forwards the original operator Health source, including `None`,
measurement capability, task projection and lock-derived identities. It then
conditionally replaces human advice and loads/renders the bound task description.
Protocol failures precede advice enrichment and task loading; exceptions propagate.
The helper does not stage files, promote capabilities or execute an agent.
`run_workflow` calls it after admission, capability commit, dual staging and early
loss/model promotion, immediately before tuner construction and execution. Late
loss promotion and infrastructure-abort handling remain workflow-owned.

Both this helper and the orchestrator belong to the preflight estimator assembly.
Relocation therefore changes the real estimator assembly and task composition
fingerprint; old locks/reuse and unqualified historical profiles may refuse.
No identity is frozen or migrated, and no historical profile is qualified by
input mapping tests. Professional Python/CLI and reviewed Assistant launches
continue through `run_workflow`; GUI candidate execution remains three-node.
This internal boundary alone does not provide candidate-worker training.

## Native plugin staging

`plugin_staging.stage_native_plugins` owns the native model/loss staging
composition. `run_workflow` constructs the destination lists (tuner first,
chain second) and calls it once after admission and capability commit, before
early loss/model promotion and tuner input preparation. Caller-owned destinations
and successful staging do not establish training readiness or launch a tuner.
The module is independently importable without the workflow orchestrator.

Generated loss name validation precedes model staging. Existing
`stage_model_source` retains declared package source or copies a generated model
and forensic sentinel, then copies descriptions. Missing model source returns
before any loss or model registration; missing description only warns. Generated
losses copy to each supplied loss destination and register from the first file,
with the original contract snapshot, before model registration from its primary
source. Reused/builtin losses skip propagation. Missing loss source warns and
model registration continues. Native registrars retain their registry authority.

Copy and loss-registration exceptions propagate with prior partial effects.
Ordinary thrown model-registration errors warn; package failures rethrow. A normal
loader `None` remains distinct from an exception. No rollback or destination
validation is added: empty model destinations may still stage loss; a present
generated loss with empty loss destinations raises `IndexError` after model
staging. These unsupported inputs retain their existing behavior.

The staging module joins the estimator source assembly, alongside the still
covered orchestrator. Assembly and derived composition/run-lock identities change;
name/version/arithmetic and scientific defaults do not. Frozen staging effects
and N1 non-identity input payloads remain unchanged. Historical external profiles
still require final-pair qualification; this extraction does not migrate locks or
prove compatible resume, artifact replay or scientific equivalence.

## Candidate attempt storage and accounting

`attempt_storage.ImplAttemptStorage` and `impl_attempt_storage(attempt_dir,
run_name, impl_attempt)` derive the native `StorageConfig` and model/test/loss
directories from `execute_tools.impl_attempts.impl_attempt_dir`. They create no
files and preserve that owner's one-based numbering and error behavior.
`model_exploration` re-exports both names for existing callers. The workflow
continues to choose the proposal attempt and retry index.

`run_context.bind_agent_run_context(agent, *, workspace, iteration, run_name,
run_id)` dispatches accounting context to an agent's `set_run_context` first,
otherwise to its non-None `bridge`. A missing run name or run ID skips binding,
as before; callers requiring accounting must supply both. Agent-owned binding
preserves proposer lazy stage bridges and tuner deferred brain construction.
The workflow's nested adapter reads its current iteration at each call, so
chain offsets and later iterations retain their original accounting identity.
Neither helper constructs providers, invokes nodes or changes retry behavior.
Both helpers' bytes join the preflight estimation assembly alongside the
previously covered workflow. Historical qualification is still required for the
changed assembly; this source move does not establish a new qualified pair.

## Non-owned semantics

- Node internals → each node's `.md` under [`nodes/`](../nodes).
- Subprocess execution, resource ceilings → `core/sandbox_executor.py`
  ([execution mechanism](../../docs/agent-reference/mechanisms/execution.md)).
- Health policy and gate actions →
  [`execute_tools/health_checks/`](../execute_tools/health_checks/README.md).
- Lock and resume mechanics → `core/run_invariants.py`, `core/resume.py`
  ([persistence and resume](../../docs/agent-reference/mechanisms/persistence-and-resume.md)).
- Metric direction → `execute_tools/metric_order.py` (one authority).

## Extension points

- **A new task never edits this package.** It authors a manifest + out-of-tree
  plugins — see [define a task](../../docs/guides/define-a-task.md) and the
  [composition mechanism](../../docs/agent-reference/mechanisms/composition.md).
- Adding a *manifest section* is a framework change to `task_composition.py`
  with its resolver, fingerprint entry and censuses — not routine.

## State and filesystem effects

Creates `run_dir = {workspace}/{run_name}` and the per-iteration tree; snapshots
the resolved task declaration/effective configuration into the run dir (only if absent); writes the
workflow summary; calls `ensure_run_invariants` (chain-level lock). Sets
`SIDERIUS_CHAIN_WORKSPACE`; mirrors validated plugins into workspace dirs. The
generated library is caller/workspace-owned and must be explicitly bound by
low-level consumers; it is not an implicit inter-run checkout channel.

The direct `run_one_iteration.py` entry (script or module CLI) binds its parsed
workspace before importing the registry-bearing resume/workflow owners in a
fresh process. That excludes implicit legacy checkout model discovery while
preserving selected-workspace plugins and explicit plugin-directory overrides.
Help and missing required arguments return before those imports. Direct
low-level calls and registries already imported in the same process are outside
this startup guarantee. Even configuration inspection can import plugins and
emit their stdout; it is not a sandbox. See the
[one-iteration entry contract](../../docs/reference/entrypoints.md#run_one_iterationpy--one-iteration).

## Reading launch settings without starting the workflow

Configuration tools can import `workflows.literature_config` to resolve a
literature configuration path and hash its exact bytes. Absolute paths are
used directly; relative paths refer to the SIDERIUS checkout, not your current
directory. An installed package without a checkout requires an absolute path.
Calling `lit_review_config_sha256(..., enabled=False)` does not read or hash
that file. Resolving an omitted enable flag may still read YAML to determine
whether literature review is enabled.

`workflows.runtime_settings.resolve_watchdog_policy(args)` resolves the standard
CLI's watchdog settings (the controls that stop work when it exceeds its time
limit). It uses the same hardware/profile authority as the launcher, writes the
resolved values back to `args`, and caches their provenance there. Pass a fresh
parsed namespace to inspect changed settings; reusing one returns its cached
result. An incomplete required-profile declaration or unenforceable phase limit
still refuses the launch.

Importing these modules does not load nodes or the workflow runner. Calling
their helpers may read configuration files and inspect hardware. These helpers
are configuration building blocks, not a complete setup review or a sandbox
for task plugins. They add no review requirement to existing launch commands.

## Failure modes

| refusal | meaning |
|---|---|
| `TaskCompositionError` (unknown key, double ref, missing file) | the manifest is wrong — misspelled sections never silently resolve a default |
| `CompositionDataRootMissing` | composed run without `--data_dir`, before any LLM/GPU work |
| `CompositionNotBoundError` | a code path reached execution without the run-scoped binding — a wiring defect, not an operator error |
| `RunInvariantsViolation` at startup | workspace lock mismatch — use a new workspace |
| literature review enabled without an explicit config | refused by name (`require_lit_review_config_when_enabled`); a task- or experiment-owned config is accepted |

## Files normally edited

Adding a launch-config field (`run_config.py` + the launcher plumbing); LLM
routing shapes (`llm_config.py`). Both are transit layers — validation lives
with the consumer.

## Files normally NOT edited

`model_exploration.py`'s orchestration body: the responsibility-decomposition
rule (CLAUDE.md) forbids adding new branching to it — extract a typed boundary
instead. `task_composition.py`'s fail-closed resolvers and fingerprint: guarded;
weakening a refusal into a fallback is the defect class the guards exist for.

## Minimal example

```bash
# The module CLI is an effectful workflow entry: all of these required inputs
# are supplied explicitly. For a credential-free view of the complete chain,
# use the maintained launcher dry-run in the root README.
.venv/bin/python src/workflows/model_exploration.py \
    --task_composition configs/task_composition/quickstart.yaml \
    --data_dir /tmp/quickstart-data --workspace /tmp/ws --run_name demo_v1 \
    --models punet --source_run_name seed --max_iterations 1
```

For real runs use the chain launcher
([entrypoints](../../docs/reference/entrypoints.md)); start with `--dry-run`.

## Related tests

`tests/unit/workflows/` (incl. the run-state/carrier oracles) and
`tests/integration/workflows/` (pseudo-mode full-loop). The composition
fail-closed behaviour and the findings-union single-authority rule carry
dedicated structural guards.

## Proposal reasoning pipeline

`proposal_pipeline.get_reasoning_pipeline(config, exploration_mode="auto",
minimum_boldness=0.05, n_candidates=None)` owns configured comparison and causal
reasoning stage construction. A `ProposalLLMConfig` activates those stages;
absent legacy proposal configuration returns `None`. The native selection and
research-policy schemas retain their defaults. `model_exploration` preserves
`_get_reasoning_pipeline` as a compatibility import. The preflight source assembly
includes both the workflow and this owner; moving code does not preserve an old
qualified assembly hash.
