# `tools/`: command-line tools for preparing, running and checking work

This package holds the command-line tools you use to prepare and run a
SIDERIUS experiment, plus supporting tooling for the checkout (such as CI
selection). It is not a task package and does not own scientific data,
generated models or run workspaces.

## Find the right tool

| Need | Tool | Start here |
| --- | --- | --- |
| Prepare a `workflow.py` run offline | `python -m tools.candidate_prepare` | [Candidate preparation](candidate_prepare/README.md) |
| Launch a prepared run, follow its status and logs, stop, pause or resume a research loop | `python -m tools.candidate_operations` | [Candidate operations](candidate_operations/README.md) |
| Do the same in a browser (experimental) | `python -m tools.candidate_console` | [Local candidate console](candidate_console/README.md) |
| Set up orchestration, where your coding agent chooses each research step | `python -m tools.orchestration_setup` | [Orchestration setup](orchestration_setup/README.md) |
| Run commands in the bubblewrap sandbox | `python -m tools.workspace_sandbox` | [Workspace sandbox](workspace_sandbox/README.md) |
| Review the settings of a standard chain iteration and get an HTML report | `python -m tools.setup_review` | [Setup review](setup_review/README.md) |

Run each tool with this checkout's `.venv/bin/python`. The
[getting-started guide](../../docs/getting-started/README.md#write-and-run-a-workflow-declaration)
shows how preparation and operations fit together. The older chain launcher and
its helper scripts are under [`scripts/`](../../scripts/README.md); workflow
behavior belongs to [`workflows/`](../workflows/README.md).

All paths are derived from the current checkout or supplied explicitly. Tools
must not edit the checkout as a substitute for caller-owned task configuration.

## Other tools

[`candidate_worker`](candidate_worker/README.md) runs one native candidate
request directly; most users reach it through candidate operations.

`python -m tools.adaptors` checks a custom adaptor that lives in your own
project: `inspect` shows its identity, `self-test` runs its examples twice, and
`admit` records a passing result under your project's `.siderius/adaptors/`.
Self-test runs your code as your user; network and files are not blocked. Run
the command as `python -P -m tools.adaptors` so files in your current folder
cannot replace framework modules. Workflows cannot run admitted adaptors yet. See the
[custom adaptor contract](../workflows/custom_adaptors/custom-adaptor-contract.md).
