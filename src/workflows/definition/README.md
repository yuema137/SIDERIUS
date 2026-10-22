# Workflow declarations

This package describes a small workflow in Python or JSON and checks whether
its connections use supported native contracts. It is a foundation for a future
editor, **not a workflow runner**. Existing launch commands remain unchanged.

The supported sequence is proposal → implementation → validation. Each node
accepts a complete request, either from an external file reference or through
one of the two native protocols. A protocol declares its arguments explicitly;
for example, implementation needs both a proposal result and a storage reference.
Several nodes may reuse a result, but generating multiple candidates, merging
results, feedback loops and human gates are not supported here yet.

Use `WorkflowDocument.model_validate_json(text)` to read a declaration and
`document.model_dump_json(indent=2)` to save it. Python construction uses the same
models and checks. Canvas positions are separate from the workflow definition.

A successful check means the **declared bindings use supported contracts within this
subset**. It does not open the referenced files, validate their contents or set
up agents. `inspect_declaration(document)` lists those remaining checks. Do not
pass this document to an existing launcher or treat its digest as a run identity.

See the [contract and Python example](definition-contract.md) for the supported
bindings, ownership and validation rules.

For one connected three-node chain, the optional
[binding preview](../../tools/workflow_preview/README.md) reads selected local
files and reports constructor model routes. It still does not execute the chain
or validate native payload contents.
