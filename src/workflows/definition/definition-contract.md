# Workflow declaration contract

## Scope and owners

Version 1 is an offline, within-iteration declaration format. It describes
literature, proposal, implementation, validation and tuning capabilities; it does not instantiate
nodes, invoke protocols, inspect files, import user code or execute graphs.
`catalog.py` is a closed inventory of supported native boundaries. Catalog owner
strings are documentation, never dynamic import instructions. Native schemas
and protocol functions remain authoritative for runtime semantics.

Each capability has one complete request and a `result` output. Protocol
arguments are logical bindings, not arbitrary schema-field connections.
`proposal-to-implementation` references `local_full_spec` in
`agent.schemas.protocols.ml_model_propose_to_ml_model_impl`.
`implementation-to-validation` references `local_all_fields` in
`agent.schemas.protocols.ml_model_impl_to_ml_model_valid`.
Tests compare their complete parameter names, annotations, requiredness and
return types with the catalog. Omitted optional arguments retain native default
ownership; this package neither resolves nor certifies those effective values.

`adaptor_strategies.py` holds the closed, versioned adaptor strategy declarations,
the shared B6 types (`SelectStrategy`, `CardinalityBound`, `Fallback`,
`derive_cardinality`) and `incompatible_pair`; `catalog.py` holds
`ADAPTOR_STRATEGIES`, `SPLITTABLE_ITEMS` and `RANKABLE_FIELDS`. Documents declare
adaptors under [Adaptor declarations](#adaptor-declarations-inert); run-time
semantics: [adaptor contract](../adaptors/adaptor-contract.md). `base.py` holds the
shared `DeclarationModel`, `Identifier` and `Location` (re-exported by `models.py`).

## Construction and interchange

```python
from workflows.definition import (
    ExternalBinding, ExternalRequest, NodeInstance, TaskReferences,
    WorkflowDefinition, WorkflowDocument, inspect_declaration,
)

document = WorkflowDocument(
    definition=WorkflowDefinition(
        task=TaskReferences(
            manifest="task/manifest.json",
            data_root="/data/my-task",
            workspace="runs/new-run",
        ),
        externals=(ExternalBinding(
            id="request", contract="proposal.input", location="inputs/proposal.json",
        ),),
        nodes=(NodeInstance(
            id="proposal", capability="proposal",
            request=ExternalRequest(binding="request"),
        ),),
    ),
)
encoded = document.model_dump_json(indent=2)
assert WorkflowDocument.model_validate_json(encoded) == document
assert inspect_declaration(document).execution_ready is False
```

`ProtocolRequest` names a protocol and contains a tuple of `ArgumentBinding`
objects. Each argument's `source` is either `ExternalSource(binding=...)` or
`ResultSource(node=..., port="result")`. Required `output` and `storage`
arguments must be present. Optional context, task-composition or LLM arguments
are available only where declared by that specific native protocol. No argument
is inferred from the task references or another node's storage.

External bindings declare the **whole** contract of a referenced value. Nullable
contracts are distinct exact catalog contracts, not subtype inference. Locations
are inert strings: no file existence, serialization format, schema contents,
artifact provenance or digest is verified. Relative references are intended for
a future caller's external project directory, never the infrastructure checkout;
this version does not resolve them. Task manifest, data root and workspace are
separate declared locations, not verified runtime bindings.

## Validation and immutability

Models reject extra fields and use frozen objects and tuple collections. Use
normal constructors or `model_validate_json`, not unchecked Pydantic
`model_construct`/`model_copy(update=...)`, for trusted declarations.
`inspect_declaration` revalidates its document before returning a report.

Validation rejects unknown capabilities, protocols and contracts; duplicate node
or external IDs; duplicate, missing or unknown protocol arguments; dangling
references; unknown result ports; exact-contract mismatches; and directed cycles.
Node and external IDs occupy separate namespaces. Unused declared externals and
multiple consumers of a result are allowed. Reusing a result does not generate
multiple candidates or schedule parallel execution. Disconnected nodes with
complete external request declarations are allowed.

Apart from the optional authored `loop` described under
[Authored loop](#authored-loop), the inert `routes` described under
[Route declarations](#route-declarations-inert) and the inert `adaptors` described under
[Adaptor declarations](#adaptor-declarations-inert), there are no custom/generation/aggregation
adapter, feedback, arbitrary-code, constructor configuration or
execution-control fields. Supplying such fields fails validation. Future support
requires an audited native owner and an explicit format extension. No generic
subtyping, JSON-schema assignment or execution inference is implemented.

Positions refer to known nodes at most once and accept finite coordinates.
They are presentation-only and do not establish execution order. Dependency
validation uses an iterative topological check, without a recursive depth limit.

## Identity and compatibility

`definition.declaration_digest()` hashes canonical JSON of the declared values,
including location strings and ordered declaration lists. Canvas positions are
excluded. Changing list order may change the digest even if the graph has the
same topology. This is a **declaration digest**, not execution, checkpoint or
reproduction identity: referenced bytes, package revisions and native defaults
can change without changing it. Existing run invariants and task fingerprints
remain authoritative for actual execution.

`DeclarationReport.status` is `declaration_validated`, never execution-ready.
Its unresolved checks include native payload validation, task/data/workspace
bindings, constructors/model routing/defaults, environment and lifecycle.

This additive package is not imported by existing launchers or workflows.
It changes no historical prompts, training defaults or paper execution paths.
It does not promise that a future graph executor reproduces those paths; that
requires separate integration and experiment-owned historical configuration.

## Authored loop

`WorkflowDefinition.loop` and `ReusableWorkflowDefinition.loop` optionally carry
`AuthoredLoop(final_iteration, feedback, stop_conditions=())`. `final_iteration`
is a positive body count; it is a ceiling, not a budget or a promise that every
body runs. `feedback` is one `LoopFeedback(source=ResultSource(node=...),
target=..., protocol="tuning-to-interpretation", history="native-research/v1")`;
these literals are the only accepted protocol and history. Validation requires the
source node to have capability `tuning` and the target node capability
`interpretation`. An absent loop is omitted from serialization, so a loop-free
declaration's digest is unchanged. Execution admission (the supported
`native-interpretation-candidate/v1` five-node body), Stop and Pause/Resume belong
to the [candidate-worker contract](../../tools/candidate_worker/candidate-worker-contract.md#declared-finite-research-body).

### Authored loop stop conditions

`AuthoredLoop(final_iteration, feedback, stop_conditions=())` optionally declares
stop criteria, a tuple of the discriminated `StopCondition` union (`kind` is the
discriminator): two deterministic hard criteria and one LLM-judged criterion:

| Constructor | Fields | Meaning |
| --- | --- | --- |
| `MetricThresholdStop` | `kind="metric_threshold"`, `metric_id: str` (non-empty, required), `threshold: float` (finite) | stop once the loop incumbent is at least `threshold` under the run metric's direction |
| `NoImprovementStop` | `kind="no_improvement"`, `completed_bodies: int` (> 0, < `final_iteration`) | stop after that many consecutive completed bodies without a strict incumbent improvement |
| `JudgeStop` | `kind="judge"`, `criterion: str` (1..2000 chars, required), `min_completed_bodies: int = 1` (> 0, < `final_iteration`), `on_failure: "fail" \| "continue" = "fail"` | ask the operator-routed LLM stop judge whether to stop, only when no deterministic condition fired |

Direction is never declared: it comes from the run's `MetricSpec`, and
`metric_id` must equal that spec's opaque id at execution time. Validation refuses
more than one condition of the same kind, a `completed_bodies` that cannot be
reached before the final iteration, and a judge `min_completed_bodies` at or above
`final_iteration` (the final boundary is never judged). Deterministic conditions are
any-of in declared order (a disjunctive stop, not a graph join). A `JudgeStop` is
always consulted after them, whatever its declared position; its position only
fixes its `condition_index`. The judge's model route is not part of the declaration:
it is the operator's `WorkflowLLMConfig.judge.stop`, and every field of `JudgeStop`
renders in canonical source (defaults included). An empty tuple is omitted from serialization
and canonical source, so the declaration digest and source bytes of a loop without
conditions are unchanged. Execution semantics, precedence and readback belong to
the candidate-worker contract ("Deterministic stop conditions" and "Judge stop
condition").

## Route declarations

`WorkflowDefinition.routes` and `ReusableWorkflowDefinition.routes` optionally carry
up to 32 `Branch` declarations. An empty tuple is omitted from serialization and
canonical source, so existing declaration digests, source bytes and receipts are
unchanged. `candidate.refuse_declaration_only(definition, *, admits_adaptors=False,
admits_routes=False)`, called first by the shared shape checks
`candidate.candidate_nodes` and `fanout.execution_families`, refuses any document with
routes ("conditional routing is declared but this execution profile does not admit
it", `ROUTING_NOT_ADMITTED`) unless `admits_routes=True`. Only `execution_families`
for `fanout.ROUTED_PROFILE` (`native-routed-candidate/v1`, v1 preview and worker only;
B1-PR5) passes it: that profile admits the S1 selection node set
(`fanout.selection_candidate`) plus at least one route, and refuses a document without
routes ("the routed profile requires at least one declared route"). Every other
profile, the fixed candidate, v2 reusable sources (including a v2 document with
`training_settings`, whose declaration validation runs those checks), managed
preparation and the console still refuse routed documents. Run-time semantics: the
candidate-worker contract, "Routed execution profile".

### Readable fields

A predicate reads only a field listed in `catalog.ROUTE_OBSERVABLES` for the branch
source's capability output contract; free field names and JSON paths do not exist.

| Observable | Contract | Native field | Kind |
| --- | --- | --- | --- |
| `validation.passed` | `validation.output` | `ValidatorOutput.passed` | bool |
| `tuning.status` | `tuning.output` | `HyperparamTuningOutput.status` | enum `completed`, `partial`, `failed` |
| `tuning.valid_formal` | `tuning.output` | `HyperparamTuningOutput.best_valid_formal_denoising_score` | metric (`float | None`) |

`tests/unit/workflows/test_workflow_routes.py` checks each row against the native schema.
Adding an observable is a catalog row plus that check.

### Predicates

`RoutePredicate` is a `kind`-discriminated union of leaves and one combinator level:

| Constructor | Fields | Reads | Meaning |
| --- | --- | --- | --- |
| `BoolIs` | `kind="bool_is"`, `observable`, `value: bool` | bool | field equals `value` |
| `EnumIn` | `kind="enum_in"`, `observable`, `values: tuple[str, ...]` (nonempty, unique, catalogued) | enum | field is one of `values` |
| `MetricAtLeast` | `kind="metric_at_least"`, `observable`, `metric_id: str` (nonempty), `threshold: float` (finite) | metric | a present value is at least `threshold` under the run metric's direction |
| `IsMissing` | `kind="is_missing"`, `observable` | metric | the value is absent |
| `AllOf` / `AnyOf` | `terms`: 2 to 8 leaves | — | conjunction / disjunction |
| `Not` | `term`: one leaf | — | negation |

Combinators contain leaves only (no nesting), so a predicate has at most 8 leaves.
Every leaf reads the branch's single source result; cross-node predicates need a typed
aggregation owner and are not expressible. Direction is never declared: `metric_id` must
equal the run `MetricSpec` id, checked by `tools.candidate_worker.route_eval.admit_route_metrics`,
called by the routed worker before any dispatch (`route_phase.admit_route_metric`). An absent metric makes `MetricAtLeast` false, never
an error; `IsMissing` makes that case explicit. Evaluation belongs to the pure route
evaluator (candidate-worker contract, "Route evaluator").

### Branches, arms and merges

`Branch(id, source=ResultSource(...), cases=(RouteCase(when, targets), ...), default=None)`
declares 1 to 8 ordered cases; the first matching case wins. `default` is `None`
(omitted from serialization) or a nonempty tuple of entry nodes. With no default and no
matching case, no arm runs; a single-case branch without a default is a guard.
Branch ids are their own namespace and must be unique.

Each target receives a control edge from the branch source, which joins the topological
check: a target that is the source or one of its ancestors fails as a cycle. The **arm**
of a case (or the default) is every node reachable from the source whose every path from
the source passes through one of that entry's targets. Validation refuses:

- unknown route nodes, uncatalogued observables, a leaf whose kind does not fit the
  observable, and enum values that repeat or are not catalogued;
- a node that is a target twice, in two cases, or of two branches (nested branching uses
  a branch whose source lies inside an arm);
- a node that depends on two arms of one branch except through a merge;
- a `SelectedSource(branch, candidates=(ResultSource, ...))` merge argument whose branch
  is unknown or has no `default` (otherwise no arm might run and the merge would starve),
  whose candidates (at least 2) do not share the argument's output contract, or do not lie
  one in each arm (every case plus the default). Full coverage places a non-target consumer
  outside every arm;
- a merge consumer that also depends on an arm of the branch it merges through another
  data or control edge, or that is itself a target of that branch;
- with a `loop`, any arm containing the loop feedback source or any of its predecessors,
  including merge candidates (decision Q5(a); conservative in v1).

Arms of different cases are disjoint by construction: distinct targets each have a
direct control edge from the source. A merge is a deterministic select keyed by the
recorded decision, not an OR/race join; its consumer depends on every candidate for
scheduling. Readiness skip semantics (`skipped`/`route_not_selected`, merge resolution,
skip propagation) are owned by `tools.candidate_worker.readiness` (candidate-worker
contract, readiness authority); decision evidence belongs to the candidate-worker
`route_phase`.

Public arm helpers (`workflows.definition.routes`, for a validated definition):
`route_entries(branch)` (entry targets per case, then the default);
`branch_arms(definition, facts)` (each branch's arms in that order; `facts` from
`validation.predecessor_facts`, control edges included); `route_targets(definition)`
(entry target → `RouteTarget(branch, source, control_only)`, where `control_only`
means the target binds no data from the branch source, so readiness lets a `rejected`
source's decision run it: the B1-Q1 fallback); `merge_arms(definition, facts)`
(merge consumer → one `MergeArms(branch, candidates=(MergeArm(node, entry), ...))` per
`SelectedSource` argument). An adaptor carries no arm label (it runs whichever arm was
selected, B6-D8), which the routed profile relies on: its selection adaptor reads one
validator outside and one inside the fallback arm.

## Adaptor declarations (inert)

`WorkflowDefinition` and `ReusableWorkflowDefinition` optionally carry
`adaptor_format: Literal["siderius.adaptors/v1"] | None` and
`adaptors: tuple[AdaptorInstance, ...]` (decision B6-D2: optional gated fields on v1
and v2, because the worker consumes v1). `None` and `()` are omitted from
serialization and canonical source, so documents without adaptors keep their
declaration digests and source bytes (pinned: the shipped examples in
`test_workflow_routes.py`, a loop document with stop conditions in
`test_adaptor_declarations.py`). Adaptors execute only under the opt-in v1
execution profiles `fanout.SELECTION_PROFILE` (`native-proposal-fanout-selection/v1`,
B6-3; shape and run-time semantics in the candidate-worker contract, "Opt-in
first-passing selection"), `fanout.ROUTED_PROFILE` (same node set plus routes) and the
B6-4 literature profiles `fanout.LITERATURE_COLLECTION_PROFILE`
(`native-literature-collection/v1`, S2) and `fanout.LITERATURE_SPLIT_PROFILE`
(`native-literature-split/v1`, S3; candidate-worker contract, "Literature adaptor
profiles"), and the B6-8a `fanout.LITERATURE_JUDGED_PROFILE`
(`native-literature-judged/v1`), the only profile that executes an LLM COMBINE
kind; `fanout.ADAPTOR_PROFILES` lists all five. `AdaptorInstance.combine` is
`llm_strategies.AdaptorCombine` (the deterministic kinds plus the four B2 LLM kinds);
declaration validation applies the table rows that need no B2 owner (a ranking LLM
kind feeds `top-k/v1`/`all/v1`; `threshold/v1` basis `rubric` reads only
`rubric-rank/v1`) and imports no agent module beyond the pydantic-only
`agent.schemas.judge_refs` (`RubricRef`, `MAX_DEBATE_ROUNDS`; the import-guard test
allowlists exactly it and proves `agent.schemas.judge_task` still trips it). The kind's
own rules (`admit_llm_strategy`) run at profile admission. `candidate.refuse_declaration_only(definition, *,
admits_adaptors=False)` refuses any document with `adaptor_format` ("adaptors are
declared but this execution profile does not admit them", `ADAPTORS_NOT_ADMITTED`),
after the routing refusal, in every shape check that preview, preparation, worker and
verifier admission use; only `execution_families` for the `ADAPTOR_PROFILES` passes
`admits_adaptors=True`. The reusable (v2) document, preparation and console profile
lists include none of them yet (B6-7), so a v2 document cannot declare adaptors. `candidate_prepare.resolution` nevertheless carries `routes`,
`adaptor_format` and `adaptors` verbatim into the effective v1 definition.

### Models

| Constructor | Fields | Notes |
| --- | --- | --- |
| `AdaptorInstance` | `id`, `kind="adaptor"`, `inputs: tuple[InputPort, ...]` (≥ 1), `bindings: tuple[PortBinding, ...]`, `combine: DeterministicCombine`, `select: SelectStrategy`, `distribute: DistributeStrategy` | one model (B6-D1); the output contract is derived, never authored |
| `InputPort` | `name`, `contract` (exact catalogue contract), `cardinality: "one" \| "many"`, `min_items: int ≥ 0 = 1`, `max_items: int > 0 \| None` (omitted when `None`) | a `one` port keeps `min_items=1` and declares no `max_items` |
| `PortBinding` | `port`, `sources: tuple[Source, ...]` | declared order is every tie-break and "first" order |
| `AdaptorSource` | `kind="adaptor"`, `adaptor`, `port="result"`, `index: int ≥ 0 \| None` (omitted when `None`) | new `Source` variant: a protocol argument, a port source, or an `AdaptorRequest` source |
| `AdaptorRequest` | `kind="adaptor"`, `source: AdaptorSource` | new `Request` variant: a whole capability request; the derived contract must equal the capability input |

Strategy constructors are the B6-2 models (`PassCombine`, `CollectCombine`,
`ConcatItemsCombine`, `MetricRankCombine`, `FieldRankCombine`; `AllSelect`,
`FirstAdmissibleSelect`, `TopKSelect`, `ThresholdSelect`; `SingleDistribute`,
`PerItemDistribute`, `SplitItemsDistribute`, `ReplicateDistribute`).
`catalog.ADAPTOR_STRATEGIES` maps every declarable kind string to
`AdaptorStrategyContract(stage, declaration, owner)` (inert strings, like
`PROTOCOLS`); a test keeps it equal to the three discriminated unions. LLM kinds
(B2) and `custom/v1` (B6-5/B6-6) are not declarable yet; they join the unions and
the catalogue with their owners. The LLM kinds' declaration models already exist
in `llm_strategies.py` (`LLMStrategy`, B2-6,
[strategy contract](../judge_strategies/judge-strategies-contract.md)); B6-8 adds
them to `AdaptorInstance.combine` and the catalogue.

A port source may be `ExternalSource`, `ResultSource`, `AdaptorSource` or a route
merge `SelectedSource` (decision 2026-10-28): the merge resolves at run time to the one
selected candidate's result, which is what record provenance (`AdaptorInputRef.source`,
a concrete origin) names.

### Format gate and graph

- Any adaptor, `AdaptorSource` argument or `AdaptorRequest` requires
  `adaptor_format="siderius.adaptors/v1"`; a format with nothing using it is refused.
  The gate runs before reference checks.
- Adaptor ids share the node namespace (unique, distinct from node ids). Externals
  stay separate. Route targets and branch sources remain nodes.
- Each adaptor's sources add dependency edges; consumers of an `AdaptorSource` depend
  on the adaptor. Adaptors join the same Kahn cycle check and topological order
  (`predecessor_facts` includes adaptor vertices). Adaptors are checked before node
  requests, so a consumer never reports a symptom of an invalid adaptor.
- Route checks treat adaptors as vertices: a merge into an adaptor port must cover
  every arm of a branch with a default. Unlike a node, an adaptor may depend on two
  exclusive arms of one branch without a merge (B6-3): it is ready once every source
  is terminal and a skipped source is inadmissible (B6-D8), so it never inherits a
  skip. It therefore carries no arm label to its consumers.

### Validation table (`adaptor_validation.py`)

Refused with a fixed message naming the adaptor (never coerced):

| Rule | Refusal |
| --- | --- |
| ports and bindings | duplicate port names or bindings; a port without exactly one binding; no source at all |
| item bounds | `len(sources)` outside `min_items..max_items` (a `one` port: exactly 1) |
| contracts | port contract not in `CONTRACTS`; a source whose resolved contract differs from its port contract; ports of different contracts (every deterministic kind has one element contract) |
| derived output | `output_contract` is the element contract, except `collect/v1`, whose output is `catalog.COLLECTION_CONTRACTS[element]` (`literature.output` → `literature.collection`, B6-4); `collect/v1` over an element without an entry (e.g. `tuning.output`, B6-9) is refused ("collect/v1 has no catalogued collection contract for …") |
| COMBINE applicability | `concat-items/v1` field must equal `SPLITTABLE_ITEMS[contract]`; `metric-rank/v1` only over `METRIC_SCORED_CONTRACTS`; `field-rank/v1` field must equal `RANKABLE_FIELDS[contract].item_field` and its ports must hold exactly one value |
| COMBINE/DISTRIBUTE pair | `incompatible_pair`: `per-item/v1` after `collect/v1`, `concat-items/v1` or `field-rank/v1`; `split-items/v1` after `collect/v1` (the same owner the strategy core calls at run time) |
| SELECT/COMBINE | `first-admissible/v1` requires `pass/v1`; `top-k/v1` and `threshold/v1` require a ranking (`metric-rank/v1`, `field-rank/v1`); `threshold/v1` requires its basis' ranking (`metric` → `metric-rank/v1`; `rubric` → a B2 rubric ranking, so refused until B2) |
| split field | `split-items/v1` field must equal `SPLITTABLE_ITEMS[contract]` |
| cardinality | `derive_cardinality(select, distribute)` must be satisfiable |
| value count (`pass`/`metric-rank`) | `top-k/v1` `k` must not exceed what DISTRIBUTE accepts (`single`/`replicate`: 1, `per-item`: `count`); `all/v1`/`threshold/v1` require the number of bound sources ≤ the derived bound max (the bound excludes the source count; topology is static, B6-D6, so `max_items` is not used) |
| value count (`field-rank`) | `top-k/v1` `k` must not exceed `split-items/v1` `count` |
| unfillable split (`field-rank`) | `top-k/v1(k)` then `split-items/v1(count > k, on_short="fail")`: at most `k` entries survive, so the adaptor could only fail |
| output index | `AdaptorSource.index` is absent for `single/v1` and `< count` for `per-item`/`split-items`/`replicate` |

Run-time-only facts (list lengths, admissibility, metric identity) stay with the
strategy core, which re-checks every rule it relies on.

## Static Python source bridge

`parse_workflow_source(source: str) -> AuthoredWorkflowDocument` and
`render_workflow_source(document: AuthoredWorkflowDocument) -> str` convert a dedicated
source module and the existing document model. The construction example above
also performs JSON/report operations; those extra statements are not accepted
in a dedicated source module.

Accepted modules contain optional initial docstring/comments, exactly one
absolute `from workflows.definition import ...` and one ordinary single-target
`document = WorkflowDocument(...)` or `document = ReusableWorkflowDocument(...)` assignment. Imports contain unique bare names
from this explicit allowlist: `TaskReferences`, `ExternalBinding`,
`ExternalSource`, `ResultSource`, `ArgumentBinding`, `ExternalRequest`,
`ProtocolRequest`, `NodeInstance`, `WorkflowDefinition`, `NodePosition`,
`WorkflowDocument`, `ReusableTaskReferences`, `ManagedCandidateBinding`,
`CandidatePreparationOptions`, `ReusableWorkflowDefinition`,
`ReusableWorkflowDocument`, plus the loop constructors `AuthoredLoop`, `LoopFeedback`,
`MetricThresholdStop`, `NoImprovementStop` and `JudgeStop`, plus the route constructors `Branch`, `RouteCase`, `BoolIs`, `EnumIn`,
`MetricAtLeast`, `IsMissing`, `AllOf`, `AnyOf`, `Not` and `SelectedSource`, plus the
adaptor constructors `AdaptorInstance`, `InputPort`, `PortBinding`, `AdaptorSource`,
`AdaptorRequest` and the thirteen strategy constructors listed under
[Adaptor declarations](#adaptor-declarations-inert). The
renderer imports loop, route and adaptor constructors only when the document uses them, so
existing canonical source bytes are unchanged. Imported unused constructors are allowed; referenced
constructors must be imported. Aliases, wildcard and relative imports fail.

Only imported bare constructors with unique known keyword arguments, literal
strings/integers/finite floats/booleans/None, and literal tuples are accepted.
Unary `+`/`-` is allowed only directly on numeric constants, excluding booleans.
Lists, mappings, sets, starred values, positional arguments, expression names,
attribute calls, arbitrary calls, arithmetic, f-strings, comprehensions, control
flow and all other statements or expressions fail closed. Schema validation
still determines which accepted literal values fit each field. The whole
module shape, resource budgets and expression grammar are checked before any
model construction. Native constructors remain the sole graph-validation owner.

The bridge reads AST data; it never evaluates selected code, imports its module
or referenced plugins, resolves locations, opens resources or starts processes.
Admission limits are 1 MiB of UTF-8 source, 100,000 AST nodes and AST depth 64
(module depth 1, including context/operator nodes). Resource inspection is
iterative. Parser syntax/recursion and numeric conversion failures become bridge
diagnostics. These are converter limits, not document-schema limits. Parsing
runs in process and does not provide hostile-input memory/time isolation.

`WorkflowSourceError` carries a nonempty tuple of frozen `SourceDiagnostic`
models. Codes are `syntax`, `unsupported`, `limit` or `validation`. Optional
`line`/`end_line` are one-based; `column`/`end_column` are zero-based UTF-8 byte
offsets, with exclusive end positions. Missing whole-input spans are `None`.
Validation points to the enclosing failing constructor and, where available,
`field_path`; unknown location components are redacted. Diagnostics use fixed
summaries, never raw values, arbitrary native validator messages or Pydantic
input/context. No partial document is returned.

Rendering revalidates through a JSON roundtrip before formatting, including
unchecked Pydantic instances. It writes a fixed header/import order, all model
fields in schema order including defaults, ordered tuples and a final newline.
It verifies the generated text with the same parser and refuses output exceeding
the bridge budgets. Parsing rendered output equals the revalidated document;
rendering it again produces identical text. Omitted protocol arguments stay
omitted. Positions survive conversion but remain outside the declaration digest.

Canonical rendering discards original comments, docstrings and formatting. It
proposes complete replacement text for a dedicated module, never a patch against
arbitrary Python. Successful conversion and declaration digest equality do not
certify runtime readiness, immutable dependency identity or scientific equivalence.
For Python-authored projects source is authoritative and JSON is an explicit
export; existing JSON callers keep their explicit authority. Launchers do not
automatically select a representation. GUI saving, revision publication,
conflict handling and immutable launches are separate work.

## Offline conversion CLI

`python -m workflows.definition to-json --input PATH` reads restricted Python
source and prints indented `WorkflowDocument` JSON. `to-python --input PATH`
reads either document variant through the validated `AuthoredWorkflowDocument` union and
prints canonical source through the same renderer. Both require an explicit
UTF-8 input file; there is no stdin mode, format inference, output-path argument,
in-place edit or overwrite flag. JSON input shares the 1 MiB byte limit. Reads
are bounded to limit + 1 bytes before decoding or parsing.

Exit 0 produces complete converted content on stdout without a banner. Syntax,
unsupported source, model validation, limit, encoding or file-read failures exit
2, emit a concise stderr diagnostic and no converted stdout bytes. JSON errors
use the same sanitized validation summary/field-path policy; CLI I/O and encoding
errors are reported separately. The library opens no paths. The CLI opens only
its explicit input and never writes a project file, resolves declared locations
or loads runtime/plugin modules.

Shell redirection is outside the converter's ownership: redirecting stdout onto
the input can truncate it before Python starts. Display output or use a distinct
new candidate path and review before replacing source. This utility provides no
GUI semantic writer, project publication/backup, revision conflict handling,
watcher or immutable execution binding.

## Reusable declaration format (v2)

`ReusableWorkflowDefinition.schema_version = 2` and the unchanged
`WorkflowDefinition.schema_version = 1` version declaration formats, not execution
support. `AuthoredWorkflowDocument` explicitly unites `WorkflowDocument` and
`ReusableWorkflowDocument`. Revalidation dispatches on the validated variant;
no reusable value is coerced through the v1 model. Both formats share graph and
layout validation, and inspection always reports `execution_ready=False`.

`ReusableTaskReferences` declares manifest and data_root without a workspace.
A reusable external is either the unchanged literal `ExternalBinding` or a
`ManagedCandidateBinding(id, contract, kind="managed_candidate")`. Managed
contracts are proposal.input, storage or native-training.settings and have no location. Graph validity
still permits unused externals and repeated capabilities; the shared pure
`candidate.candidate_nodes` separately checks the supported three- or four-node candidate subset.

`ReusableWorkflowDocument` adds `preparation_options: CandidatePreparationOptions`.
proposal_advice, implementation_advice and validation_advice default to None;
allowed_output_types is None or a nonempty tuple of OutputTypeName from the small
`agent.schemas.output_types` owner. None retains native default ownership. Without training settings, no native payload schemas load at this boundary.
Training settings load the existing native validator lazily; task plugins,
providers and runtime constructors remain unexecuted. Its `declaration_digest()` includes canonical definition and
preparation options and excludes positions. Exact source bytes/comments are not
captured as identity here. v1 digest and canonical rendering are unchanged.

The restricted source bridge and offline conversion CLI accept both formats.
Canonical structured editing preserves values and tuple ordering, not comments
or formatting. The reusable example is
`examples/workflow_declarations/reusable_candidate.py`. Its explicit optional
literal and distinct managed storage aliases are declaration choices, not
prepared payloads. Pure resolution is owned by
`tools.candidate_prepare.resolution`. Managed-only reusable preparation is implemented
by `prepare_reusable_candidate` / `--reusable-request`; retained selection and
`build_reusable_operation` launch through the existing operation owner. Authored
v2 snapshots resolve to generated v1 worker inputs without coercing the authored
model. The console's `ReusableCandidate` consumes already prepared captures under
explicit configured project/task policy. Existing v1 preview and `EditedCandidate`
remain v1-only. The console prepares saved reusable source, including declared
training; unsaved edits cannot run. Resume is not implemented. See the [preparation contract](../../tools/candidate_prepare/candidate-prepare-contract.md)
and [console contract](../../tools/candidate_console/console-contract.md#reusable-capture-consumption).

## Source-owned reusable native training

Version 2 also admits the existing four-stage candidate graph when the document
supplies sparse `training_settings` and exactly one managed
`native-training.settings` external. Tuning consumes the same proposal and
validation results through `validated-candidate-to-tuning`. Old declarations
remain three-stage and retain their canonical bytes and semantic identities.

Only `training_settings` accepts JSON-shaped dict/list literals. Keys must be
literal unique strings; expansion, comprehensions, computed expressions,
nonfinite numbers and executable constructors inside settings are refused before
model construction. The native settings parser validates supplied controls,
including the prohibition on explicit `require_probe_runner=False`. Omission,
explicit null and supplied values remain distinct recursively. Frozen document
objects do not freeze nested mappings; consumers revalidate at each boundary.

The authored mapping does not acquire native defaults. Preparation reconciles
its output restriction, inserting only `launch.allowed_output_types` when absent
(including explicit null), and refuses conflicts. External `health_checks_config`
is unsupported in reusable capture; task-composed Health and existing inline
startup controls remain available. Native v1 external Health support is unchanged.
Source validation does not load selected task plugins, bind runtime verifiers or
discover hardware; importing native schemas can import torch.

## Optional accepted task binding (declaration only)

Reusable v2 documents may carry `task_binding: TaskBinding`. Its version is
`siderius.task-binding/v1`; `package_id` and `revision` are explicit readable
metadata, while `task_data_path_id` and `semantic_fingerprint` record the accepted
native composition identity. These constructors compute no identity, resolve no
package/version and import no task. Composition remains the single fingerprint
owner; this is its assembly-bound identity, not a new universal package hash.
Manifest/data locations remain separate declared references.

Absent/None binding is omitted from serialization and source, including its
constructor import, preserving existing v1/v2 canonical bytes and digests. A
present binding participates in the existing document declaration digest. v1
cannot carry this field and is never silently migrated. Old source stays unbound;
no readable version is inferred from a path, timestamp or identity-format label.

Bound source is readable/convertible. Reusable preparation retains its pin and
independently enforces both accepted native identity fields before payload
publication through the
[preparation owner](../../tools/candidate_prepare/candidate-prepare-contract.md#accepted-task-binding-enforcement).
Authoring supports explicitly reviewed current-snapshot adoption and guarded
publication while native identity remains unchanged, through its
[publication owner](../../tools/workflow_authoring/authoring-contract.md#bound-source-publication-boundary).
Pin removal and unresolved changed-task migration remain refused. Guarded
publication alone does not establish successful preparation or launch. Existing unbound
paths and previously captured runs retain their original contracts.

## Reusable execution profile

`ReusableWorkflowDocument.execution_profile` optionally selects
`"native-proposal-fanout/v1"`. None is omitted from JSON and canonical source, so
old source bytes and semantic identities remain unchanged. An explicit profile is
source-owned and participates in the document digest; task-only identity adoption
cannot change it. No profile is inferred from repeated nodes. Graph execution
refuses `training_settings` and uses the existing fanout topology admission during
[reusable preparation](../../tools/candidate_prepare/candidate-prepare-contract.md#reusable-proposal-fanout).
Generated v1 source remains a declaration; its accompanying parent-verified worker
request carries the execution profile.


## Native literature edge

The inert catalog includes `literature.input`, `literature.output`, the `literature`
capability and `literature-to-proposal`. The latter maps a selected review `output`
and external `proposal_input` through the existing target-owned
`local_typed_evidence` protocol. Since B6-4 it also includes the contract
`literature.collection` (`list[NamedLiteratureReviewOutput]`, the existing
`ml_literature_review_to_ml_model_propose` model: `contribution_id` plus one complete
`LiteratureReviewOutput`) and the protocol `literature-collection-to-proposal`
(`reviews: literature.collection`, `proposal_input: proposal.input` → `proposal.input`,
owner `local_typed_evidence_many`, whose `Sequence` parameter accepts the catalogued
list; the signature test records that one widening). Only a `collect/v1` adaptor
output reaches it at run time: no profile admits a `literature.collection` external, and the S2 profile is its only executor. Structural validity alone grants no execution.
The native worker admits exactly one review and one complete candidate only under
[its explicit literature profile](../../tools/candidate_worker/candidate-worker-contract.md#opt-in-native-literature-candidate).
The reusable preparation route below uses the same native profile. Existing source
editing supports its declaration; dedicated visual creation controls are not added.

Reusable v2 sources can opt into that same four-node literature profile. Its
managed `literature.input` binding requires sparse `literature_settings`; the
source parser accepts only inert JSON, and preparation validates existing native
types. The field is absent for old bindings, preserving old canonical source and
declaration identity. Settings participate in external-binding identity and cannot
be changed by a task-reference-only update. See the
[preparation contract](../../tools/candidate_prepare/candidate-prepare-contract.md#reusable-native-literature-candidate)
for the exact controls, child-composition trust boundary and resource restrictions.
