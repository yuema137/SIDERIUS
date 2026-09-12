# tests

This tree records framework evidence: deterministic unit contracts, opt-in
integration seams, shared fixtures/helpers, and manual hardware probes. The
[unit map](unit/README.md) is the normal source-change starting point; use the
[integration map](integration/README.md) for cross-process or provider seams.

See [fixtures](fixtures/README.md), [helpers](helpers/README.md),
[manual](manual/README.md), and preserved [pseudo-data](pseudo_data/README.md)
for ownership and invocation boundaries.

Each family map identifies the production owner, the defect its tests catch,
and a focused command. Integration defaults are synthetic or recording; real
LLM/training paths require explicit markers/options. No map implies a
full-suite, live-provider, GPU, or scientific-result claim.
