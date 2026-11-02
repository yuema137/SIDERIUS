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

Health checks measure variation among predictions for valid evaluation rows.
Before each Health-enabled trial or formal attempt, the example checks that
the selected scope contains at least two valid rows and only evaluation-shard
rows. Fewer than two valid predictions cannot meet the positive variation
threshold, so those selections are refused before execution. A scope
that passes this coverage check can still fail the prediction-variation check.

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

## Repeating a sampled run

The generated dataset stays fixed. To repeat the random row selections in a
run, use the same `--run_seed`; the framework supplies the scope and epoch
sampling seeds. Direct plugin callers must supply `ScopeBuildRequest.seed`
and `EpochSamplingParams.epoch_seed` when sampling, or receive `MissingRunSeed`.
Selecting all rows or applying a prefix ceiling needs no seed.

Updating a plugin changes the composition fingerprint that identifies the
run's configuration and code. Start a new workspace after updating this pack;
a workspace pinned to the previous plugin cannot resume with the new one.
