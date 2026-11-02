# `agent/schemas/` — node contracts and typed protocols

Technical inventory for this module. Start with [the directory guide](README.md)
for navigation. Source and tests determine current behavior.

## Purpose

The typed surface of the node graph. Every node's input and output is a
Pydantic `BaseModel` declared here, and every edge between nodes is a protocol
function declared in `protocols/`. Nodes communicate through **schema, storage
and protocols — and nothing else** (CLAUDE.md); this package is two of the
three.

## Public interface

Per-node contracts (one module each): `interpretation.py`, `proposal.py` (+
`proposer_evidence.py`), `implementor.py`, `validator.py`,
`hyperparam_tuning.py` (the largest — `ExperimentRecord`,
`HyperparamTuningOutput`, the status vocabulary, persisted health results),
`literature_review.py`. Cross-cutting contracts: `model_io_contract.py`
(`ModelIOContract` — the normalized forward contract), `training_diagnosis.py`,
`score_table.py`, `storage.py` (`LocalStorageConfig` — the workspace/run_name
namespace every node writes under), `ordering.py`, `vocab.py`,
`health_feedback.py`, `run_metadata.py`, `telemetry/`, `judge.py` (LLM judge
request/verdict/evidence records; see the
[judge contract](../judge/judge-contract.md)).

`output_types.py` owns the lightweight `OutputTypeName` vocabulary used by
proposal/implementor schemas, launch config, CLI and plugin loading.
`proposal.OutputTypeName` remains an explicit public re-export. The loader
derives its legal plugin tuple from this alias and adds builtin-only `hybrid`
only to its broader execution vocabulary; plugins cannot declare `hybrid`.

