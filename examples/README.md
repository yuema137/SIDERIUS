# Framework examples

SIDERIUS ships two lightweight synthetic examples:

- [`quickstart/`](quickstart/README.md) demonstrates a caller-owned task
  composition without introducing a scientific default.
- [`synthetic_masked_regression/`](synthetic_masked_regression/README.md)
  demonstrates masked continuous supervision, a lower-is-better primary metric,
  an observational secondary metric and task-owned Health.

These packages are executable framework specifications. Their offline checks
are small, CPU-friendly and credential-free, and make no scientific-performance
claim. Separately recorded real-resource receipts retain their original scope
and revision. Real datasets, task packages, campaign workflows, and result evidence
belong in external consumer repositories.

Production framework modules do not import from `examples/`. A run consumes an
example through the same public composition contract available to an external
task.

For current contract coverage, see
[supported task shapes](../docs/concepts/supported-tasks.md). For the manifest
surface, see the [task composition reference](../docs/reference/task-composition.md).
For current source ownership and external task locations, see the
[repository map](../docs/repository-map.md).
