"""Shared execution facts for agents designing native-trainer candidates.

This describes the shipped trainer, not scientific advice or a new lifecycle
hook. Keep it aligned with train_engine_sandbox and TrainingBudgetReceipt.
"""

NATIVE_TRAINING_CONTRACT = """\
## Native training execution boundary

The framework owns the optimizer loop, validation and checkpoint lifecycle.
A generated model plugin supplies its configuration and forward computation;
naming a model or buffer after a training intervention does not implement it.

- The native trainer defaults to exporting the last completed epoch.
  `train_config.checkpoint_selection="best_validation_loss"` instead exports
  the earliest epoch with minimum loss on the fixed training-validation scope;
  it requires that scope and does not use final scoring results. The selected
  epoch is recorded in `selected_checkpoint`. It does not perform scientific
  early stopping or invoke a plugin's custom training loop / validation callback.
  A proposed scheduler
  or independent ensemble-member training procedure needs an actual supported
  execution path; describing one does not make it run.
- `train_config.target_standardization="training_pool_global"` enables a
  framework affine transform for continuous regression: fit one global mean
  and population standard deviation from the authorized training pool, compare
  predictions and targets in standardized units, and export physical-unit
  predictions. With this policy the base model must predict standardized values;
  do not add a second inverse transform inside the plugin. Statistics are stored
  in the checkpoint; final evaluation labels are never used to fit them.
- With the default `target_standardization="none"`, target statistics are not
  automatically injected into model buffers. If a
  proposal requires target normalization, identify where the statistics come
  from, how they are initialized from the authorized training scope, and how
  output and loss units remain consistent with the task contract. Zero/one
  defaults are an identity transform, not fitted standardization. Do not read
  validation/test labels to fit statistics or invent dataset constants.
- The native loss receives model output and dataset targets. An affine output
  head alone does not standardize the optimization loss. A jointly optimized
  average of ensemble outputs is not independently trained/restored members.
- Design within supported interfaces. Explicitly report an unavailable
  intervention and any approximation; do not claim the original intervention
  was tested. Reviewers must keep trainability and specification alignment
  separate: runnable code may still fail to implement the causal hypothesis.
"""
