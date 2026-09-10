# Framework examples

SIDERIUS ships one lightweight synthetic example:

- [`quickstart/`](quickstart/README.md) demonstrates a caller-owned task
  composition without introducing a scientific default.

The example is an executable framework specification. It is intentionally
small, CPU-friendly, credential-free, and makes no scientific-performance
claim. Real datasets, task packages, campaign workflows, and result evidence
belong in external consumer repositories.

Production framework modules do not import from `examples/`. A run consumes an
example through the same public composition contract available to an external
task.

For current contract coverage, see
[supported task shapes](../docs/concepts/supported-tasks.md). For the manifest
surface, see the [task composition reference](../docs/reference/task-composition.md).
