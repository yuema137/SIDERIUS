# Evaluation declarations and launch admission

Owners: `evaluation_spec.py` (Pydantic declarations), `evaluation_registry.py`
(kind registration and capability table), `evaluation_validation.py` (cross-model
validation and inspection), `workflows/evaluation_composition.py` (resolution and
canonical identity). The existing task composer delegates to these owners.

## Availability and boundaries

`evaluation:` is optional. Absence preserves previous semantic fingerprint inputs,
source metric behavior and prompt bytes. Presence permits composition and inspection,
and primary-only metric declarations can launch with evaluation rendering.
Weighted-sum formula aggregation (#1294) launches on the supported native route
described in [Deterministic selection runtime](#deterministic-selection-runtime).
Rubric components and rubric balancing (#1297) launch as declared agent
guidance only; see [Rubric guidance](#rubric-guidance). Feasibility constraints on metric and
measurement components (#1295) launch on the same route; see [Feasibility constraints](#feasibility-constraints).
Builtin candidate measurements (#1296) launch on the same route; see
[Candidate measurements](#candidate-measurements). Composition never
executes arithmetic, measurements or an LLM. A declaration is not runtime support.

`RunTaskComposition.evaluation` is `ResolvedEvaluation | None`. Its `spec` is the
validated `EvaluationSpec`, `components` contains resolved identities/directions,
`registry` contains this composition's registrations, and `inspect()` reports
warnings, marginal utility rates, required capabilities and the evaluation digest.
`bind_run_task_composition` checks capabilities before binding or reading data;
the standalone scoring-child metric entry also checks them. Missing capability
errors state that composition succeeded and name the unavailable capabilities.
Unknown plugin capability names fail closed through the same table.

## Schema

All declarations are frozen, strict Pydantic models with `extra="forbid"`.
YAML lists become tuples only at declared sequence fields. Numbers are finite,
not strings or booleans; means, ranges and units are never inferred from names.
Author prose is bounded: component `meaning` and rubric-balance `guidance` have
at most 1000 characters, matching the existing rubric criterion-description cap;
metric `units` has at most 128 characters, enough for compound unit labels rather
than another narrative field. An evaluation has at most 32 components and 64
constraints: a bounded decision inventory with room for two bounds per component.
These are declaration API limits, not scientific thresholds or a total token
budget for plugin-rendered content. Composition errors retain the field name,
and invalid declarations are refused before component loaders run.
New fields must have defaults, and default values must be omitted from canonical
identity (`exclude_defaults=True`). Explicit default and omitted default are equal.
The size bounds add validation metadata only: no field, default, or serialization
value changes. Existing valid declarations retain their evaluation identities.

`EvaluationSpec` fields:

- `schema_version`: `siderius.evaluation/v1`, default that value.
- `component_kinds`: mapping from custom kind to `{file, symbol}`, default `{}`.
  `module:` is refused; code must carry the existing file-content identity.
- `components`: required nonempty ordered sequence of registered variants;
  each requires unique `id`, literal `kind`, and nonblank `meaning`.
- `selection`: required discriminated primary/formula/rubric_balance variant.
- `constraints`: ordered sequence, default `()`.

Builtin components:

- `metric`: required `metric` refers to a declared primary or secondary metric id;
  optional `units: str | None = None`, descriptive `range: {lower, upper} | None =
  None` with lower < upper. Direction comes from its resolved `MetricSpec`. Values
  are in **post-transform `MetricResult.scalar` units**. No `limits`: scoreability
  retains metric validity ownership. Aliasing one metric as two components refuses.
- `rubric`: required `rubric: {id, version, sha256?}` resolves against manifest
  `rubrics`. Optional authored SHA must match; actual content SHA always enters
  identity. Units, range, limits and direction are forbidden. The authored SHA
  assertion is excluded from spec serialization; resolved identity carries the
  authoritative SHA. No rubric scores enter scalar selection or constraints.

- `measurement` (#1296): required `measurement` (one of `trainable_parameter_count`,
  `total_parameter_count`, `model_bytes`, `inference_latency_ms`), required explicit
  `direction: higher | lower`, optional descriptive `range`, and `protocol` required
  for `inference_latency_ms` and refused otherwise (`input_shape` 1-8 positive ints
  including batch, `warmup` 0..1000 default 10, `repeats` 1..10000 default 50,
  `timeout_seconds` (0, 3600] default 300). Units are fixed by the measurement
  (parameters, bytes, ms), never authored or inferred. Two components with the same
  measurement and protocol refuse. Registration requires capability `measurements`.

External variants may add their own typed fields, including limits if appropriate.

Selection variants:

- `{kind: primary}` retains the source primary metric for deterministic ranking.
- `{kind: formula, formula: {family: weighted_sum, params: {terms: [...]}}}`.
  Each term requires `component`, positive `weight`, finite `lower < upper`, and
  explicit `out_of_range: refuse | clip`. Terms refer to distinct deterministic
  quantitative components. Component descriptive ranges never supply term bounds.
  The family discriminator is retained for future additions; there is no arbitrary
  expression language or lexicographic family in v1.
- `{kind: rubric_balance, rubric: {id, version, sha256?}, guidance: <text>,
  deterministic_ranking: <primary or formula>}`. The deterministic ranking is
  mandatory and cannot recursively be rubric_balance. The rubric and guidance
  are rendered agent guidance only; every deterministic ranking uses
  `deterministic_ranking` (see [Rubric guidance](#rubric-guidance)).

Weighted-sum arithmetic contract: normalize each term to
`q=(value-lower)/(upper-lower)` using its explicit range policy. Convert q to
utility using the source metric direction through MetricOrder; lower-preferring
components contribute `1-q`. The aggregate is `sum(weight*utility)/sum(weight)`.
The output is higher-is-better utility in [0,1] by definition: no authored aggregate
direction. There are no observed-population normalization bounds. Inspection
reports the signed marginal rate `weight/sum(weights)/(upper-lower)` as an exact
rational string (utility per raw unit, within the interval); clipping makes the
rate zero outside the interval, refusal produces no utility there. Directional
sign and warning language are obtained from MetricOrder.

Constraints require `{component, op, threshold}`; op is `>=`, `>`, `<=` or `<`.
All constraints are conjunctive and refer to raw post-transform component values,
never normalized utilities. Unknown/nonquantitative references and contradictory
intervals refuse composition. Preference-opposing constraints remain valid and
produce inspection warnings. Descriptive component ranges do not impose feasibility.
No equality, implicit tolerance or inferred scientific threshold is supported.

Only a secondary referenced by a formula term or constraint becomes REQUIRED
quantitative evidence for formula and constraint execution. Merely listing it as a component leaves it
observational. Missing or nonfinite required evidence must fail closed; unrelated
secondary errors retain their observational behavior. Health, feasibility and
preference remain separate authorities; Trial Health exemptions do not grant
feasibility exemptions.

## Registry extension

A file exports one `ComponentKindRegistration` with kind, version, schema, load,
fingerprint, render, value_kind (`quantitative` or `rubric`), and
required_capabilities (default empty frozenset). Schema extends `ComponentSpec`,
uses one matching `Literal` kind and must remain extra=forbid, frozen and strict.
Plugin schemas must not exclude fields or define custom serializers, including
in nested models or Annotated types: these could hide validated values from the
resume identity. Registration inspects the compiled Pydantic schema and refuses
these declarations. Expected validation/loading ValueErrors become
TaskCompositionError; unexpected hook programming errors propagate unchanged.
Each composition starts with a fresh builtin registry; builtin override refuses.
There is no mutable shared registration state or rollback procedure.

The composer loads that symbol with existing `_load_symbol`, then constructs one
Pydantic discriminated union from all registered schemas. No consumer owns a
second list of kinds. It calls `load(component, EvaluationLoadContext)` for each
validated variant. The context offers source MetricSpecs, judge declarations and
a file-symbol loader that captures provenance. Load hooks resolve declarations;
they must not execute a candidate or contact a service. A `ResolvedComponent`
carries optional direction and resolved JSON identity, not a measurement result.

`fingerprint(component, resolved)` adds JSON identity to the complete validated
declaration; it cannot remove core fields. Absolute host paths in contributor
values/keys refuse. File references pin captured contents and existing code_package
member identity, with paths resolved relative to the manifest. Declare helpers in
code_package; a registry hit alone is not content proof. `render(component,
ComponentRenderContext)` is the pure full-string hook used by the shared
evaluation prompt renderer. It must disclose meaning and applicable metadata.
The context supplies MetricOrder direction words and, for builtin rubric
components, the resolved RubricSpec. Plugins own their extra units/ranges/limits.
Registry `required_capabilities` join selection/constraint capabilities and the
mandatory rendering capability; only framework runtime owners enable table entries.

## Identity and resume

When present, canonical evaluation identity is added under `evaluation` in the
composition fingerprint. It contains default-excluding declarations, role-bound
kind/source identities, contributor output and exact resolved rubric hashes.
Explicit matching rubric hash and implicit resolution produce identical identity.
Declared list order is semantic; mapping keys are canonicalized. Resolved absolute
locations stay provenance only. No evaluation key or plugin pin is added on absence.

Existing composition fingerprint locks AND record stamps own resume rejection.
Changes to meaning, terms, constraints, rubric content or plugin code cannot reuse
old records merely because MetricSpec stayed equal. `reconcile_metric_specs` and
`reconcile_metric_identity` retain their current APIs and comparison granularity.

Full fingerprints still change release-wide when composer source changes because
`estimation_assembly_digest` includes that file (#999). Semantic-payload parity
excludes assembly digest fields and must be labelled separately from full identity.
Never suppress assembly changes or rewrite archived evidence to claim parity.

## Downstream handoff

Formula execution emits a NEW effective selection MetricSpec whose id derives from canonical
evaluation identity, with higher-is-better utility for weighted_sum. Ranking binds
to that scalar. **Health explicitly keeps reading original source metric values,
never utility**, including a named raw component where a check supports one.
Primary-unit `--target_score`, loop `metric_threshold`/`MetricAtLeast`, and threshold
adaptors must refuse launch under formula selection unless re-declared against
effective utility or a named raw component. Never silently compare those existing
thresholds to utility. Feasibility thresholds name raw components.

The `evaluation.spec` renderer is gated outside its decorated boundary on
absence: historical profiles on absent-evaluation tasks never meet the new
boundary and need no override. Present evaluation requires an explicit override
or native declaration in an active profile. Changed assembly hashes still require
normal offline qualification. #1295 enforces feasibility through scoreability
(below), so every selection site inherits it; #1296 supplies measurement schema/execution (below);
#1297 ships rubric guidance only; candidate-result projection and versioned replayable
rubric judge calls are a separate follow-up. Existing metric-scored
adaptor restrictions remain until deliberately amended by their owner.

Composition scales with declaration/plugin bytes, not dataset size; it loads no
scientific data, tensors or GPU work. Bounds are authored values, never caps on
TIDMAD or other task dataset lengths.

## Validation

`tests/unit/workflows/test_evaluation_composition.py` covers real composer and
launch paths, resume refusal with unchanged source MetricSpec, reference resolution,
inspection, plugin identity/isolation/relocation, defaulted schema extension and
rubric digest resolution. Full affected package suites and the separately recorded
baseline comparison establish integration evidence; declarations alone do not
establish runtime evaluation support.

## Evaluation prompt rendering

`agent/evaluation_context.py` constructs typed, copyable declaration snapshots
from the composed evaluation, source primary MetricSpec and judge declarations.
`bind_run_task_composition` binds them through its existing ExitStack; nested,
exceptional and concurrent scopes restore their own context. The composition
verification guard rejects a missing or mismatched evaluation binding. No manifest
reload, model execution, measurement or judgment occurs during rendering.

`agent/prompt_templates/evaluation.py:render_evaluation_spec` is the sole
`evaluation.spec` boundary. It dispatches components through the composition's
registry hooks. It emits `[TASK EVALUATION]`, interpretation rules, Components,
Selection, Constraints, then any inspection warnings, in declaration order,
and closes with `[END TASK EVALUATION]`. Builtin authored text normalizes CR,
CRLF and Unicode line/paragraph separators to LF before continuation indentation;
authored lines cannot acquire the unindented layout of framework section labels.
Plugin hooks own their field formatting and can reuse `indent_text`. These text
delimiters distinguish declaration prose from surrounding framework text; they
do not make instruction-like author content trusted executable policy.
Metric descriptions include meanings, units, MetricOrder direction words and
optional descriptive ranges. Rubrics include resolved identity, integer scale
and weighted criteria; they never receive a quantitative direction or unit.
Formula descriptions include weights, exact relative weights, explicit term
bounds, refuse/clip policy, symbolic utility and the existing inspection owner's
signed marginal rates. Rubric balancing always includes deterministic_ranking.
No result is scored or constraint enforced by this text.

For example, weights 3 and 1 on a higher-preferring accuracy term bounded [0,1]
and a lower-preferring error term bounded [0,10] produce the declared utility
`(3*u_accuracy + 1*u_error)/4`. Marginal rates within bounds are 3/4 per accuracy
unit and -1/40 per error unit. A component's descriptive [0,100] error range does
not change the term's bounds. Clipping has zero marginal rate outside bounds;
refusal yields no utility there. Constraints retain raw values and exact authored
operators. Metric constraint lines repeat declared units (or say units are not
declared); custom-kind constraint lines refer to the component declaration, whose
hook owns unit semantics. No unit is inferred from arbitrary plugin attributes.

`append_constraint_disclosure` appends evaluation through one shared path after
execution constraints. It invokes no new boundary for an absent evaluation and
adds no bytes. A present spec invokes the boundary even if a profile suppresses
execution-constraint disclosure. Existing consumers include proposer legacy and
pipeline stages/retries, interpreter primary/dedup/analysis brief, tuner planner
and reflector, implementor model/loss/repair, validator review, literature search
and synthesis, and data-analysis structured output/repair. Proposer metric context
points to the shared user-message block rather than duplicating it and applies
prediction direction rules to the named prediction metric. Under active evaluation
the interpreter labels its legacy score field as a recorded score; serialized keys
remain unchanged. Literature extraction preserves published source facts and
receives no task-evaluation block. Existing judge versions remain unchanged;
a future rubric judge version must explicitly use this renderer.

A historical profile selected for an evaluation-bearing task must declare this
boundary native or provide a renderer accepting `context`. An empty override
suppresses presentation only; it cannot admit formula, constraint, measurement or
rubric execution. Providers receive deep-copied plain containers instead of the
composed registry's MappingProxyType containers. No global kind registry is added.

The rendering assembly includes context, builtin hooks, registry, evaluation
schema/inspection and MetricOrder dependencies. Adding the composer binding also
moves estimation assembly and full composition fingerprints. Absent-spec semantic
payload and native prompt-byte parity are distinct from assembly identity parity;
no archived identities or qualification receipts are rewritten.

Regression coverage: `tests/unit/agent/test_evaluation_rendering.py` exercises
formats, bounds/rates, plugin hooks, profile admission/copying, scope isolation,
and a paper-style profile on a real absent-evaluation composition;
`test_evaluation_prompt_paths.py` checks final offline provider arguments.
`tests/unit/workflows/test_evaluation_composition.py` covers primary launch,
missing-capability refusal and lost-binding detection. No real hardware or LLM
qualification is implied by these tests.

## Deterministic selection runtime

`workflows/evaluation_selection.py` derives the effective `MetricSpec` without
replacing `RunTaskComposition.metric`, which remains the executable source metric.
`selection_metric_spec` exposes the ranking declaration. The optional typed
`SelectionBinding` is projected through `TaskCompositionRef`; it carries source
and effective specs, evaluation SHA and ordered required component identities.
`evaluation.inspect()` reports `effective_metric_id`, direction and utility units
for formula selection. The id is `evaluation.weighted_sum.v1.<evaluation SHA>`;
aggregation is `evaluation.weighted_sum/v1`, direction is `higher`, and no source
transform is applied twice. Primary selection retains the original spec.

`evaluation_aggregation.py` is the sole arithmetic owner. The native task-owned
scoring child calls it after source primary and declared secondary evaluation.
Finite decimal input representations are converted to exact rational values for
normalization, directional utility and weighted summation; final persisted numbers
are floats. Bounds and weights come from terms, never observed candidate values.
`MetricOrder.normalized_utility` owns source-direction interpretation. A missing,
refused, errored, nonfinite or out-of-range required component produces the existing
`NotScoreableResult` path; no available-term renormalization or zero substitution.
The source primary must also succeed, including when it is not a formula term.
Unreferenced secondaries remain observational.

`EvaluationInputsScoreability` accepts evaluated component evidence. Its generic
file-only `check` refuses because file presence cannot establish quantitative
acceptance. The aggregate owner supplies its evidence verdict after the source
metric contracts and range checks. Persisted inspection uses the existing inert
scoreability reconstruction; it does not execute external task code.

The child writes `evaluation_result: EvaluationEvidence` beside `metric_result`.
This contains the evaluation SHA, effective metric id, source `MetricResult`,
ordered `ComponentEvaluation` entries (identity, raw, normalized, utility, authored
weight/bounds/range policy, weighted contribution and clipping flag), aggregate,
and typed failures. Successful `metric_result.scalar` and `denoising_score` are the
aggregate. Effective `file_vector` and `per_sample` are absent/null: a scalar
combination does not imply a per-file decomposition. The source vector remains in
`evaluation_result.source_metric_result.per_sample`.

The parent checks the child status first (a crashed or OOM-killed scorer keeps
`ScoringSkillExecutionError` with its status and stderr), then validates the child
identity, required component roster and scalar agreement, and re-derives every
component and the aggregate from raw values and the declared terms
(`SelectionBinding.terms`) before adopting results. Raw values must equal the
transported source results; duplicate source metric ids, missing evidence or any
disagreement raise `EvaluationTransportError`. The scoring child composes full task
bindings only when its manifest declares `evaluation`; absent-evaluation children
compose the metric section alone. Structured refusal evidence survives child exit
1 into `error_scoring` / `failure_type=not_scoreable` and `metric_refusal`.
Scope and package-integrity exceptions retain their existing terminal handling.
On refusal, `denoising_score_single._emit_outcome` merges secondary fields only
when `evaluation_result` is present. Without evaluation, the child JSON retains
the pre-formula refusal bytes even when observational secondaries were computed;
`test_scoring_refusal_payload.py` checks a fixed historical literal and formula
refusal evidence preservation. The record field is omitted when evaluation is
absent. Historical records are not recomputed. Existing composition locks and metric reconciliation reject changed
formula identities and mixed source/effective ranking histories.

Health receives the original source scalar and vector through
`evaluation_child.source_health_inputs`; `round_health` independently checks the
selection scalar's validity. Formula utility never replaces a task Health input.
Existing Health validity filtering still precedes MetricOrder ranking. Consumers
bound to the effective spec and exercised offline under formula selection: tuner
run order and planner request, tuner run-output `metric_spec` stamps, attempt-record
evidence, workflow seed/interpretation reconciliation (`_declared_metric_spec`), the
native completed-history chain incumbent (through `run_workflow` in
`test_workflow_completed_history_uses_effective_metric`, including transport to
the next tuner input; reverting that call site to the source spec fails), the
resume record fold, worker loop stop
admission, worker interpretation seeds and prepared candidate payloads. The
effective `MetricSpec` round-trips through JSON (`evaluation_inputs/v1` is a
framework scoreability contract), so persisted stamps compare equal on readback.
Proposal evidence, metric-rank adaptors, run reports and dashboard ranking read
the persisted stamp through their existing MetricOrder paths; that is established
by source review only, without a formula-specific test (no worker profile admits a
metric-rank adaptor). Source per-file values must not be labelled as utility evidence.

### Admission and threshold units

`workflows/evaluation_admission.py` owns formula admission. Only native TASK_OWNED
scoring-child execution is supported. ANCHOR_NORMALIZED and
CandidateEvaluationExecutor combinations refuse; their child handoffs are #1336.
Referenced custom quantitative kinds without runtime values refuse by component
name and kind (#1338). Constraints remain independently gated; enabling formula
aggregation does not enable them. Rubric capabilities add no runtime value.

Under formula selection, existing primary-unit thresholds refuse. Use the generated
effective metric id for loop `metric_threshold`, route `MetricAtLeast`, and
`threshold/v1` metric adaptors. The exploration CLI requires
`--target_score_metric <effective id>` alongside `--target_score`. All declared
branches are checked before dispatch. `component:<id>` raw targets explicitly
refuse until #1337. A target value of .8 means .8 utility, not source-metric units.

Active tuner score-unit settings require `score_units_metric` (CLI
`--score_units_metric`) equal to the generated effective id. This acknowledges
units for enabled skip/bypass margins and a numerical degeneration penalty.
Disabled formal gates need no unit declaration; dimensionless fractions keep their
meaning. No-evaluation and primary-selection launches retain existing behavior.

Validation owners: `tests/unit/execute_tools/test_evaluation_aggregation.py`,
`tests/unit/workflows/test_evaluation_admission.py`, the existing metric/Health
structural guards and the complete affected package suites. Paper qualification
must report semantic-payload parity separately from release-wide assembly identity
changes; schema/source edits can move identities even with identical prompt bytes.

## Rubric guidance

`IMPLEMENTED_CAPABILITIES` sets `rubric components` and `rubric balancing` to
True. The capabilities have exactly one runtime consumer: the
`evaluation.spec` renderer. Launch admits a `kind: rubric` component and
`selection: {kind: rubric_balance}` on every route that admits the rest of the
evaluation. Their deterministic parts keep their own gates: a formula under
`deterministic_ranking` needs `formula aggregation`; constraints need
`feasibility constraints`.

**A rubric is not a metric.** A rubric referenced by an evaluation `rubric`
component or by `selection.kind: rubric_balance` is task-declared
natural-language guidance. Its criteria, weights and integer scale, and the
balance `guidance`, are rendered to agents through `evaluation.spec`. The
rubric enters evaluation identity by resolved content hash. It has no
direction, units or total. It is never:

- a formula term or a constraint;
- an input to MetricOrder;
- a record score field;
- a Health input;
- a stop-condition value.

Every deterministic ranking uses the effective metric of
`deterministic_ranking` (`formula_terms` unwraps it; `selection_metric_spec`
exposes it): tuner trials and planner requests, incumbent, resume folds,
`--target_score`, metric stop conditions and metric adaptors. That effective
metric is the source primary for `{kind: primary}`, or
`evaluation.weighted_sum.v1.<evaluation SHA>` for a formula.

No framework step judges a trained candidate against an evaluation rubric. No
judge call, judge evidence or LLM cost is added. The existing judge strategies
use only the rubric named in their own declaration (`rubric-rank/v1`), and
their templates are unchanged.

Rendered semantics:

- A rubric component ends with `Role: qualitative guidance for agents; no
  framework step scores it; never a deterministic scalar or ranking input.`
- Rubric balancing states `Rubric balancing is guidance for agents; no
  framework step judges candidates against it.`, followed by the rendered
  `deterministic_ranking`.

Evaluations without rubrics, and absent `evaluation:` sections, keep their
prompt bytes. No new prompt boundary is added.

Deferred follow-up: rubric-driven judged selection is a separate change. It
covers a `candidate.result` projector, a `judge.rubric/v2` template rendering
`evaluation.spec`, a dedicated judge route and budget, and rubric facts for
adaptors over `tuning.output` and JudgeStop. Today `ITEM_PROJECTORS` holds only
`proposal.output` and `literature.output`. No shipped profile admits an adaptor
over `tuning.output`. Q-B2-2 forbids an LLM from reordering metric-scored
items.

Validation: `test_rubric_guidance_launches_without_entering_metric_order` (binding
admits a rubric component with `rubric_balance` over a formula; the effective
metric is the weighted-sum id) and the rubric wording assertions in
`test_rubric_balance_discloses_criteria_and_deterministic_formula`.

## Feasibility constraints

Owner: `evaluation_aggregation.evaluate_constraints` / `evaluate_constraint` (the
single comparison arithmetic, shared by the scoring child and the parent verifier)
and `constrain_primary` (primary selection). Constraints are enforced as declared
scoreability; no selection site carries a separate feasibility filter.

An infeasible round takes the existing scoring-refusal path: the attempt does not
succeed, so the tuner's attempt retry and `consecutive_fails` accounting apply
unchanged (each retry trains again; consecutive infeasible rounds reach the
consecutive-failure brake). The parent re-derives every constraint verdict on a
successful evaluation; on a refusal it accepts the child's failure list, which
fails closed.

- `SelectionBinding` is bound when the spec declares formula terms OR constraints.
  `constraints: tuple[ConstraintTerm, ...]` (omitted when empty) carries each
  declared constraint and the source metric id of its component (`None` for a
  non-metric quantitative component). `is_formula` is true only when the effective
  metric id differs from the source id; constraint-only bindings keep the source
  `MetricSpec` as the effective spec, its units and its per-sample evidence.
- The scoring child judges every constraint on the raw post-transform value: the
  source primary or a declared secondary by metric id, or, for a measurement
  component, the typed `MeasurementResult` whose `component_id` matches (#1296
  `measurement_results`, indexed by `record_measurements`); a failed measurement
  has no value. Comparison is exact on the
  decimal representations; `>=`/`<=` are inclusive and `>`/`<` exclusive; no
  tolerance. A missing, null or nonfinite value is never satisfied.
- Each unsatisfied constraint is a `ScoreabilityFailure`
  `requirement="constraint:<component>"`, detail
  `constraint <component> <op> <threshold> violated: <raw>` (or `has no finite
  value`). Under formula selection these join the term failures under
  `evaluation_inputs/v1`. Under primary selection the refusal is a
  `NotScoreableResult` for the source metric id with contract
  `evaluation_constraints/v1`; a source-primary refusal is returned unchanged
  without evaluation evidence.
- `EvaluationEvidence.constraints: tuple[ConstraintEvaluation, ...]` (omitted when
  empty) records `{component_id, op, threshold, raw, satisfied, detail}` in
  declaration order on success and refusal. Under primary selection a successful
  `aggregate` equals the source scalar and `components` is empty.
- The parent re-derives every constraint verdict from transported raw values and
  refuses disagreement or a success that contains a violated constraint
  (`EvaluationTransportError`). It also requires the constrained primary scalar to
  equal the source scalar.
- A refusal becomes the existing `error_scoring` / `failure_type=not_scoreable`
  record with `metric_refusal` and `evaluation_result`; `memory.conclusion` names
  every violated constraint and `memory_update` names infeasibility. Every
  selection site already requires `status == "success"` or a finite
  `denoising_score` (tuner best tracks and Trial winner, skip/bypass gates, chain
  incumbent and `--target_score`, resume folds, loop stops, `MetricAtLeast`,
  adaptors, interpretation, reports), so an infeasible candidate is never selected,
  ranked or used as an incumbent. Health is not evaluated for a refused round, and
  feasibility never changes Health validity or a scored record's score.
- Trial and Formal rounds follow the same rule; there is no Trial exemption.
- Constraint-only bindings do not change threshold units: `--target_score`, loop
  `metric_threshold`, `MetricAtLeast` and `threshold/v1` keep the source metric.
  Only the native TASK_OWNED scoring child produces the evidence; other routes and
  `CandidateEvaluationExecutor` refuse at launch, as for formulas.
- Pseudo scoring (`core.pseudo_scoring`) passes synthetic values through the same
  child owner when constraints are declared.
- The shared `evaluation.spec` renderer states that a Trial or Formal candidate
  violating a constraint, or lacking a finite value for one, is not scoreable and
  never selected.

Not covered: noise-aware constraints and a feasibility-specific planner feedback
carrier. `require_component_runtime` admits metric and builtin measurement
components; custom plugin kinds without a runtime value remain refused (#1338).

Validation: `tests/unit/execute_tools/test_evaluation_constraints.py` (refusal and
reason, exact inclusivity, fail-closed missing values, formula constraints, parent
re-derivation, tuner best/Trial-winner exclusion through the real record builder,
per-sample record readback) and
`tests/unit/core/test_stub_formula_scoring.py` (pseudo transport).

## Candidate measurements

Owners: `execute_tools/candidate_measurement.py` (request, measurement and supervision),
`candidate_measurement_worker.py` (worker entry), `measurement_results.py` (typed
results/accessor), `candidate_measurement.active_measurement_components` (bound roster).

`TidmadSandbox.execute_scoring` runs declared measurements in a separate supervised
child **before launching the scoring child**. It transports a validated
`MeasurementWorkerRequest` containing checkpoint reconstruction inputs and the exact
component declarations. Only the measurement worker constructs the candidate with
`construct_inference_model`, loads it with `load_inference_checkpoint` (trainer
sentinel enforced), and runs its forward. The scoring interpreter reads typed JSON
and does not import candidate model/plugin modules for measurement; candidate
monkeypatches cannot reach its aggregation or emission. This is interpreter/process
isolation, not an OS security sandbox against filesystem writes by same-user code.
`compose_scoring_child_bindings` and `compose_scoring_secondary_metrics` resolve
only metric/evaluation/judge declarations through the existing owners, never the
full task composition that would import declared model or loss plugins. Task-owned
metric and data-path implementations still execute as the trusted scoring authority.

The worker inherits the attempt's environment, plugin roots and
`CUDA_VISIBLE_DEVICES`, selecting CUDA when visible and CPU otherwise. It uses the
scoring role's address-space cap from `core.execution_calibration`; its supervised
RSS ceiling is that positive cap in bytes, or physical host RAM when no extra cap
is declared. The parent supervises the owned process group with a hard deadline of
300 seconds for startup/checkpoint loading plus the sum of declared latency
`timeout_seconds`. Deadline/RSS excess terminates the group (5-second TERM grace,
then KILL and a 5-second reap bound; RSS/deadline polling is 0.2 seconds). A blocked
model import, constructor or forward cannot evade this parent-owned deadline.

The parent validates worker JSON and writes `scoring_measurement_results.json`,
including synthesized typed failure results after timeout, RSS excess, crash or
invalid output. Only declaring runs receive `--measurement_results_json`; the
scoring child refuses an absent flag or a mismatched component roster/kind. Runs
without measurements start no worker and retain their existing scoring argv.

- Parameter counts are summed over the loaded model's parameters (trainable: those
  with `requires_grad`). `model_bytes` is the checkpoint file size.
- `inference_latency_ms`: one synthetic input (`torch.randn` seeded 0 in the resolved
  inference dtype, zeros for integer dtypes), `eval()` and `inference_mode()`,
  `warmup` untimed forwards, then `repeats` `perf_counter` timed forwards with CUDA
  synchronization. Value is the median in ms; noise is `{repeats, iqr}`. It never
  reuses inference-phase per-file or per-batch wall times, which include I/O and
  contention. Per-protocol checks after each forward can return an early failure;
  the independent parent-owned worker deadline also kills blocked forwards.
- Each failure (exception, timeout, nonfinite value) becomes a `MeasurementResult`
  with `failure` set; measurement code never raises out of the child. Code-package
  integrity failures still propagate.

The child emits `measurement_results` (one per component, declaration order) beside
`evaluation_result`. `aggregate_evaluation` reads measurement terms from them: a
missing, failed or nonfinite required measurement becomes a `ScoreabilityFailure`
naming the component and the reason, so the candidate is not scoreable. The parent
requires exactly the declared measurement ids and kinds (no missing, extra or
duplicate results), then re-derives each measurement term against the transported
`measurement_results` (`SelectionTerm.source_measurement`); disagreement raises
`EvaluationTransportError`. Constraint-only failures also include the measurement's
failure reason. Successful scoring transport must equal the parent's validated
worker results.
Records carry `measurement_results` on success and on structured formula refusals;
the field is omitted when empty, so non-declaring runs keep record and planner prompt
bytes. `measurement_results.measurement_value(record, component_id)` is the accessor
for feasibility (#1295) and rubric projection (#1297); it raises
`MeasurementUnavailable` instead of returning a missing value. Pseudo mode
(`core/pseudo_scoring.py`) synthesizes results within term bounds and passes them
through the same aggregation owner. Rendering uses `render_measurement_component`
through the existing `evaluation.spec` boundary.

Refused combinations: a bound `CandidateEvaluationExecutor` refuses launch
(`require_measurement_route`). The ANCHOR_NORMALIZED route scores in process and runs
no measurement, so a formula term over a measurement fails closed there. Shared-GPU
contention during latency timing is not detected; pair accelerator latency with an
exclusive host-ledger placement (`time_budgeted: true`). Replay reads persisted values
and never re-measures.

Closed follow-ups (not implemented): the `CandidateMeasurement` plugin family,
manifest-declared external hardware executors (`CandidateEvaluationExecutor` as a
component), and FLOPs/MACs counting.

Validation: `tests/unit/execute_tools/test_evaluation_measurements.py` (protocol
applicability, median timing without warm-up, checkpoint-derived values and failure
records, aggregation refusal reason, parent re-derivation, launch admission and the
record accessor).
