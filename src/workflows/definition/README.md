# Workflow declarations

Describe a supported workflow in a dedicated Python file, check its declared
connections, and export JSON or canonical Python source. The supported chain is
proposal → implementation → validation. Each node takes a complete external
request or an explicitly bound native protocol request.

For a Python-authored project, the Python declaration is authoritative; JSON is
an export. Existing JSON callers can keep their explicit JSON input. Conversion
does not change how launchers select their inputs or make a declaration runnable.

## Convert a declaration

Create a dedicated file such as `/path/to/project/workflow.py`:

```python
from workflows.definition import (
    ExternalBinding, ExternalRequest, NodeInstance, TaskReferences,
    WorkflowDefinition, WorkflowDocument,
)

document = WorkflowDocument(
    definition=WorkflowDefinition(
        task=TaskReferences(
            manifest="task/manifest.json",
            data_root="data",
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
```

From an installed SIDERIUS checkout, display its document JSON:

```bash
.venv/bin/python -m workflows.definition to-json --input /path/to/project/workflow.py
```

To keep an export and inspect proposed canonical source, choose distinct new
candidate paths:

```bash
.venv/bin/python -m workflows.definition to-json \
    --input /path/to/project/workflow.py > /path/to/project/workflow.export.json
.venv/bin/python -m workflows.definition to-python \
    --input /path/to/project/workflow.export.json > /path/to/project/workflow.candidate.py
```

Review the candidate before replacing your declaration. Canonical output preserves
declared settings, connections and layout. It discards original comments,
docstrings and formatting. **Never redirect output onto the input file:** the shell truncates
that file before the converter starts. The CLI reads only its explicit input
and writes completed content to stdout; it offers no in-place or output-path
option.

The parser accepts the constructor-only module shape above, plus optional initial
docstring/comments and nested supported constructors with literal values and
tuples. It refuses dynamic scripts, extra statements, foreign imports, computed
values and unsupported syntax. Input must be UTF-8 and at most 1 MiB. A conversion
failure exits 2, prints a concise diagnostic to stderr and emits no converted
content to stdout.

## What validation establishes

A successful conversion establishes that declared connections use supported
contracts. Locations remain literal strings: conversion does not open task,
data, payload or plugin paths, validate their contents, import selected source
or start agents. Relative locations retain their declared spelling.
`inspect_declaration(document)` lists the remaining runtime checks.

The Python API provides `parse_workflow_source(text)` and
`render_workflow_source(document)`. For direct JSON construction, use
`WorkflowDocument.model_validate_json(text)` and
`document.model_dump_json(indent=2)`. Both use the same existing models.

The [declaration contract](definition-contract.md) defines the full grammar,
diagnostics, limits, supported bindings and ownership. Multiple consumers can
reuse a result; generation of multiple candidates, aggregation, feedback loops
and human gates need later runtime support.

For one connected three-node chain, the optional
[binding preview](../../tools/workflow_preview/README.md) reads selected local
files and reports constructor model routes. It still does not execute the chain
or validate native payload contents.
