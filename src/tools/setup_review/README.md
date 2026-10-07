# Preview the settings for one run

This optional tool shows the arguments you prepared for a standard, single-iteration
SIDERIUS run. It saves a local HTML page and JSON report with the CLI defaults,
your settings after argument parsing and advice loading, and the command to run
separately. You can use ordinary SIDERIUS launchers without this tool.

**The preview is not a complete preflight.** It does not run task plugins, check
your dataset, authenticate credentials, discover a GPU, call an LLM or start training.
A report means the supported declarations were read; it does not mean the experiment
will run successfully. Hardware-dependent watchdog settings, task implementation
and task-dependent node activation remain explicitly unchecked. Static model routes
are resolved; endpoints selected by an SDK or its environment remain unknown.

## Prepare the request in your own directory

First [install SIDERIUS](../../../docs/getting-started/installation.md) and prepare
your external [task package](../../../docs/reference/task-composition.md), dataset
and LLM configuration. This tool does not create those inputs. The example below
assumes they already exist; replace `/home/alex/siderius-project` and the SIDERIUS
Python path with your actual paths.

Keep the task/configuration files separate from the new **run workspace**, which
will receive generated code and experimental results when you later launch:

```text
/home/alex/siderius-project/
├── tasks/my-task/task.yaml       # existing task composition manifest and plugins
├── data/                        # existing data, or use an external absolute path
├── llm/agents.json               # existing model routing; no API keys
├── review-request.json          # write this request
├── review-001/                  # inspector creates this report directory
│   ├── report.json
│   └── index.html
└── runs/demo/                   # later launch creates this run workspace
```

Save this as `review-request.json`. `argv` contains the arguments after
`python -m workflows.run_one_iteration`; do not put a shell command or Python
executable into it. The two JSON keys shown here are the complete request schema.

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
    "--max_rounds", "3"
  ]
}
```

The run workspace must be absent or an empty directory. The task manifest must
exist as a regular file; its contents and plugins are not validated by this tool.
For this example, `max_rounds` declares three tuning rounds within one iteration,
not three workflow iterations. Check the remaining defaults in the report before
deciding whether they fit your experiment.

## Generate and read the report

Run from the directory named by `working_directory`, using the Python interpreter
from your SIDERIUS installation. The inspector verifies the directory instead of
changing it inside your process.

```bash
cd /home/alex/siderius-project &&
/path/to/SIDERIUS/.venv/bin/python -m tools.setup_review \
  --request review-request.json \
  --output /home/alex/siderius-project/review-001
```

`--request` may be relative to your current directory; `--output` must be absolute.
The output parent must exist, and `review-001` must not exist yet. The report and
run workspace must be outside the framework checkout and must not contain one
another. Existing reports are never overwritten: use `review-002` for another
inspection. Nothing is written to the task package or run workspace.

Open `review-001/index.html` in your browser. It works offline without JavaScript
or a web server. Start with the declared rounds, data portions and budgets; each
links to its full parameter row. Expand **CLI help** for the existing parser's
description. The full table shows every CLI default beside the parsed setting.
Help describes the CLI contract; it does not mean every downstream interaction
or enforcement rule has been checked by this preview.

For example, `--max_rounds 5` leaves the CLI default column at `3` and displays `5`
as your setting. A missing `trial_portion` stays `null`: this declaration has not
fixed its value. It does not mean zero training data. A missing LLM node block
also stays visibly absent in the declared configuration. The separate static-route
table applies each node's own defaults.

The report preserves the original argument list, including aliases and abbreviated
flags. It does not guess which flags were explicitly written by comparing values
with defaults. Advice is loaded using the standard advice owner; per-agent CLI
advice retains its normal precedence over file advice. Relative paths follow the
existing runner rules: ordinary input paths use the working directory, while
relative literature configuration paths remain relative to the SIDERIUS checkout.
Prefer an absolute literature configuration path for an external project.

## Check model routes and optional key presence

The static-route table shows the four individual nodes, three proposer stages,
tuner planner and reflector, and literature main and search routes. It includes
models, reasoning effort, retry settings, request timeouts and client reuse.
Shared-client labels describe matching routes, not which stage executes first.
For example, omitting `implement` uses the implementor's model default; writing
`"implement": {}` uses the LLM configuration schema's default instead. The table
shows that difference rather than treating an empty block as an absent block.

`conditional` means execution must reach that step before it calls the model.
`task_dependent` means task composition must first decide whether to enable it.
`disabled` and `pseudo` routes do not need provider keys. These are possible
routes, not a prediction of call counts or costs. Planner and reflector share
the planner's transient-error retry setting; `null` means unbounded retries for
those errors. A finite `max_retries` counts total attempts, including the first
request; zero still permits the first request. Timeout attempts have a separate limit.

By default, the report lists provider key names without reading their values.
To check whether the current shell supplies nonempty values, request it explicitly:

```bash
cd /home/alex/siderius-project &&
/path/to/SIDERIUS/.venv/bin/python -m tools.setup_review \
  --request review-request.json \
  --output /home/alex/siderius-project/review-002 \
  --check-environment
```

This flag belongs to the inspector; it is not added to the saved launch command.
The check reports `present_nonempty`, `missing`, `not_checked` or `not_required`.
It never saves key values, lengths or hashes, loads dotenv/key files, or contacts
a provider. A nonempty value does not prove that authentication will work. Set
missing variables in the shell you will use to launch the experiment.

## Launch separately after checking the remaining requirements

The page's **Command to run separately** section contains your current Python
interpreter, the standard module and the original arguments. Use that command only
after preparing the task, data, environment, credentials and resource budgets.
Launching can spend API credits and start training; previewing does neither.

`report.json` contains the same inspection snapshot in the typed v2 format. Its
`declaration_inspected` outcome means settings were read, and `llm_review` is
`not_performed`. It is not an approval or an explicit user decision to skip a
future LLM review. The ordinary launch command does not enforce this report or
detect subsequent edits. Generate another preview after changing your inputs.

Store API keys in the environment expected by your provider, not in the request,
LLM config or advice text. The inspector never reads key files; it reads the named
environment values only when you select `--check-environment`. It does show the
declared arguments and advice in local reports, so do
not paste secrets into those fields or publish reports without reading them.

## Supported scope and errors

This first version supports only a fresh standard iteration 1. It refuses seed
evidence, resume/replacement flags, fixed-candidate plans and the runner's
print-only flag. Multi-iteration launchers and custom Python workflows are outside
its scope. `--help` belongs on the inspector command, not inside a saved run argv.
Non-finite numeric declarations such as `NaN` or `Infinity` are rejected rather
than silently converted to JSON `null`.

Invalid requests, unreadable selected configuration files and unsupported modes
exit nonzero with a message. A failed or interrupted write may leave an incomplete
report directory. Inspect or remove that directory yourself before retrying, or
choose a new output name; the tool does not delete report contents. Each file is
published atomically and without overwriting, but the two-file pair is not one
atomic transaction. Success is printed only after both files have been written.

This tool leaves existing execution behavior, prompts and defaults unchanged.
It is one part of optional setup assistance, not a completed onboarding workflow
or paper-artifact reproduction check.
