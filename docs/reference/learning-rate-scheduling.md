# Native epoch learning-rate scheduling

`train_config.lr_schedule` defaults to `null`: the optimizer keeps the existing
constant learning rate, and neither config serialization nor training history
adds a schedule field. A model plugin cannot implement an optimizer scheduler
merely by declaring a buffer or describing the technique.

## Explicit configuration

Set `kind: cosine` with required positive integer `horizon_epochs` and finite
nonnegative `min_lr`, no larger than `train_config.lr`. Alternatively set
`kind: step` with required positive integer `step_size_epochs` and finite
`gamma` in `(0, 1]`. Unknown fields and incomplete strategies fail validation.
No strategy parameters are silently chosen by the framework.

Both native execution paths use zero-based epoch indices. Epoch zero uses the
base learning rate. Cosine computes
`min_lr + (base_lr - min_lr) * (1 + cos(pi * epoch / horizon_epochs)) / 2`
before the horizon; the epoch whose index equals the horizon and every later
epoch use `min_lr`. Step decay computes
`base_lr * gamma ** (epoch // step_size_epochs)`.

The schedule horizon is independent of requested epochs and cooperative budget
extensions. For example, horizon 2 gives base LR at epoch 0, the midpoint at
epoch 1, and the floor at epoch 2 and beyond. A run of only two epochs therefore
does not train at the floor. The caller chooses the intended horizon explicitly.

## Locks, evidence and measurement

The existing ParameterRules authority applies to `train_config.lr_schedule`.
An exact-null rule disables schedules even if an agent requests one. An exact
complete object freezes a strategy and its parameters. A nested rule requires
an existing compatible parent object: it does not create a strategy or guess
missing parameters. When execution-constraint disclosure is enabled, agents receive these rules
through the existing shared disclosure.

`training_history.learning_rates` contains one vector of actual optimizer-group
rates per completed training epoch. Its length matches `epochs_completed`;
values are finite and nonnegative and group count is stable. It is absent when
scheduling is disabled. Failed or zero-step epochs are not completed rows; an
aborted attempt may emit no successful history at all. Selecting an earlier
model checkpoint does not remove later completed training observations.

Prephase resource probes construct the same base-rate optimizer and measure
initial training steps. They do not advance an epoch schedule or establish
memory/time guarantees for every later schedule state. Runtime protection and
training-budget ownership remain unchanged. Checkpoints restore model weights;
this feature does not introduce optimizer-state resume.

Historical experiment modes must explicitly disable scheduling and use their
experiment-owned prompt compatibility profile. New scheduling must not be hidden
under historical text claiming constant-LR execution.
