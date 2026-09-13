# Modular variant

This is a packaging example of [synthetic masked regression](../README.md),
not another scientific task or benchmark. [composition.yaml](composition.yaml)
reuses the original implementation files unchanged and declares every Python
member it imports. The original single-file manifest remains supported.

The four modular helpers live beside the original plugins as
`../plugins/_modular_*.py`. Their leading underscores keep them out of ordinary
model/loss directory scans; the modular manifest selects them explicitly.
This directory contains only the variant's manifests and documentation.

The data path creates `MaskedScope` objects. The metric imports that same class
through a relative helper and checks its identity before calling the unchanged
masked-MSE arithmetic. A per-entry module namespace would break this check.
The example also loads the model, objective/loss, Health check/view, static
parameter-count observable and file-presence scoreability through local entries.
The static diagnostic does not affect the primary metric or model selection.

Use this manifest wherever a command accepts `--task_composition`:

```text
examples/synthetic_masked_regression/modular/composition.yaml
```

Generate data under an explicit writable workspace using the parent example's
instructions. Data, YAML/JSON declarations, descriptions and outputs are not
Python members. Do not put generated data or run artifacts in this code tree.

`code_package.root` is relative to the manifest; each listed Python member is
relative to that root. Relative imports can access only listed members; normal
installed dependencies still use ordinary imports. Do not add the example or
its parent to `PYTHONPATH`.

Changing any listed file changes the whole package identity. A running parent
uses its captured bytes; a new child verifies the whole declared set before
execution and refuses changed/missing members. Start a new composition/run after
an intentional edit; do not rewrite a captured transport artifact to resume.
This mechanism provides reproducible loading, not a security sandbox for Python.

Focused tests prove composition, shared scope identity, family loading and cold
child integrity. They do not claim new real-training or scientific qualification.
