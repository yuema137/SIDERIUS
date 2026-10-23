# Workflow declaration contract

## Scope and owners

Version 1 is an offline, within-iteration declaration format. It describes
proposal, implementation and validation capabilities; it does not instantiate
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

There are no custom/generation/aggregation adapter, feedback, arbitrary-code, constructor configuration or
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
`ReusableWorkflowDocument`. Imported unused constructors are allowed; referenced
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
contracts are proposal.input or storage and have no location. Graph validity
still permits unused externals and repeated capabilities; the shared pure
`candidate.candidate_nodes` separately checks the supported three-node subset.

`ReusableWorkflowDocument` adds `preparation_options: CandidatePreparationOptions`.
proposal_advice, implementation_advice and validation_advice default to None;
allowed_output_types is None or a nonempty tuple of OutputTypeName from the small
`agent.schemas.output_types` owner. None retains native default ownership. No
native payload schemas, task plugins, providers or runtime constructors load at
this boundary. Its `declaration_digest()` includes canonical definition and
preparation options and excludes positions. Exact source bytes/comments are not
captured as identity here. v1 digest and canonical rendering are unchanged.

The restricted source bridge and offline conversion CLI accept both formats.
Canonical structured editing preserves values and tuple ordering, not comments
or formatting. The reusable example is
`examples/workflow_declarations/reusable_candidate.py`. Its explicit optional
literal and distinct managed storage aliases are declaration choices, not
prepared payloads. Pure resolution is owned by
`tools.candidate_prepare.resolution`; reusable preparation and launch are not
implemented. Existing v1 preview/launch requests remain v1-only and the editor's
launch review explicitly refuses reusable declarations.
