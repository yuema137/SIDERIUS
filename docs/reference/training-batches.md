# Retaining a partial final training batch

`train_config.drop_last` defaults to `true`, preserving existing training.
Set it to `false` to optimize every row selected for each epoch, including an
incomplete final batch. This does not change the selected training scope or
per-epoch sampling fraction; both must also be full to guarantee full-pool use.

At 40,000 selected rows and batch size 128, the default performs 312 optimizer
steps and omits 64 rows; `drop_last=false` performs 313 steps and uses all rows.
The final batch must be supported by the candidate architecture. The framework
does not pad, duplicate rows, or silently change batch size to accommodate a
model that cannot train on its tail (for example some batch-normalization
configurations at a one-row batch).

Task-scope and legacy workload resolvers, step guardrails and time estimation
use the same floor/ceiling rule as the actual DataLoader. A retained partial
batch counts as an optimizer step. With a mean-reduced criterion, epoch loss
is weighted by actual batch row counts so a short tail is not overrepresented.
With a sum-reduced criterion, the batch losses are summed without weighting
them a second time. The compatibility default retains its historical reporting.
Optimizer updates retain the configured criterion and learning rate.

With tail retention enabled, `training_history.training_samples` records the
actual rows used in each completed epoch. It must contain one positive count
per completed epoch. It is omitted under the compatibility default.

An experiment can freeze the choice with the existing workflow parameter rule
`train_config.drop_last: {exact: false}`. The rule is part of run identity;
switching policy requires a fresh workspace when it is frozen by the workflow.
