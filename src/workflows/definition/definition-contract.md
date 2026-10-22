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
