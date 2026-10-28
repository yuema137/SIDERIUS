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
  `proposer_literature_evidence.py`.
- Record vocabularies (statuses, verdicts as persisted strings) are declared
  here and are load-bearing for persisted history — additive evolution only.
- `extra="forbid"` on record-facing types where a misspelled key must refuse.
- `ParameterRule` declares exactly one kind by key presence. Only `exact`
  accepts null; a null `range` / `allowed` / `predicate` is refused instead
  of falling back to an exact-null kind, and `NumericRange` bounds are strict
  numbers (no bool or string coercion).
- `ParameterRules` checks fixed `train_config` and `loss_config` paths against
  the consuming `TrainConfig` / `LossConfig` `model_fields` and nested model
  annotations, including optional unions. The shared document resolver
  repeats this check so a mutated rule dictionary cannot introduce a silently
  ignored execution lock. Exact rules may insert omitted valid leaves. The
  resolver also checks `model_config` paths against the selected model's
  config class (`get_config_class` of the locked or authored `model_type`);
  unregistered model types are not checked, and `extra="allow"` configs
  accept unknown keys.
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
