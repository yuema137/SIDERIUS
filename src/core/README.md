# Run execution and recovery

This package starts and limits child processes, records run identity, and
restores earlier results when a run resumes. Its resource checks decide whether
work can fit the declared limits. Scientific meaning comes from the task
package; core code manages the execution and evidence around it.

Saved node outputs preserve non-finite results such as infinity and NaN in
standard JSON. The native output models decode these records when you load
them; existing records remain readable. See the
[record encoding contract](core-contract.md#versioned-non-finite-record-json-issue-1111)
if you write a tool that reads the raw JSON.

## Find the right part

| Need | Start here |
| --- | --- |
| Resume or inspect a run | [Workspace reference](../../docs/guides/workspaces-and-resume.md) |
| Understand saved identity | [Persistence contract](../../docs/agent-reference/mechanisms/persistence-and-resume.md) |
| Investigate execution limits | [Runtime controls](runtime_control/README.md) |
| Understand detected GPU support | [Accelerator facts and limits](accelerator-runtime.md) |
| Package local task code | [Local-code packages](local_code/README.md) |

## Technical detail

The [run execution and recovery contract](core-contract.md) records interfaces,
inputs, outputs, state changes, refusal behavior and related tests. Cross-package
rules remain with the mechanism references it links.
