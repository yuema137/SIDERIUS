# .github/workflows

`ci.yml` is the automatic PR/master workflow and declares a `workflow_dispatch`
entry for exceptional operator use. Normal evidence comes from automatic PR CI;
selection and sharding are delegated to existing tools. This directory contains
no credential recipe.

Validation/use route: [`src/tools/ci_selection/`](../../src/tools/ci_selection/README.md)
owns affected-test selection; [`src/tools/ci/`](../../src/tools/ci/README.md)
owns execution and sharding. This guide is navigation, not a second contract.
