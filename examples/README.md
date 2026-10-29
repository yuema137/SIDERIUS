# Framework examples

SIDERIUS ships two lightweight synthetic examples:

- [`quickstart/`](quickstart/README.md) demonstrates a caller-owned task
  composition without introducing a scientific default.
- [`synthetic_masked_regression/`](synthetic_masked_regression/README.md)
  demonstrates masked continuous supervision, a lower-is-better primary metric,
  an observational secondary metric and task-owned Health.
  Its [modular variant](synthetic_masked_regression/modular/README.md) demonstrates
  explicit local-package members and shared helper-class identity while reusing
  the same synthetic implementation files.

[`task_templates/csv_classification/`](task_templates/csv_classification/README.md)
is a task package to copy for your own tabular classification data in CSV
files: it reads real files from the data folder and declares a main score,
Health checks and a locked parameter, with each line to change marked.

[`console_bundle/`](console_bundle/README.md) holds the sources of the quickstart
example bundle, a release zip that packages the quickstart task with a ready
experiment setup for the browser console; it is built from `quickstart/`, not a
separate pack.

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
