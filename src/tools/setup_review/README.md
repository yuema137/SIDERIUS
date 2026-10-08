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
Non-finite numeric declarations such as `NaN` or `Infinity` are generally rejected
rather than silently converted to JSON `null`. The two formal delta fields are an
exception: the runner deliberately ignores them when its formal gates are off.
The preview preserves those values as explicit `nan`, `+inf` or `-inf` numeric
labels; the optional task-settings check below applies the actual formal policy
and rejects nonfinite deltas when those gates are enabled.

Invalid requests, unreadable selected configuration files and unsupported modes
exit nonzero with a message. A failed or interrupted write may leave an incomplete
report directory. Inspect or remove that directory yourself before retrying, or
choose a new output name; the tool does not delete report contents. Each file is
published atomically and without overwriting, but the two-file pair is not one
atomic transaction. Success is printed only after both files have been written.

This tool leaves existing execution behavior, experiment prompts and runtime defaults unchanged.
It is one part of optional setup assistance, not a completed onboarding workflow
or paper-artifact reproduction check.

## Optionally check that the task and its providers compose

The ordinary preview above never imports your task. If you also want to check
whether its declared plugins and installed providers can load together, run this
**separate command**. It executes trusted task/provider factories in the existing
[workspace sandbox](../workspace_sandbox/README.md). It requires Linux, bubblewrap
and enabled user namespaces; there is no fallback to executing on the host.

Use task code you trust. Keep credentials out of your source installation and
every directory you expose: the child can read all files under a mounted root,
and arbitrary factory code can print what it reads. The sandbox provides a wall
timeout and its supported process/filesystem/network/device boundaries. It is
not a defense against malicious same-user code, nor a host-memory or disk quota.

Reuse `review-request.json` from the earlier example. Keep your task code/configs
under `tasks/my-task` and your dataset separately under `data`. The data directory
is not exposed to this check. Declare every external source/config/provider root
needed by composition with another `--read-only`; the exact Python installation
and its framework source are already mounted by the sandbox owner.

```bash
cd /home/alex/siderius-project &&
/path/to/SIDERIUS/.venv/bin/python -m tools.setup_review.check_task \
  --request review-request.json \
  --read-only /home/alex/siderius-project/tasks/my-task \
  --scratch /home/alex/siderius-project/check-scratch-001 \
  --output /home/alex/siderius-project/task-check-001 \
  --timeout-seconds 30
```

Choose the timeout for this check; `30` is an example, not a training budget.
Both new directories must have existing parents, use canonical absolute paths,
and be separate from one another, the actual run workspace, installation and
read-only roots. Existing directories are refused. No caller environment variables,
API keys, GPU devices or network access are forwarded. A plugin needing unavailable
resources fails visibly; the checker does not widen access or install dependencies.

The scratch directory holds the child's request, response and any files its
factories create. Its generated-library binding is separate from your actual run
workspace. The report directory contains:

| File | What to inspect |
|---|---|
| `index.html` | Start here: task/provider check outcome, metric and direction, dataset declaration, parameter rules, inference policy, Health declaration and remaining limits. |
| `settings.html` | CLI defaults, static model routes, original arguments and the ordinary command to run later. This is the declaration-only preview, linked from the task-check page. |
| `report.json` | Typed task-check result, including the original v2 declaration snapshot, selected limits, actual sandbox profile, source identities and runner status. |

**Without extra options, passed means the task and selected planner provider composed.** It does not mean
the data is valid, a model trains, Health checks pass, credentials work, or hardware
fits the budget. The checker does not invoke data loaders, construct training
models, materialize Health or call an LLM. Task imports/factories are executable
Python, so they can still perform arbitrary computation within the declared
boundary. For example, a missing installed planner strategy produces a failed
check even if the task itself composed; the page preserves those task facts and
identifies the provider failure. Configure or install the intended provider yourself
and rerun; no historical or native fallback is silently selected.

