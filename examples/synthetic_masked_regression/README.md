# Synthetic masked regression

This CPU-only example is a small, offline tutorial for a task with continuous
outputs, a lower-is-better metric, an observational secondary metric, validity
masks, and task-owned Health checks. It demonstrates framework contracts; it
is not a scientific task, benchmark, or quality claim.

It follows the example-pack governance in
[`siderius_generic_framework_upgrade.md`](../../docs/design/siderius_generic_framework_upgrade.md)
§22.23; that design record explains why examples demonstrate contracts without
becoming scientific defaults.

## Try it

From the repository root, follow the [example test](../../tests/unit/examples/)
or inspect the shipped declarations in [`declared/`](declared/README.md) and
plugins in [`plugins/`](plugins/README.md). The pack generates three disjoint
24-row shards from a pinned seed, trains on shards 0–1, and evaluates shard 2.
Generated data belongs in a caller workspace and is not committed.

The modular variant shows the same task through explicit composition:
[`modular/composition.yaml`](modular/composition.yaml). Use the repository
[first-run guide](../../docs/getting-started/first-run.md) for launch and
workspace safety.

## What to read next

- [Current status](STATUS.md) — landed deterministic coverage and explicit limits.
- [Provenance](PROVENANCE.md) — dated resource qualification and retained receipts.
- [Task declarations](declared/README.md) — data, metrics, objective, and Health.
- [Plugin declarations](plugins/README.md) — task-owned execution seams.

The example's workflow tests use typed offline agent responses. Live provider
calls, network literature retrieval, and physical GPU claims are outside this
pack's ordinary run.
