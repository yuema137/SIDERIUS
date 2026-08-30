# Synthetic masked regression

A CPU-only, offline framework example for contract shapes the classification
quickstart does not cover: continuous regression, a lower-is-better primary
metric, an observational secondary metric, and a semantic supervision target
whose second value is an explicit validity mask.

This pack is demonstration infrastructure, not a scientific task or benchmark.
Its deterministic generator creates three disjoint 24-row shards. Shards 0–1
train; shard 2 evaluates. The model emits `[B, 1]`, while the custom objective
requires `[B, 2]` supervision containing `[truth, validity_mask]`. Invalid rows
remain observable in the artifact but never enter either metric.

Governance and scope are owned by
`docs/design/siderius_generic_framework_upgrade.md` §22.23 and the Phase-C
coverage matrix in `docs/design/framework_experiment_repository_separation.md`.

The pack covers composition, exact materialization, custom-loss semantics,
prediction-aligned source transport, persistence, primary plus secondary
scoring, record-level primary-only selection under a deliberately conflicting
secondary, task-owned Health over valid predictions, and deterministic
traversal of the production five-node workflow. The workflow test substitutes
typed offline agent responses and exercises literature-review ON/OFF topology;
it does not claim live LLM execution or network retrieval. ON requires an
explicit task-owned config and carries the advisor output into the proposer;
OFF does not open the configured path or call the advisor. The production
training engine also completes one bounded CPU optimizer step using the real
``[truth, validity_mask]`` target and custom loss. The pack also proves checkout-independent composition identity, compatible workspace
resume after relocation, refusal after a declared plugin edit, and standalone
typed invocation of the interpretation node. Its resource witness materializes
one full task-valid training batch through the isolated worker's
production boundary; it does not claim a physical GPU measurement on CI.

A separate bounded TestPod qualification ran the production isolated
preflight on an H100 80GB at repository SHA `1acfe3bb`. The fixed candidate
measured `0.229 GB`: a `1.0 GB` operator cap admitted it, while a `0.001 GB`
cap produced `MEASURED_PEAK_ABOVE_VRAM_CAP`. The compact receipt is
`expected/h100_resource_qualification.json`; this GPU evidence remains
separate from ordinary CPU/offline CI.
