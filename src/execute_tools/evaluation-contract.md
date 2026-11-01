# Evaluation declarations and launch admission

Owners: `evaluation_spec.py` (Pydantic declarations), `evaluation_registry.py`
(kind registration and capability table), `evaluation_validation.py` (cross-model
validation and inspection), `workflows/evaluation_composition.py` (resolution and
canonical identity). The existing task composer delegates to these owners.

## Availability and boundaries

`evaluation:` is optional. Absence preserves previous semantic fingerprint inputs,
source metric behavior and prompt bytes. Presence permits composition and inspection,
but launch currently refuses: `evaluation rendering` is not implemented until
#1293. Formula aggregation (#1294), feasibility (#1295), measurements (#1296) and
rubric execution (#1297) have independent capability gates. Composition never
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
New fields must have defaults, and default values must be omitted from canonical
identity (`exclude_defaults=True`). Explicit default and omitted default are equal.

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

Measurement is NOT a builtin E1 schema. #1296 adds it by registering a variant.
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
  mandatory and cannot recursively be rubric_balance. Rubric selection is only
  used by admitted judged paths once #1297 lands, not by every selection site.

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
quantitative evidence for formula execution (constraint execution remains #1295). Merely listing it as a component leaves it
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
ComponentRenderContext)` is a pure hook for #1293, unused by prompts in E1.
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

#1293 wires one `evaluation.spec` renderer; historical exp profiles require an
explicit empty override and offline qualification. #1295 owns feasibility at all
selection sites; #1296 supplies measurement schema/execution; #1297 owns candidate
result projection and versioned replayable judge calls. Existing metric-scored
adaptor restrictions remain until deliberately amended by their owner.

Composition scales with declaration/plugin bytes, not dataset size; it loads no
scientific data, tensors or GPU work. Bounds are authored values, never caps on
TIDMAD or other task dataset lengths. Deferred compatible extensions: #1307, #1308.

## Validation

`tests/unit/workflows/test_evaluation_composition.py` covers real composer and
launch paths, resume refusal with unchanged source MetricSpec, reference resolution,
inspection, plugin identity/isolation/relocation, defaulted schema extension and
rubric digest resolution. Full affected package suites and the separately recorded
baseline comparison establish integration evidence; declarations alone do not
establish runtime evaluation support.

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

The parent validates the child identity, required component roster and scalar
agreement before adopting results. Structured refusal evidence survives child exit
1 into `error_scoring` / `failure_type=not_scoreable` and `metric_refusal`.
Scope and package-integrity exceptions retain their existing terminal handling.
The record field is omitted when evaluation is absent. Historical records are not
recomputed. Existing composition locks and metric reconciliation reject changed
formula identities and mixed source/effective ranking histories.

Health receives the original source scalar and vector through
`evaluation_child.source_health_inputs`; `round_health` independently checks the
selection scalar's validity. Formula utility never replaces a task Health input.
Existing Health validity filtering still precedes MetricOrder ranking. Effective
identity travels through tuner best tracks, chain history, resume, interpretation,
proposal evidence, adaptors, reports and dashboard ranking. Source per-file values
must not be labelled as utility evidence.

### Admission and threshold units

`workflows/evaluation_admission.py` owns formula admission. Only native TASK_OWNED
scoring-child execution is supported. ANCHOR_NORMALIZED and
CandidateEvaluationExecutor combinations refuse; their child handoffs are #1336.
Referenced custom quantitative kinds without runtime values refuse by component
name and kind (#1338). Constraints and rubric capabilities remain independently
gated; enabling formula aggregation does not enable them or evaluation rendering.

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
