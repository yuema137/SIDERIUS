# Review your setup before starting a run

Use this **optional** tool to see which task, model routes, data settings and
budgets a standard SIDERIUS run will use. It writes an offline HTML page for
human review, including defaults you did not explicitly set. It can also ask an
LLM to review the saved configuration, or record your decision to skip that step.

The tool supports a **new workspace and one standard workflow iteration**.
It does not review arbitrary Python orchestration, an entire multi-iteration
chain, or a resumed run. Those routes remain available through their own launchers.

## Choose direct or reviewed launch

| Route | What you do | What happens before execution |
| --- | --- | --- |
| Direct | Prepare your task and experiment, then use the ordinary launch command. | Normal framework validation applies; this optional review is not required. |
| Reviewed | Save a request, check the task and environment, review or explicitly skip, then use the reviewed launcher. | The launcher compares the saved setup with current selected inputs and checks how review findings were handled. |

Professional users can prepare either route themselves. Assistant users can ask
their agent to read the optional
[setup-review skill](../../../docs/agent-reference/siderius-setup-review/SKILL.md).
This is a repository instruction file; reading it does not require a global
skill installation or make review compulsory.
The choice of route does not change your scientific task or select a historical
paper strategy. Historical experiment settings belong to
[siderius-exp](https://github.com/yuema137/siderius-exp).

## Keep the files in your own project

First [install SIDERIUS](../../../docs/getting-started/installation.md) and prepare
your [task package](../../../docs/reference/task-composition.md), data and LLM
routing. This tool inspects those inputs; it does not generate them.

```text
your-project/
  tasks/my-task/task.yaml       task manifest and associated plugins
  llm/agents.json               provider/model settings, without keys
  review-request.json          arguments for the standard iteration
  task-check-001/              task check: report.json and index.html
  environment-preview-001/     hardware/settings: report.json and index.html
  semantic-review-001/         LLM review or explicit skip receipt
  reviewed-launch.json         selected reports, receipts and decisions
  runs/demo/                  generated models, records and results
```

Data may live elsewhere; declare its actual path. Keep API keys in the launching
environment or a trusted external credential file, outside both source repositories.
The run workspace must initially be absent or empty. Use a new report directory
each time you inspect changed settings; old reports are not overwritten.

## Save the settings you intend to run

Write `review-request.json` in your project. Replace the example project path
and input paths below. `argv` contains arguments, not a shell command.

```json
{
  "working_directory": "/home/alex/siderius-project",
  "argv": [
    "--workspace", "runs/demo",
    "--run_name", "demo",
    "--start_iteration", "1",
    "--task_composition", "tasks/my-task/task.yaml",
    "--data_dir", "data",
    "--llm_config", "llm/agents.json",
    "--max_rounds", "1",
    "--healthgate_mode", "blocking",
    "--result_authority", "diagnostic"
  ]
}
```

Here `max_rounds=1` means one tuning round inside the iteration. Other settings,
including retry limits and data fractions, still have their own meanings and
defaults. Inspect them in the report rather than assuming every limit is one.
The example's Health/result settings select a diagnostic run; choose settings
appropriate to your experiment.

For a quick declaration preview, run from the saved working directory:

```bash
cd /home/alex/siderius-project &&
/path/to/SIDERIUS/.venv/bin/python -m tools.setup_review \
  --request review-request.json \
  --output /home/alex/siderius-project/review-001
```

Open `review-001/index.html`. It shows your parsed arguments beside the CLI
defaults and an ordinary launch command. **This preview alone does not check
the task, dataset, hardware or provider authentication.**

## Follow the reviewed route

Use the [complete command sequence](usage.md) for the following steps. Each
command uses the same project directory and the exact installation's Python.

| Step | What it checks or records | What you inspect next |
| --- | --- | --- |
| 1. Check task and settings | Load trusted task/providers in the sandbox; select `--resolve-task-settings` to resolve task-dependent settings. | `task-check-001/index.html`; fix failures before continuing. |
| 2. Inspect the environment | Query local hardware and resolve launch settings. Select `--bind-launch` for later reviewed execution. | `environment-preview-001/index.html`, including all resolved launch defaults and unchecked requirements. |
| 3. Review or explicitly skip | Send the saved review packet to the configured LLM, or record an explicit skip. | Findings and the saved receipt; decide how to address findings. |
| 4. Save the launch request | Name the exact reports, their hashes, receipt and any finding acknowledgements. | The [reviewed-launch request recipe](reviewed-launch.md#request-recipe). |
| 5. Launch | Run `python -m tools.setup_review.launch --request reviewed-launch.json` with your installation's Python. | Workflow results under your chosen run workspace. |

Step 1 needs Linux, bubblewrap and working user namespaces. It does not silently
fall back to executing task factories on the host. Step 2 queries hardware but
does not allocate a model or train. Step 3 calls a provider only if you request
an LLM review. **Step 5 starts the real experiment and can spend API credits and
GPU time.** A successful launch check does not mean the experiment succeeded;
inspect its normal manifest, output records and score.

If you change a model route, task file or another bound setting after review,
make fresh reports and a new review/skip receipt. Acknowledging a finding cannot
override a changed input. If a failed launch initialized the run workspace,
choose a fresh workspace as well.

## What a successful check does not prove

Configuration consistency does not establish data correctness, model quality,
provider credit, enough GPU memory or successful training. A key-presence check
reports names and presence only; it never authenticates. Selected GPU protection
is a separate [explicit execution setting](../../core/runtime_control/README.md#protecting-a-native-gpu-attempt).
Read the remaining checks on the HTML page before launching.

For exact flags, report formats, source coverage and error handling, see the
[command reference](usage.md), [task-settings contract](task-settings.md),
[environment contract](environment-settings.md), [semantic-review contract](semantic-review.md)
and [reviewed-launch contract](reviewed-launch.md). For a caller you assemble
yourself, start with [external orchestration](../orchestration_setup/README.md).
