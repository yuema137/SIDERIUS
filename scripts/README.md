# Launch and inspect runs

These scripts connect a selected checkout to a caller-owned task, data directory
and workspace. Start with launch for research runs, runtime for bookkeeping,
or diagnostics for an explicit environment investigation. Scientific campaign
launchers live in siderius-exp.

## Find the right part

| Need | Start here |
| --- | --- |
| Preview or launch a chain | [Launch scripts](launch/README.md) |
| Use a scheduler | [Slurm entry](slurm/README.md) |
| Inspect runtime bookkeeping | [Runtime utilities](runtime/README.md) |
| Diagnose a machine or provider | [Opt-in diagnostics](diagnostics/README.md) |

## Technical detail

The [launch and inspect runs contract](script-contract.md) records interfaces,
inputs, outputs, state changes, refusal behavior and related tests. Cross-package
rules remain with the mechanism references it links.
