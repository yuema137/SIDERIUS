# `core/` — run-scoped execution infrastructure

Technical inventory for this module. Start with [the directory guide](README.md)
for navigation. Source and tests determine current behavior.

## Purpose

Everything a run needs *underneath* the science: subprocess sandboxing and
memory ceilings, hardware discovery, the run-invariants lock, chain resume,
runtime measurement/admission, and campaign bookkeeping. Nothing here knows
what a task means — task semantics live in
[`execute_tools/`](../execute_tools/README.md) and in task packages.

## Public interface

| file | surface |
|---|---|
| `run_invariants.py` | `RunInvariants` (frozen model) · `build_run_invariants` (the ONE shared construction path — materializes + hashes the effective health config first) · `ensure_run_invariants(workspace, expected)` (create-or-validate, first writer wins) · `validate_stamped_invariants` (ingress check for seeds/restored records) |
| `resume.py` | `restore_prior_state(workspace, current_iter, seed_paths, …) -> RestoredState` · `union_key_findings` (THE findings-union authority) · the digest projections (`project_knowledge`, `project_prediction_memory`, `project_vocab_link_confirmations`, …) |
| `chain_state.py` | `ChainState` — the chain's mutable cross-iteration state; `chain_state_field_names()` feeds the carriers' deny-lists |
| `sandbox_executor.py` | `TidmadSandbox` — the GPU child launch surface: `execute_training`, `execute_inference`, `evaluate_metric`, `execute_scoring`; every child goes through one observed-subprocess seam. Its bytes are part of `verifier_assembly_digest` |
| `stub_sandbox.py` | `StubSandbox(TidmadSandbox)` — the pseudo-mode sandbox, selected only by `--is_pseudo_training`; launches no subprocess and synthesises results from `random.Random(run_id)`. Outside every assembly digest closure, so pseudo-only edits move no paper-facing identity (#1475). Import it from here; `core.sandbox_executor` does not re-export it |
| `execution_calibration.py` | `resolve_role_ceiling(role)` (typed role/value/source) · `resolve_role_ceiling_gb(role)` (compatibility projection: `None` inherits existing OS limits; explicit `0` adds no cap; positive GiB retains the child RLIMIT_AS setter) · `SIDERIUS_SUBPROCESS_RSS_GB` accepts one global integer or complete role mapping; malformed **refuses** · `calibration_provenance()` records configured policy, not measured OS limits |
| `hardware_context.py` | `get_or_create(workspace, run_name)` — discovery + the per-run `{run_name}_hardware.json` manifest; `inspect_gpu_runtime()` — fresh backend/property facts without persistence, under the [accelerator contract](accelerator-runtime.md) |
| `subprocess_env.py` | the one environment a child needs for generated plugin roots and optional captured task-code transport; defaults `PYTHONHASHSEED=0` (an operator-set value is kept) |
| [`local_code/`](local_code/README.md) | finite captured package imports, whole-set identity, verified child transport and named integrity refusal |
| `runtime_control/` | measurement, admission, watchdog, calibration registry, `launch_guard.run_launch_self_test`, estimator/policy identity |
| `server_configs/` | per-server calibration registry (`_base.py` schema; one module per host) |
| `seeding.py` | `RunSeed` · `RunSeedBinding` · `resolve_run_seed` / `generate_run_seed` · `derive_seed` (`siderius-seed/v1`) · `MissingRunSeed`; see the [seeding mechanism](../../docs/agent-reference/mechanisms/seeding.md) |
| `training_seeds.py` | torch-free `SeedContext` · `TrainingSeedPlan` (`init_*`, `epoch(k)` → `EpochSeeds`) · `resolve_trainer_seed_plan` (trainer CLI entry boundary) · `trainer_seed_record`; see [trainer seeding](../../docs/agent-reference/mechanisms/seeding.md#trainer-seeding) |
| `campaign_identity.py` | validates campaign ids, binds campaign state to its identity stamp, and admits campaign homes |
| `runtime_control/campaign.py` | typed C12 validation-campaign matrix, measured cell records, pairwise plans, and campaign verdicts |
| `committed_digests.py` · `memory_probe.py` · `inference_defaults.py` · `scientific_authority.py` | single-purpose authorities (read their docstrings) |

## Inputs

Workspace paths and run names; the environment overrides named above; the
calibration store (default `~/.siderius`, override `SIDERIUS_CALIBRATION_DIR`);
prior-run outputs for resume/seeding.

## Outputs

`{workspace}/run_invariants_lock.json` · `{workspace}/{run_name}_hardware.json` ·
child subprocesses with role-scoped `RLIMIT_AS` · `RestoredState` for the
workflow · calibration observations.

## Owned semantics

- **The lock partition rule**: `_CANONICAL` fields are compared on resume,
  `_PROVENANCE` fields (e.g. the resolved role ceilings) are recorded and
  *never* compared — a resume on a differently-calibrated host stays legal. A
  guard test asserts the two partition every declared field.
- **Role memory ceilings via `RLIMIT_AS`** constrain process address space,
  with one application per execution role. Allocation refusal can be recorded;
  this is not universal protection from kernel OOM or host failure.
- **The findings-union rule** has one authority (`union_key_findings`), called
  by both the digest projection and the loop closure; re-inlining it is the
  defect a mutation-proven structural guard exists to catch.
- **Replay integrity on resume**: a prior iteration whose `run_output` hash
  does not match its manifest stops the chain (`ReplayIntegrityError`).

## Non-owned semantics

- What the children *do* → [`execute_tools/`](../execute_tools/README.md)
  engines; [execution mechanism](../../docs/agent-reference/mechanisms/execution.md).
- What the lock's health hash *means* →
  [`execute_tools/health_checks/`](../execute_tools/health_checks/README.md).
- When gates fire, round policy → the tuner node.
- The workspace layout narrative →
  [workspaces and resume](../../docs/guides/workspaces-and-resume.md).

## Extension points

- A new host: add `server_configs/{hostname}.py` (unknown hosts fall back with
  a one-time warning — only time forecasts are affected).
- Additional address-space cap: `SIDERIUS_SUBPROCESS_RSS_GB`, an operator
  decision. Its legacy name means RLIMIT_AS, not physical RAM/RSS. Omit it to
  inherit OS limits without an additional cap. Use
  one non-negative integer to set every role, or one complete mapping such as
  `training=0,inference=96,scoring=24` when a host needs different ceilings.
  A mapping must name all three roles exactly once; `0` adds no cap for that
  role and does not remove inherited OS restrictions. Numeric validation applies
  to the selected role; provenance resolves and checks all three.
- There is deliberately **one caller-owned override layer**, not a hierarchy
  of global and per-role variables. The role mapping is a value carried by
  that existing layer; do not add another precedence level.

## Pseudo resource admission

`pseudo_admission.resolve_pseudo_admission` resolves all three optional role
ceilings through `execution_calibration.resolve_role_ceiling`; it never discovers
hardware or adds an override layer. `StubSandbox` launches no subprocess, so
pseudo training requires no host ceiling. `PseudoAdmission.decision` records
`pseudo: no execution envelope (StubSandbox launches no subprocess)`.
Omitted and zero declarations are valid. A supplied `SIDERIUS_SUBPROCESS_RSS_GB`
is validated and recorded, but enforces nothing in the stub. Malformed values
retain `MalformedCeilingOverride`; the standard launcher prints `LAUNCH REFUSED`
and exits 2 before workflow setup. Direct preflight callers retain the typed exception.

The pseudo adapter persists the decision and resolved `RoleCeiling` declarations
in `preflight_workers/<label>.json`, under `pseudo_admission`, with outcome
`PSEUDO_NO_EXECUTION_ENVELOPE`. This is not a GPU measurement, model-fit assertion
or parent-process memory enforcement. Real training retains the existing GPU
snapshot and isolated probe.

## State and filesystem effects

Writes the lock and hardware manifest into the workspace; appends calibration
observations under `~/.siderius` (host-global by design); spawns process-group
children. `StubSandbox` is the pseudo-training stub — no GPU, canned results.

## Failure modes

| refusal | meaning |
|---|---|
| `RunInvariantsViolation` | canonical lock field differs — new workspace, not a bypass |
| a pre-runtime-identity lock | rejected, not defaulted — that workspace cannot be resumed by this build |
| `MalformedCeilingOverride` | a bad `SIDERIUS_SUBPROCESS_RSS_GB` refuses loudly instead of silently falling back |
| `ResumeError` / `ReplayIntegrityError` | workspace state unreadable / tampered — fails closed |
| `LocalCodeError` | declared task-code integrity/dependency refusal; the workflow halts the chain with its own diagnosis, not a scientific failure |
| `MemoryError` in a child | may be classified as `oom_host_ram`; address-space limits do not prove host-wide OOM immunity |

## Files normally edited

`server_configs/` (new host); `runtime_control/` policy modules under their own
design docs. Additional address-space limits belong in caller environment
configuration, not machine-specific defaults in `execution_calibration.py`.
Historical experiment limits require verified provenance in exp; absence of an
archived environment does not prove that the old fallback value was used.

## Files normally NOT edited

`run_invariants.py` field partitions (adding a field to the wrong partition
either weakens the guarantee or breaks every resume); `sandbox_executor.py`'s
launch seam and role sites; `resume.py`'s union/projection authorities.

## Minimal example

```python
from core.execution_calibration import resolve_role_ceiling_gb
resolve_role_ceiling_gb("training")   # -> None (inherit OS limits), or explicit override
```

## Related tests

`tests/unit/core/` (lock partition guard, calibration refusal, resume
projections, replay integrity) and the tuner/workflow suites that exercise the
sandbox seam in pseudo mode.


## Watchdog deadline ownership

`runtime_control/watchdog_deadline.py` owns deadline selection. Typed selection
and independent watchdog budget are validated by `WatchdogConfig` and
`RuntimeControlPolicy`; admission continues to use its existing outer budget.
See [watchdog deadlines](../../docs/reference/watchdog-deadlines.md) for native
ceilings, explicit historical selection, transport and resume semantics.

## Phase launch and supervision structure (issue 672)

`runtime_control/phase_launch.py::run_phase_subprocess` is the shared selector
for armed-watchdog versus ordinary training/inference launches. The executor
retains admission, native input validation, task/config transport, timing,
timeout artifact cleanup and result classification. Both paths preserve the
runner's keyword contract; ordinary launches discard timeout metadata exactly
as before. Training bindings and inference batch size are each resolved once
for validation and child transport. The launch selector participates in runtime
verifier and preflight assembly identities.

The Step-11 structural guard retains the original executor budgets. The removed
subprocess monolith's historical measurements remain recorded separately from
its current compatibility facade. The facade retains all 13 existing parameters
and may only forward to `supervise_subprocess` and project the typed result.
Both real supervision functions are independently bounded against their
`46ee9920` measurements with no growth allowance. `supervise_process` still has
95 AST branch nodes / 277 lines: this change does not claim to reduce that
existing protected-process complexity. Further supervision features require
responsibility extraction; the facade cannot hide growth in its implementation.

## Pseudo composed inference and scoring

`StubSandbox.execute_inference` and `execute_scoring` accept optional
`task_scopes`, matching the wrappers' production call surface. They delegate
scope configuration transport to `execute_tools.scope_artifact.task_scope_argv`;
they do not interpret opaque scopes. The owner is a no-op without a training
scope; otherwise it requires a bound task-data-path capability and invokes the
task's codec to write training/evaluation artifacts under the sandbox configs
directory. Binding/codec errors propagate from these stub methods. The real
scoring method retains its ordinary-error result envelope.

Pseudo execution launches no child and consumes the existing seeded synthetic
result stream. For an evaluation scope, `core.pseudo_deliverables` supplies
CPU predictions through `run_generic_inference` and the task's ordinary
`write_deliverable` codec. This reads task input data and writes synthetic
artifacts for normal Health checks; it does not train a model or provide
scientific measurements. Predictions use the declared output geometry and
dtype, varying class indices across samples and non-class positions, or bounded
continuous values. They do not inspect labels, task names or Health thresholds.
Unresolvable geometry and non-floating continuous output dtypes raise
`PseudoEvidenceUnsupported`; task codec and data errors propagate. Legacy calls without evaluation scopes remain artifact-free.

The task codec owns scope ordering, source context and storage. Batch size one
bounds framework tensor lifetime, not task dataset/writer memory. The pseudo
evaluation ceiling bounds the row count: `StubSandbox.execute_inference`
forwards `runtime_policy["validation_max_samples"]` as `max_samples`, and
`write_pseudo_deliverable` passes it to `run_generic_inference(max_samples=...)`,
which compares the length of the one `validation_dataset` it constructs before
any prediction and raises `EvaluationSampleCeilingExceeded`; the pseudo path
translates that into its own refusal, so the scope is constructed once (#1488).
Real inference passes no ceiling and checks nothing. A longer scope (a task whose
`build_eval_scope` ignores `ScopeBuildRequest.max_samples`) raises
`PseudoEvidenceUnsupported` naming the task, the count and the ceiling;
nothing is written. `None` (direct callers without a runtime policy) skips the
comparison. A `pseudo_inference_<exp_id>_<run_name>.json` sidecar records
`_pseudo_origin`, `evaluation_max_samples` and inference sample/batch counts. The existing saved-record marker remains
required: synthetic Health success is only wiring evidence. Fixed inference
timings, absent runtime verification, training-cache merge order, legacy
SampleSet scope checks and saved `_pseudo_origin` provenance remain in force.
Caller regression: `tests/unit/core/test_stub_composed_scope.py`.

Before scope artifact writes, pseudo execution requires `exp_id` to pass the
existing `validate_generated_artifact_name` component rule. Calls with no
training or evaluation scope retain the legacy pseudo API without an `exp_id`
path check.

`verifier_provider.verifier_assembly_digest` includes the entire
`sandbox_executor.py`; changes confined to its pseudo methods still change the
runtime assembly identity. Historical runtime profiles can therefore refuse a
new build until separately qualified. Synthetic parity does not establish
historical campaign, paper, or resume compatibility.

When the bound manifest (`active_task_manifest_path`) declares a formula
`evaluation` selection, `StubSandbox.execute_scoring` returns formula evidence
from `core.pseudo_scoring.synthetic_formula_scoring`. It composes that manifest
through `compose_scoring_child_bindings`, as the scoring child does, draws one
synthetic scalar per primary/secondary source metric, and passes them through
`execute_tools.evaluation_child.aggregate_child_outcome`; it implements no
aggregation arithmetic. A manifest without an `evaluation` key is detected from
its raw YAML and never re-composed. A formula-referenced metric draws inside its
term's `[lower, upper]`, so `refuse` terms accept it; an unreferenced metric,
and the primary's nine-value `per_sample`, keep the legacy synthetic band. Success adds `evaluation_result`, `metric_result` and
the secondary result lists; `denoising_score` is the effective aggregate and
`file_vector` is null, as from the real child. A non-scoreable aggregation
returns status `error` with `not_scoreable` and `evaluation_result`. The
parent's `validate_child_evaluation` checks this payload unchanged. Runs without
a bound manifest or formula terms keep the legacy payload and random stream.
Values are synthetic wiring evidence, not measurements. Regression:
`tests/unit/core/test_stub_formula_scoring.py`.

## Versioned non-finite record JSON (issue #1111)

`record_encoding.py` is the single encoding-version owner. `record_json` writes
native typed outputs; `encoded_record` serves the untyped `LocalRecorder` detail,
log and summary writers. New native records retain their ordinary field layout
and add `$siderius_encoding = {"version": "siderius.nonfinite/v1", "floats": [...]}`.
Each path is an ordered list of string object keys/non-negative integer array
indices pointing to a string `Infinity`, `-Infinity` or `NaN`. Only paths named
in this metadata decode to floats: an ordinary string with the same spelling
remains a string, including inside `Any` and union fields. Real null remains null.
The reserved metadata member cannot be supplied as ordinary record data.
Canonical scalar/list roots use `wrapped=true` in the same metadata, distinguishing
them from object roots with a field named `value`. Metadata is validated by
`EncodingMetadata` before path dereferencing.

`model_record_value` preserves the model's JSON aliases/serializers and restores
non-finite float leaves from its Python dump before encoding. This is necessary
because JSON-mode dumps already replace non-finite values in `Any` with null.
`RecordModel` decodes at `model_validate`/`model_validate_json` entry, before native
validation. JSON input is re-entered through Pydantic's JSON validator so strict
tuple/date handling is retained. In-memory dumps and model JSON schemas acquire
no metadata fields. `LocalRecorder.get_summary` returns decoded records.

Old unversioned documents remain readable. Legacy null is never guessed back
into a float: its original sign/value is irretrievably absent. Files already
invalid under their native required-float schema remain invalid; capture can
compare their legacy storage projection against a supplied in-memory output
without rewriting them. `capture_record` uses versioned structural comparison
for new documents, making NaN stable while retaining sign and missingness.

`canonical_json_bytes` keeps sorted keys, compact separators and ASCII escaping.
Finite canonical values retain their bytes. Non-finite canonical values use the
same metadata/typed-path owner, with `allow_nan=False` guarding publication.
Adaptor records declare `encoding_version`; output/parameter digests and emitted
output bytes use that version. An absent version denotes the historical encoding.
Only readback calls `replay_json_bytes(..., version=None)`, reproducing historical
bare tokens and output digests byte for byte. Writers always select the current
version. Unknown versions and malformed metadata refuse; verification never
tries several encodings until one matches.

Identity impact: new native file digests change because of encoding metadata,
and new adaptor record digests change because of `encoding_version`. Non-finite
canonical output digests change; finite canonical values, declarations and
custom-adaptor manifests retain their existing bytes. Archived files, receipts
and digest anchors are never rewritten. New records preserve values that old
null projection discarded, so downstream handling of non-finite evidence may
change; this is not a scientific threshold/direction change. Exact reproduction
of historical writer bytes requires the experiment's historical framework pin
in `siderius-exp/pyproject.toml` and its resolved `uv.lock`.
No new-write legacy switch is supplied by the framework.

Evidence: `tests/unit/core/test_record_encoding.py`, the reachable-model census
in `tests/unit/agent/schemas/test_record_encoding_census.py`, and native/capture
and legacy/new adaptor replay tests in `tests/unit/tools/candidate_worker/`.

The source-bound `estimation_assembly_digest` changes because its closure includes
`agent/schemas/hyperparam_tuning.py`; `rendering_assembly_digest` changes because
its closure includes output schemas and native writer modules. Runtime verifier
and GPU protection closures are untouched, including `process_visibility.py`.
Template text and output field schemas are unchanged, but a non-finite value
previously erased to null can now affect downstream prompt data. Experiment-owned
qualified-assembly lists need separate qualification before adopting the new
revision; retain the experiment dependency pin to reproduce historical behavior.

### Raw consumer boundary and prompt rendering

`decode_record` also accepts a summary list and decodes each record before
returning it. Dashboard local-data access, exploration summary/native-output
routes, persisted metric ranking, funnel assembly and workflow validation
delegate to this owner. Raw log bootstrap/summary equality and native capture
intentionally retain storage bytes for durability or comparison; these are not
scientific consumer APIs. Typed native readers use `RecordModel` validation.

Planner `get_planner_user_prompt` decodes incoming memory before truncation,
JSON history rendering and training-dynamics rendering. Reflector
`get_reflector_user_prompt` decodes the actual-results record before rendering.
This also covers external callers passing raw persisted dictionaries. No
storage metadata or quoted numeric sentinel is model-facing. The existing
JSON-in-prose renderer represents decoded non-finite floats as unquoted
`Infinity`, `-Infinity` and `NaN`; it is prompt text, not a persisted strict
JSON document. Actual string values remain strings. Finite/null histories
retain field order and identical rendered bytes. For newly persisted
non-finite histories, the planner now sees the original numeric evidence where
historical null-projected records render `null`; old archives still render
their historical null. Typed interpreter/proposer/literature/implementor
consumers receive decoded values before their existing projections and numeric
formatters, never storage tags. No prompt template is changed.

### Version selection threat model (issue #1326)

The encoding version is a dispatch label, not authentication. Replay selects the
encoding a stored artifact records (`AdaptorRecord.encoding_version`,
`ImplementorOutput.consumed_input_encoding`, the `$siderius_encoding` member) and
then requires two independent facts: the stored bytes equal the trusted digest
anchor (graph trace `record_sha256`, adaptor `outputs[].sha256`), and the value
recomputed from upstream native records equals what the artifact claims.
Changing or removing a version therefore changes the anchored bytes and is
refused at the anchor (`graph adaptor record mismatch`, `graph native record
mismatch`). A forger who rewrites a record and its outputs consistently in the
legacy encoding still cannot change the numeric value: the outcome is
recomputed, so only its spelling can differ, and that spelling differs from the
anchor. Without a metadata path `decode_record` never turns a string into a
float (a lax typed `float` field may still parse the spelling, yielding the same
value it encoded, never another number). Duplicate metadata paths are refused by `decode_record`'s own path
check (`duplicate non-finite float path`); overlapping paths fail dereferencing.

Legacy null is irrecoverably ambiguous: an unversioned artifact whose writer
null-projected a value cannot say whether it was `inf`, `-inf`, `NaN` or
missing, and replay reproduces that historical identity rather than guessing.
If an attacker controls both the artifacts and every trusted anchor, this format
supplies no authenticity; anchors must come from a trusted receipt chain.

Evidence: `tests/unit/core/test_record_encoding.py` (duplicate/overlapping paths) and
`tests/unit/tools/candidate_worker/test_adaptor_encoding.py` (consistent legacy
downgrade refused by the trusted anchor).

### Scoring child output (issue #1316)

The scoring child (`execute_tools/denoising_score_single.py::_merge_output_json_for`)
writes its parent-created `--output_json` with `encoded_record(data, always=False)`
and `allow_nan=False`; the parent reads it only through
`execute_tools.evaluation_child.read_scoring_output`, which applies
`decode_record` (`TidmadSandbox.execute_scoring` and `scoring_refusal_fields`).
A finite payload carries no metadata and keeps its historical bytes. A
non-finite primary scalar, `file_vector` element, `metric_result.scalar` or
secondary scalar now reaches the tuner as the float it was, instead of `null`;
an actually missing element and the not-scoreable `denoising_score: null`
remain `None`. Live decisions that previously tested `is not None`
on a score now test `execute_tools.metric_order.finite_score` (a real finite
number; the neutral owner both the tuner and the dashboard import):
checkpoint retention (`scored`), the per-file score table, and the reflection
context's rank / new-best / efficiency fields. A non-finite round is therefore
decided exactly as the null round it used to be. Persisted-record rankers
outside the tuner apply the same predicate: the dashboard model overview best
and leaderboard (`dashboard/data_sources/local_json.py`) and
`persisted_ranking.best_by_declared_metric` never rank or call best a NaN/±inf
record (a trial `failed_mode_collapse` record keeps its non-finite score);
typed dashboard responses serialize any remaining non-finite float field as
JSON `null`. Selections over persisted
records were already finite-aware or status-gated: best tracks
(`math.isfinite`), the validity merge (`_merge_score_validity_failure` makes a
non-finite round `failed_mode_collapse`), candidate eligibility, and
interpretation/reflection filters on `status == "success"`. Persisted records,
planner history and reflector-visible results now carry the non-finite value
on the task-owned subprocess route, as the in-process anchor route already did. The file is
transient (removed after the read), so no archive of it exists.
Identity impact: `estimation_assembly_digest` binds
`ml_hyperparameter_tune_agent.py` and `execution.py`, and enters every
composition's `semantic_fingerprint` through the preflight estimator identity.
Every task composition fingerprint therefore moves with this revision, and
because `task_composition_fingerprint` is a compared run invariant
(`run_invariants.py`), a run started before it is refused on resume
(fail-closed). Experiment-owned fingerprint and assembly qualification lists
must be requalified at freeze; historical runs resume only under their pinned
framework revision.
`scoring_utils.coerce_nonfinite_to_none` no longer runs on any new write; it
remains for comparisons with legacy null-projected storage images.
Evidence: `tests/unit/execute_tools/test_scoring_output_nonfinite.py`.
