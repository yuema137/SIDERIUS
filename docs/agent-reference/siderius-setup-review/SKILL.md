---
name: siderius-setup-review
description: Help a user prepare and optionally review an external SIDERIUS task and experiment, inspect resolved settings, and use the supported standard single-iteration launch. Use when setup assistance or review is requested; this is not a mandatory gate or an arbitrary-workflow reviewer.
---

# SIDERIUS setup review

Use the [human setup guide](../../../src/tools/setup_review/README.md) to explain
the route and the [command reference](../../../src/tools/setup_review/usage.md)
for exact commands. Read the relevant linked contract when a report or refusal
needs investigation. The source and validated schemas own runtime behavior;
this skill adds guidance, not another configuration authority.

## Establish the user's intended run

- Reuse the user's already stated task, data location/split, provider/model,
  hardware and budget choices. Ask only for consequential missing decisions.
  Do not substitute a documentation example for a model or spend limit the user
  selected. Do not infer the authorized duration from a training budget.
- Keep task meaning separate from experiment settings. Build and edit files in
  an external project; leave repository templates and archived runs untouched.
  Name the task manifest, data directory, LLM config, optional advice, launch
  request and new result workspace explicitly.
- Use the selected installation's own Python environment and declared plugins.
  Historical paper policies must be selected from exp; do not recreate them as
  framework defaults or silently install a historical fallback.

## Offer the appropriate route

Direct standard launch remains valid without this skill or a review receipt.
When the user wants the optional reviewed route, prepare a fresh standard
single-iteration request and follow this sequence:

1. Inspect declarations and resolve the trusted task/providers using the task
   check with `--resolve-task-settings`. Preserve failures and fix their actual
   cause. Do not remove the application's sandbox to make a check pass.
2. Inspect the intended execution environment with `--bind-launch`. Explain
   resolved defaults, conditional/unknown values and remaining checks. Hardware
   discovery, key presence and a parsed configuration do not prove a real run
   will succeed. If the agent's tool context restricts hardware or namespaces,
   identify that distinction before calling it a task or host failure.
3. Let the user select LLM review or an explicit skip, honoring existing session
   choices. An unperformed review is not a skip receipt. Send only the authorized
   saved review packet to the selected provider; do not send data or secrets.
4. Save the [reviewed launch request](../../../src/tools/setup_review/reviewed-launch.md#request-recipe)
   with exact report/receipt hashes and necessary finding dispositions. Show the
   user the actual settings and the command, working directory and interpreter
   that will execute them. An acknowledgement cannot override changed inputs.
5. Launch only within the user's authorization for real API/GPU work. Reading
   this skill grants no budget or external-action permission. Use fresh reports
   and, when necessary, a fresh run workspace after a bound input changes.

For [external orchestration](../../../src/tools/orchestration_setup/README.md),
help prepare the documented agent instructions, explicit caller and sandbox.
The standard reviewed-launch gate does not review arbitrary caller control flow;
do not silently replace the user's orchestration with a fixed workflow.

## Report what actually happened

Distinguish declaration inspection, task composition, environment discovery,
LLM review/skip, launch authorization and successful scientific execution.
Inspect the run's manifest, records and actual result files; a zero process exit
or matched launch check alone is insufficient. Report failed/no-record runs as
such, without changing scientific checks just to obtain a successful status.

Give the user exact paths for saved task/experiment files, the launch command,
run status and results. Explain one requested parameter change and which files
and reports must be saved again. Keep README prose concise and link detailed
schema/identity/error contracts instead of copying them into the human entry.
