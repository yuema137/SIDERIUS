# tests

This tree records framework evidence: deterministic unit contracts, opt-in
integration seams, shared fixtures/helpers, and bounded manual diagnostics. The
[unit map](unit/README.md) is the normal source-change starting point; use the
[integration map](integration/README.md) for cross-process or provider seams.

See [fixtures](fixtures/README.md), [helpers](helpers/README.md),
[manual](manual/README.md), and preserved [pseudo-data](pseudo_data/README.md)
for ownership and invocation boundaries.

Each family map identifies the production owner, the defect its tests catch,
and a focused command. Integration defaults are synthetic or recording; real
LLM/training paths require explicit markers/options. No map implies a
full-suite, live-provider, GPU, or scientific-result claim.

## External effects

Framework tests do not provide a shared real-dataset or real-training mode.
Real scientific data, task-owned executors, GPUs and full workflow evidence
belong to each external task package. The shared `--real-llm` option selects
only real provider calls; it never selects data or subprocess training.
