# Technical references

Use this directory after the human documentation route has shown you which
part of SIDERIUS you need to understand. These pages are detailed contributor
references: they describe schemas, protocols, invariants, and failure
behavior, while repository and package READMEs remain short landing pages.

Start with the [reference index](index.md) when you already know the change
you need to make. It routes you to the smallest set of current mechanism,
module, and node contract documents. For a first visit, begin with the
[documentation map](../README.md), [installation](../getting-started/installation.md),
or [first run](../getting-started/first-run.md).

The [mechanism index](mechanisms/README.md) is useful when a rule crosses
several packages. Node-specific behavior belongs in the adjacent
`src/nodes/<node>/<node>.md` contract, linked from the [source node map](../../src/nodes/README.md).

The source and its tests are authoritative. Design pages record history and
rationale; they do not promise that an unlanded design is current behavior.
