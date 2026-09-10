# Supported task shapes and current maturity

SIDERIUS is contract-driven rather than dataset-driven. Framework source does
not maintain a roster of scientific datasets and does not select behavior from
a task name. A task is supportable when it can provide the required public
contracts and plugins.

## Required shape

A composed task supplies:

- a `TaskDataPath` implementation for data access;
- a `DatasetProfile` carrying generic identity plus opaque task topology;
- a training objective and model I/O contract;
- one primary metric with an explicit direction and executable scoreability
  contract;
- a deliverable declaration;
- an explicit Health declaration or explicit absence.

Optional contracts add secondary metrics, custom scope construction, model or
loss plugins, parameter rules, literature-review inputs, and task-owned Health
checks. Unsupported declarations fail at composition instead of selecting a
scientific fallback.

## Demonstrated framework contracts

The framework-owned example and synthetic tests collectively demonstrate:

| contract shape | evidence owner |
|---|---|
| classification and higher-is-better ordering | Quickstart |
| continuous regression and lower-is-better ordering | synthetic masked regression |
| task-owned objective and semantic target validation | synthetic masked regression |
| declared scoreability before metric arithmetic | generic metric tests |
| task-owned Health plugins and explicit Health absence | synthetic contracts and Quickstart |
| task-owned split/scope construction with non-overlap | Quickstart and synthetic scope tests |
| bounded training, inference, scoring, admission, persistence, and resume | minimal-example qualification matrix |
| external file plugins with content identity and child-process transport | composition contract tests |

These are framework capability claims, not scientific benchmark claims.

## Real scientific tasks

Real task packages and campaigns are external consumers. Their data,
scientific thresholds, task plugins, workflows, budgets, results, and
qualification receipts are intentionally not distributed with SIDERIUS.
Their evidence may demonstrate that the public contracts work on additional
modalities, but it does not make those tasks framework defaults.

## Next

- [What a task must provide](task-package.md)
- [Define your own task](../guides/define-a-task.md)
- [Task composition reference](../reference/task-composition.md)
- [Quickstart example](../../examples/quickstart/README.md)