Child-result JSON is limited to `1048576` bytes (1 MiB) by default. The report records
the actual `result_max_bytes`. If an expected task summary exceeds it, inspect the
cause and explicitly add, for example, `--result-max-bytes 2097152` on a new check.
This limits result transport; it does not restrict dataset size or allocate memory.
Special files, links, malformed results and mismatched request identities are refused.

Failure or timeout returns a nonzero exit and leaves a report when possible. A
changed manifest is marked stale. Other source identities describe what the
composition captured; they do not prove every ambient import stayed unchanged.
The runner reports status, return code and elapsed time, not independently measured
proof that no orphan process survived. No report is enforced by the ordinary launch.

Each output file is published without overwriting; the page is published last.
An interruption can leave partial report/scratch directories. Inspect them yourself
before removing them, or choose new names. They are diagnostic artifacts, not
experimental results. This command does not create the actual run workspace.

## Resolve settings that depend on your task

Add `--resolve-task-settings` when you also want to see the selected data
partitions, whether analysis is enabled, and the effective Health configuration.
Health configuration describes which checks would run and what they would do;
this command does not run those checks against data or model results.

Declare `--healthgate_mode` and `--result_authority` in the saved run arguments,
as the standard runner requires. The checker uses the same validator and reports
contradictions instead of choosing these values for you. For example,
`observe_only` with `scientific` fails because observation alone cannot certify
a scientific result. Use the combination appropriate for your experiment.

```bash
cd /home/alex/siderius-project &&
/path/to/SIDERIUS/.venv/bin/python -m tools.setup_review.check_task \
  --request review-request.json \
  --read-only /home/alex/siderius-project/tasks/my-task \
  --resolve-task-settings \
  --scratch /home/alex/siderius-project/check-scratch-002 \
  --output /home/alex/siderius-project/task-check-002 \
  --timeout-seconds 30
```

Open `task-check-002/index.html` and read **Task-dependent settings**. For a task
with four partitions, an omitted `--data_scope` resolves to `[0, 1, 2, 3]`.
Analysis becomes enabled or disabled according to the actual task binding and
your override. Health gates list their cadence, checks and actions. Disabled
Health stays visibly disabled; it does not produce a pretend empty enabled run.

If your saved arguments select an external `--health_checks_config`, expose its
source directory with another `--read-only`. Relative Health paths use the saved
working directory. Keep datasets outside exposed roots. Generated Health YAML
lives in `check-scratch-002/task-settings/health_checks_effective.yaml`; the report
saves its resolved fields and body digest, so you can inspect it after removing
scratch. Neither directory is your future experiment workspace.

This option checks configuration relationships only. It does not inspect dataset
contents, measure memory/time, authenticate keys, resolve hardware-dependent
watchdog profiles, or choose future training parameters for the agent. Those
unknowns remain on the page. The ordinary command in `settings.html` still does
not compare current inputs with this report. After changing inputs, make a new
check before using that command.

The optional review below can read these additional saved facts. Its packet uses
`setup-review/v2` when resolved task settings are present; older report packets
retain `setup-review/v1`. Read the saved packet before sending it to a model.
The [task-settings contract](task-settings.md) describes the callable input,
shared rule owners, transport and source-identity boundary.

## Ask for an optional LLM review, or explicitly skip it

After reading a saved declaration or task-check report, you can record a separate
decision about LLM review. This step reads the saved JSON snapshot; it does not
reload your task or prove that the original files are still unchanged. It never
starts the experiment. Ordinary launchers remain usable without this step.
For a saved task check, it validates only the declaration, task/provider result
and recorded limitations used for review. Old sandbox/request/execution wrappers
are discarded, so cleaning up the earlier scratch directory does not prevent
reviewing its saved facts. This does not certify that the old sandbox can launch now.

To **skip LLM review explicitly**, create `skip-review.json` in your project:

```json
{
  "operation": {
    "kind": "skip",
    "report": "/home/alex/siderius-project/task-check-001/report.json",
    "expected_sha256": "<SHA-256 of that exact report.json>",
    "output": "/home/alex/siderius-project/semantic-review-001",
    "input_max_bytes": 1048576,
    "reason": "I will inspect the settings and remaining requirements myself."
  }
}
```

