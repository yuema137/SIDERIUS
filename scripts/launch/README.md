# `scripts/launch/`

Maintained chain launcher, shared argument construction, source-authority
probe, and auto-resume inspection. Use an explicit checkout and its own
`.venv`. The launcher verifies that its Python environment imports that checkout
before inspecting run state or starting an iteration.

For an optional fresh foreground chain whose selected settings are checked
again at launch and before every iteration, use the
[native capture walkthrough](../../src/tools/native_chain/README.md).
Ordinary chain execution and automatic resume keep their existing behavior.

For a task using a weighted evaluation formula, enabled formal score gates need
`--score_units_metric <effective metric id>` so their margins have explicit utility
units. Obtain that id from the composed evaluation's inspection output. Leaving
the gates disabled needs no new flag. See the
[evaluation contract](../../src/execute_tools/evaluation-contract.md#deterministic-selection-runtime)
for the supported scoring route and threshold rules.
