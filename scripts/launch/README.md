# `scripts/launch/`

Maintained chain launcher, shared argument construction, source-authority
probe, and auto-resume inspection. Use an explicit checkout and its own
`.venv`. The launcher verifies that its Python environment imports that checkout
before inspecting run state or starting an iteration.

Every `run_chain.sh` flag, its default and its failure behavior are documented in
the [entrypoints reference](../../docs/reference/entrypoints.md#run_chainsh--the-chain-launcher).

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

## CPU pseudo smoke runs

Use `--is_pseudo_llm --is_pseudo_training` to exercise the chain with canned
LLM and execution results. No API key, GPU or memory-limit setup is needed.
Add both flags to your normal task launch command.

The execution stub starts no subprocess, so pseudo admission records that no
execution envelope is needed. If you set `SIDERIUS_SUBPROCESS_RSS_GB`, its value
is validated and recorded, but it limits nothing in the stub. A malformed value
stops launch with `LAUNCH REFUSED` and exit code 2.

Pseudo admission does not establish that a real model fits on CPU or GPU.
Task validation and Health checks still run, so a pseudo chain can fail later
if its canned outputs lack required evidence.