Replace the placeholder with the result from
`sha256sum /home/alex/siderius-project/task-check-001/report.json`. Use the
declaration report path instead if you have not run the task check. The new output
directory must not exist; its parent must exist. Report/output paths are absolute,
and the output must be separate from the installation, source report and run workspace.

```bash
/path/to/SIDERIUS/.venv/bin/python -m tools.setup_review.review \
  --request /home/alex/siderius-project/skip-review.json
```

Open `semantic-review-001/index.html`. It records **skipped**, your reason and the
exact source digest. This is different from the original report's **not_performed**:
the original report stays unchanged. Skipping imports no provider gateway and
does not read provider credentials, authenticate, or make an LLM request.

For an **actual LLM review**, copy the operation into another request file, use a
new output directory, replace `kind` with `"review"`, remove `reason` and add:

```json
"llm": {
  "provider": "openai",
  "model_id": "<your supported reviewer model>",
  "max_retries": 1
},
"total_review_seconds": 120,
"request_timeout_seconds": 60
```

These numbers are examples for this optional review, not experiment budgets or
new framework defaults. Set the provider's key in your launching environment;
never put a key in either JSON file. Explicit review uses the existing gateway's
environment/dotenv loading behavior. Running the command with `kind: review`
contacts that provider and can incur charges. Use it only after choosing an
appropriate model, limits and permission to send the report's selected text.

The review sends selected scalar settings, static model routes, key-name statuses
and unresolved checks. A task-check snapshot also contributes selected task,
metric, forward-contract, parameter-rule and inference-policy declarations.
It omits raw argv, arbitrary configuration extras, advice, source-code files and
data. This deliberately limited packet may miss relevant settings; the page is
not a complete effective-configuration review. Text in an included field can
still contain secrets: inspect your source report before sending, and inspect
the saved packet before sharing it. There is no automatic guarantee that all
human or model text is safe to publish.

The total review deadline starts before report reading and continues through
gateway construction, requests/retries and response validation. It is cooperative:
a blocked file read or constructor cannot be forcibly interrupted, but an expired
operation cannot send a new request or accept a late answer at a checked boundary.
It is neither a hard wall-clock watchdog nor a dollar/token cap. `max_retries`
retains the gateway's existing total-attempt semantics; content-level retries are
separate, so one review can send multiple API requests.

| Saved file | What it means |
| --- | --- |
| `index.html` | Start here: reviewed/skipped/failed, findings and remaining limits. |
| `receipt.json` | Typed decision, source/prompt digests, reviewer settings and timing evidence when available. |
| `packet.json` | Exact selected semantic facts. Skips also save this local packet. |
| `system.txt`, `user.txt` | Exact prompts prepared before a review request; absent for a skip. Their existence alone does not prove a request was sent. |
| `token_usage.jsonl` | Existing gateway telemetry when responses were recorded; absence is not proof that no request reached the provider. |

**Reviewed means a schema-valid model answer was accepted.** It does not mean
the task passed deterministic checks or the experiment is ready. A failed task
check remains visible even if the model reports no findings. Review errors return
a nonzero exit and save a failed receipt when the output can be prepared safely.
Early input errors may produce no directory; interrupted writes can leave a
partial directory. Existing files are never overwritten or deleted automatically.
Use a new output name for each attempt.

To change settings, edit your original task/experiment files, regenerate the
appropriate preview/check, and choose a new review output. This operation neither
checks stale source files at launch nor imposes a receipt gate. Custom Python
orchestration and multi-iteration runners are not represented by this standard
snapshot; do not substitute a different command and claim it was reviewed.

An assistant can invoke the same typed callable or inspect its `SKILL_SPEC`;
see the [semantic review API contract](semantic-review.md). This is an optional
review building block, not completed Professional/Assistant onboarding or proof
that the four independent onboarding trials have run.
