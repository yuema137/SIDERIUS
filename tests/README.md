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

## Optional external resources

The shared fixtures behind `--real-data` and `--real-training` read their
resource root only from the absolute path in `SIDERIUS_TEST_DATA_DIR`.
Leaving the variable unset visibly skips that optional lane. Setting it to a
blank, missing, non-directory, or incomplete resource is a qualification
failure; it never falls back to a developer path or becomes a green skip.

For example:

```bash
SIDERIUS_TEST_DATA_DIR=/absolute/path/to/test-data \
  .venv/bin/python -m pytest <selected-test> --real-data -q
```

The shared historical real-data fixture still expects its named external file.
Direct historical workload owners have not yet been routed through this seam;
their migration or retirement is the next bounded portability slice. This
resource contract does not make a real scientific task a framework default.
