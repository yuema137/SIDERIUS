---
name: siderius-setup-review
description: Guide SIDERIUS setup from a short problem description and data location through an external task package, experiment and launch instructions. Use when a user wants to try a new task or review an existing setup; configuration review is optional and arbitrary workflow control flow is not automatically reviewed.
---

# SIDERIUS setup review

Use the [human setup guide](../../../src/tools/setup_review/README.md) to explain
the route and the [command reference](../../../src/tools/setup_review/usage.md)
for exact commands. Read the relevant linked contract when a report or refusal
needs investigation. The source and validated schemas own runtime behavior;
this skill adds guidance, not another configuration authority.

## Start from the user's problem, not a prepared manifest

A brief such as "I have MNIST images and labels in /data/mnist; help me build and
evaluate a digit classifier" is enough to begin. Do not require the user to name
this skill, supply configuration files or understand the repository architecture.
Own the preparation work and guide the decisions using the current source and
references below. A described task is not authorization for unbounded API/GPU work.

1. Inspect available local data metadata and the selected installation. Follow
   [installation](../../getting-started/installation.md) for the checkout's own
   environment and explain missing dependencies, supported hardware and required
   credential names. Reuse existing data; never print key values or put them in
   generated files. Distinguish a tool sandbox restriction from a missing host
   capability. Do not claim setup succeeded without actually checking it.
2. Resolve consequential scientific choices with the user: inputs and targets,
   leakage-safe split unit, workflow validation versus held-out final test, metric
   and any task-specific validity rules. Propose concrete choices with reasons;
   reuse choices already given instead of making the user answer them again.
3. Author or adapt the [task package](../../reference/task-composition.md) in a
   new external project. Inspect an existing task before reusing it; a similarly
   named dataset does not guarantee matching labels, splits or objectives.
   Implement its required adapters through the published contracts. Explain the
   resulting scientific choices without asking the user to handwrite schemas.
4. Prepare the experiment separately: model routing, workflow, data exposure,
   iterations, budgets and output workspace. Recommend the
   [Luna test profile](../../../configs/llm/README.md) for an initial process check,
   while honoring an explicitly chosen model. Keep keys external. Save a launch
   script and settings in the project; do not reimplement framework training.
5. Run the applicable [offline checks and command preview](../../getting-started/first-run.md)
   in the selected environment, resolve actual failures, and give the user the
   saved task/experiment paths, important effective settings, exact command and
   result locations. Offer the optional review route below. Continue to a real
   run only within the user's existing execution and spending authorization.

If data, tools or access are unavailable, state the specific missing prerequisite
and continue independent preparation. Do not present a plan or unexecuted command
as a completed setup. Manual authoring remains available for users who prefer it.

## Preserve the user's intended run

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