`judge_task.py` owns the task-declared judge inputs composed from the
manifest's optional `judge_blocks:` and `rubrics:` sections
([task composition](../../../docs/reference/task-composition.md#judge-guidance-and-rubrics)):
`JudgeTaskBlocks` (prose guidance; identity `judge_guidance_sha256`),
`RubricSpec` / `RubricCriterion` (`siderius.rubric/v1`; 1–32 criteria with
unique names, integer `scale_min < scale_max` with span `<= 100`,
`0 < weight <= 100`), `RubricRef` (`id`, `version`,
`sha256`), `rubric_sha256` (canonical-JSON digest of the validated spec) and
`resolve_rubric_ref`, which raises `RubricRefError` with `reason`
`unknown_rubric` or `digest_mismatch`. A rubric is not a metric: it carries no
total and no direction, and never enters `MetricOrder`. Totals are computed by
framework code from validated per-criterion integers, never by the LLM.

`protocols/` — one module per directed edge, named
`{source_code}_to_{target_code}.py` (e.g.
`ml_model_valid_to_ml_model_tune.py`). Functions inside are named
`{transport}_{data_scope}` (`local_all_records`, …), and every `local_*`
function has a `database_*` placeholder beside it.

## Inputs / Outputs

Upstream node `*Output` objects in; a fully populated downstream `*Input` out.
The input schema is the **completeness contract**: every field a downstream
node needs must exist on some upstream output and be mapped by the protocol —
no hidden contracts, no silent defaults.

## Owned semantics

- The field-mapping between nodes happens **only** in a protocol function.
- Proposer literature input accepts either the existing singular bounded
  projection or an ordered `reviews` collection of named projections. The
  collection preserves each contributor card, run identity, citation and claim;
  it does not combine or rank them. Each review and the complete collection
  must fit the 65,536-byte limit owned by
  `proposer_literature_evidence.py`. IDs remain unchanged in typed/serialized
  evidence; the [proposal renderer](../prompt_templates/proposal/README.md)
  owns single-line presentation of contribution IDs, contributor names and
  citation source labels in singular and collection evidence, and through the
  same `_single_line_label` owner the `AgentCard.agent_name` heading in
  `render_agent_cards` and the `ExpertContextItem` `source` / `source_ref` (and
  unlisted `kind`) labels in `render_expert_context`, and the
  `ProposerDataAnalysisEvidence` `report_ref.logical_ref`, `question_id`,
  `finding_id`, `method_skill_ids` / `method_generated_program_ids` items and
  `QuantitativeResult` `result_key` / `unit` in
  `render_data_analysis_evidence` (#1465, #1497; empty labels keep
  their bytes; deduplication keys on the raw `source_ref`). Multiline labels
  and labels beginning with a double quote use JSON string encoding so distinct
  raw labels remain distinguishable. Evidence prose remains multiline.
- `ProposalOutput.baseline_config` validates supplied `train_config` through
  `TrainConfig` before the proposer exits structural repair. It forwards normalized
  supplied values without filling omissions or removing extension keys. Null or
  non-object supplied training sections refuse. Segmentation sizes reject bool
  before task-specific divisibility validation; absent/null segmentation retains
  the existing optional-dimension behavior. See the
  [proposal contract](../../nodes/ml_model_proposal_agent/ml_model_proposal_agent.md)
  for advisory and retry ordering.
- Record vocabularies (statuses, verdicts as persisted strings) are declared
  here and are load-bearing for persisted history — additive evolution only.
- `extra="forbid"` on record-facing types where a misspelled key must refuse.
- `ParameterRule` declares exactly one kind by key presence. Only `exact`
  accepts null; a null `range` / `allowed` / `predicate` is refused instead
  of falling back to an exact-null kind, and `NumericRange` bounds are strict
  numbers (no bool or string coercion). `exact` / `allowed` values may not
  contain a non-finite real number (float, Decimal, numpy scalar) at any
  nesting depth, including mapping keys, and may not be cyclic or nested more
  than 64 levels; each is a validation error naming the rule path. Range
  bounds are finite.
- `ParameterRules` checks fixed `train_config` and `loss_config` paths against
  the consuming `TrainConfig` / `LossConfig` `model_fields` and nested model
  annotations, including optional unions. The shared document resolver
  repeats this check so a mutated rule dictionary cannot introduce a silently
  ignored execution lock. Exact rules may insert omitted valid leaves. The
  resolver also checks `model_config` paths against the executed model's
  config class (`get_config_class(executed_model_type)`; the caller passes
  `force_model` or the plan's top-level `model_type`, which is the default).
  A `model_config.model_type` rule is validated against the executed type and
  never selects it. The tuner fails closed when the class is unregistered;
  only proposal-baseline resolution (`defer_unknown_model`, with the proposed
  model name as `executed_model_type`) defers. `extra="allow"` configs accept
  unknown keys. `validate_model_parameter_rules` runs the full resolver once at
  tuner launch for a fixed `force_model`, on an empty model configuration with
  only planner-chosen values deferred. The same target check refuses boolean
  `exact` / `allowed` values on a field whose type does not admit `bool`.
  See the [parameter-rule contract](../../../docs/reference/task-composition.md)
  for sampling ownership, composition conflicts and value-validation boundaries.

## Non-owned semantics

- Node behaviour → `nodes/`; execution → `execute_tools/`; storage layout
  narrative → [workspaces and resume](../../../docs/guides/workspaces-and-resume.md);
  the graph rules → [architecture](../../../docs/architecture.md).

## Extension points

A new edge = a new protocol module following the naming convention + tests
(steps 2/4/6 of [`nodes/NODE_TEMPLATE.md`](../../nodes/NODE_TEMPLATE.md)).
A new cross-node value travels: producer output schema → protocol mapping →
consumer input schema — never through a file read by convention.

## State and filesystem effects

None at import; nodes persist their own records under
`{workspace}/{node}_{run_name}.json` via `storage.py` config (a **log, never a
channel**).

## Failure modes

Pydantic validation errors at node boundaries — the system's first line of
defence against raw LLM output reaching execution; a protocol that drops a
required field fails the downstream input validation, loudly.

## Files normally edited

The schema of the node whose contract is changing, plus **both** ends of every
affected protocol, plus the connection audit (NODE_TEMPLATE step 7).

## Files normally NOT edited

Persisted-record field names and status strings (history depends on them);
`__init__.py` of `protocols/` beyond mechanical re-exports.

## Minimal example

```python
from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import (
    local_validated_model,
)
tuner_input = local_validated_model(validation_output, ...)  # the ONLY mapping site
```

## Related tests

`tests/unit/agent/` per-node schema suites and
`tests/unit/agent/protocols/`; golden record baselines under the tuner's
test goldens pin persisted shapes.

## Persisted output encoding

Native output schemas derive from `core.record_encoding.RecordModel` (literature
through `ExternalAgentOutput`). Its validation entry points decode versioned
non-finite record metadata before running native validators; field declarations,
JSON schema and in-memory dumps are unchanged. `ExperimentRecord` uses the same
reader. The [core contract](../../core/core-contract.md#versioned-non-finite-record-json-issue-1111)
owns the encoding and legacy behavior. Do not reimplement null/string conversion
in a node or protocol. The census walks all reachable output field annotations,
including `Any` containers and required float leaves.

## Conditional loss rules and attempt receipts

`LossConfig.inactive_parameter_values` owns activity. A rule constrains its
field only when active; it never implicitly restricts planner loss choice.
`ParameterRules` and the combined ownership gate refuse dead rules when exact
or singleton-allowed declarations fix an incompatible type. The shared
resolver repeats this check, then skips inactive field constraints for a
planner-selected type and logs the decision. Missing inactive values need not
exist and inactive predicates are not called. Active rules retain ordinary
exact/conflict/value enforcement.

`InactiveParameterRule` contains `path`, `owner` (task/workflow), `loss_type`,
`rule` (typed `ParameterRule`) and `reason="inactive_for_selected_loss"`.
`apply_parameter_rules` recomputes `ExperimentPlan.inactive_parameter_rules`
every call; the tuner transports it to the identically typed
`ExperimentRecord.inactive_parameter_rules` at the common emission boundary.
Both fields default to empty and are excluded from dumps when empty, preserving
legacy no-receipt record shapes. Planner history retains the record field even
when condensed. Unknown proposal types defer activity; omitted strict-plan types
use the LossConfig default. Ordinary LossConfig normalization is unchanged.

### Data Analysis canonical identities

`data_analysis.common` owns the UTF-8 canonical identity convention used by
Data Analysis and judge consumers. Its
[canonical identity contract](data_analysis/canonical-identity-contract.md)
specifies strict non-finite records, `FrozenModel` decoding, legacy verification
and the finite-byte compatibility boundary. The non-finite codec remains owned
by `core.record_encoding`; schemas do not define another encoder.

## Attempt resolution receipts

`ExperimentRecord.resolution_events` is a tuple of the existing
`ResolutionEvent` (`field_path`, `proposed`, `executed`, `authority`) copied
from the final `ExecutionProvenance.events` of the attempt (issue #1322). It
defaults to empty and is excluded from dumps when empty, so a record whose plan
survived resolution, and every record written before the field, keeps its
shape. Empty therefore means "no recorded divergence", not proof of agreement
for archived records. The intermediate `plan_resolution_events` comparison is
not persisted. Like inactive-rule receipts it is transported through
`record_params` and promoted at the tuner's common emission boundary, so the
persisted `params` stay a pure configuration. Planner history retains it in
recent and condensed records; see the
[tuner contract](../../nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md#condensed-planner-history-resolution-receipts-issue-1322).

## Trial schedule refusal identity

`hyperparam_tuning.validate_trial_override_schedule` retains its existing admission
predicate and remedy text, raising `PydanticCustomError` with type
`trial_override_schedule` when Trial overrides would apply to zero tuning rounds.
It remains a `ValueError` for direct callers; Pydantic preserves the type in native
validation details. This lets declaration and HTTP projections identify the refusal
without interpreting message text or repeating schedule rules. No valid launch,
training defaults or emitted prompt text changes. The schema file participates in
rendering and estimation assembly identities; its source change updates those hashes.
