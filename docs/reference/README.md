# Configuration and execution reference

Use these pages when you need an exact field, default, owner or failure rule.
For an introduction, start with [getting started](../getting-started/README.md)
or the [concept guide](../concepts/README.md).

| Decision | Reference |
| --- | --- |
| What a task declares | [Task composition](task-composition.md) |
| Which file or command owns an option | [Configuration map](configuration-map.md), [entrypoints](entrypoints.md) |
| Which planner is selected | [Planner strategies](planner-strategies.md) |
| How training is bounded | [Training batches](training-batches.md), [cooperative budget](cooperative-training-budget.md), [budget diagnostics](training-budget-diagnostics.md) |
| How resources are estimated | [Preflight estimation](preflight-estimation.md) |
| How model selection and retention work | [Checkpoint selection](checkpoint-selection.md), [checkpoint retention](training-checkpoint-retention.md), [model output retention](model-output-retention.md) |
| How evaluation is executed | [Candidate evaluation](candidate-evaluation-execution.md), [private validation](private-validation-execution.md) |
| How data preparation affects execution | [Target standardization](target-standardization.md), [HDF5 read cache](hdf5-read-cache.md) |

Cross-package lifecycle rules are in the
[mechanism reference](../agent-reference/mechanisms/README.md).
