# Launch and inspect runs with scripts

The recommended way to prepare and run SIDERIUS 1.1 is not in this folder: it
is the pair of command-line tools `tools.candidate_prepare` (prepare a
`workflow.py` run offline) and `tools.candidate_operations` (launch it, follow
its status and logs, and stop, pause or resume a research loop). Start with
[Write and run a workflow declaration](../docs/getting-started/README.md#write-and-run-a-workflow-declaration).

The scripts here serve the older chain launcher (used by the paper tasks and
the companion tutorials), Slurm submission, runtime bookkeeping and opt-in
diagnostics. They connect a selected checkout to a caller-owned task, data
directory and workspace. Scientific campaign launchers live in siderius-exp.

## Find the right part

| Need | Start here |
| --- | --- |
| Preview or launch a chain with `run_chain.sh` (older route) | [Launch scripts](launch/README.md) |
| Use a scheduler | [Slurm entry](slurm/README.md) |
| Inspect runtime bookkeeping | [Runtime utilities](runtime/README.md) |
| Diagnose a machine or provider | [Opt-in diagnostics](diagnostics/README.md) |

## Technical detail

The [launch and inspect runs contract](script-contract.md) records interfaces,
inputs, outputs, state changes, refusal behavior and related tests. Cross-package
rules remain with the mechanism references it links.
