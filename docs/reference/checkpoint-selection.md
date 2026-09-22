# Native training checkpoint selection

`train_config.checkpoint_selection` controls which completed epoch is exported:

| Value | Behavior |
| --- | --- |
| `last_completed_epoch` (default) | Export the last completed epoch, preserving the existing policy. |
| `best_validation_loss` | Export the earliest epoch with minimum finite training-validation loss. |

Best selection requires an explicit fixed training-validation scope and fails
before model construction if it is missing. It uses the loss computed after
each complete epoch, never the final scoring result or test labels. Ties retain
the earlier epoch. Training still follows its configured time/epoch limits;
this option does not enable early stopping or a learning-rate scheduler.

The trainer retains one CPU copy of the best model state (parameters, buffers,
module metadata and extra state). It restores that state only after training,
before final static observations and serialization. This costs host memory
approximately equal to one model state, plus copy/restore overhead; it does not
keep an additional GPU model or a checkpoint file for every epoch. Snapshot
copy time is included in cooperative epoch budgeting. Optimizer state is not
restored because this artifact is for inference, not continuation training.

`selected_checkpoint` records the one-based epoch and validation loss in the
training result and experiment record. The result boundary verifies that they
agree with the validation history and requested policy. A missing or invalid
receipt fails the attempt rather than silently exporting the wrong policy.
`final_loss` and training history still describe the actual last training epoch;
they are not rewritten to pretend training ended at the selected epoch.

Experiments can freeze this choice using the existing workflow parameter rules:

```json
{"workflow_parameter_rules": {
  "train_config.checkpoint_selection": {"exact": "best_validation_loss"}
}}
```

These rules participate in run identity, so changing the frozen choice requires
a fresh workspace. Use an infra revision that supports the field. Existing
experiments without the rule retain the default policy.

This capability does not automatically normalize targets. A normalization
proposal must supply a valid initialization path using only its authorized
training scope and preserve the task's output and objective units. The shared
agent guidance explains this boundary; it does not enforce scientific fidelity
or establish that any particular model has learned.
