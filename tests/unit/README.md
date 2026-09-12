# tests/unit

Unit-suite index for deterministic regressions; CI selection may expand from affected files, while local guidance stays focused.

## Child routes

Start with [agent](agent/README.md), [core](core/README.md),
[execute_tools](execute_tools/README.md), [nodes](nodes/README.md), or
[tools](tools/README.md); each child names its source owner and focused route.
CI may widen selection for shared dependencies.

Other maintained families: [dashboard](dashboard/README.md),
[docs](docs/README.md), [examples](examples/README.md),
[guardrails](guardrails/README.md), [ml_models](ml_models/README.md),
[packaging](packaging/README.md), [scripts](scripts/README.md),
[sdsc_submission_scripts](sdsc_submission_scripts/README.md), and
[workflows](workflows/README.md). Agent subfamilies are indexed by the
[agent map](agent/README.md).

The [agent_generated](agent_generated/README.md) family is a historical
registry/index-write regression suite owned by `core.capability_registry`,
not a production package.

`test_repo_hygiene.py` owns repository-level checks; a focused run is not a
full-suite result.
