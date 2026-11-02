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

## CPU pseudo smoke runs

Use `--is_pseudo_llm --is_pseudo_training` to exercise the chain with canned
LLM and execution results. Declare positive address-space limits for all three
execution roles through `SIDERIUS_SUBPROCESS_RSS_GB` before launch. For example,
`SIDERIUS_SUBPROCESS_RSS_GB=16 bash scripts/launch/run_chain.sh --mode lilab ...
--is_pseudo_llm --is_pseudo_training` declares 16 GiB for each role; replace
`...` with your workspace, run name, task composition and data-directory flags.
Choose the limits explicitly for your run; 16 GiB is an example, not a default.

Pseudo admission records that declaration without probing a GPU or estimating
candidate memory. Missing or zero limits stop launch with
`PSEUDO_ENVELOPE_REQUIRED`. A positive declaration admits only synthetic
execution: it does not establish that a real model fits on CPU or GPU, and it
does not cap the chain parent's memory. Task validation and Health checks still
run, so a pseudo chain can fail later if its canned outputs lack required evidence.
