# Cooperative training budget

Opt in with `--training_budget_reserve_fraction FRACTION` on the chain,
iteration or tuner CLI. Omission preserves fixed-epoch behavior. This is a
generic execution policy; task data selection, objectives and scoring stay
with the task composition.

## Required operator settings

Declare both role time budgets and explicit role epoch ceilings in 1..100.
The existing epoch-cap resolver remains authoritative: role-specific cap,
then `max_epochs`. The reserve must be strictly between zero and one.
Incomplete configuration is rejected at the typed tuner boundary, before
training. Formal receives its own budget and ceiling even when `full_clone`
copies the Trial proposal's initial epochs.

The policy uses the resolved attempt budget, including an explicitly selected
bypass ceiling. It reaches the local training child even when forecast
admission leaves in-process admission record-only. Admission authority and
watchdog enablement are not changed by opting in.

## Execution and accounting

The monotonic clock starts when the runtime policy is resolved, before the
prephase GPU measurement and training child setup. Earlier LLM planning and
forecast admission are outside this allocation; the enclosing campaign clock
still includes them. Each attempt gets a new clock; epochs never reset it.

One initial complete epoch measures data construction, loader work, optimizer
steps, validation and loop overhead. At each completed epoch, the executor
uses the slowest complete epoch observed so far to decide whether another
fits after the explicit downstream reserve. The reserve is an operator
allowance for final inference, scoring and saving, not a measured prediction.

Training stops at the time boundary or explicit epoch cap. There is no
default optimizer-step ceiling: the chain, iteration and tuner CLIs all
default `--max_steps_per_attempt` to `0` (disabled). A fast model is not
refused merely for exceeding 150,000 optimizer steps. The legacy explicit
`--max_steps_per_attempt N` option remains available for bounded harnesses;
when deliberately enabled, it also bounds adaptive expansion: before
each epoch the actual loader size plus completed steps must fit. A normal
`step_limit` stop saves the last completed weights; inability to fit even
one epoch fails before optimizer work. The existing `allow_extreme_steps`
operator override still disables this guard. It does not stop
on loss plateaus, restore a best checkpoint, alter validation cadence or
increase batch/model size to fill VRAM. The last completed weights are saved.
A fast model can reach the epoch cap with budget remaining; that is reported
as `epoch_cap`, not convergence or successful budget exhaustion.

This is cooperative scheduling, not a process killer. An unexpectedly slow
single epoch can exceed the allowance; reserve adequacy must be checked from
real downstream timings. It does not guarantee a hard wall-time ceiling.

Each `[training_budget_decision]` logs elapsed/remaining time, observed next
unit cost, reserve, epoch count and stop reason. The trainer's result JSON
adds `training_budget`, retaining the original epoch proposal, hard ceiling,
actual completed epochs/steps, per-epoch durations and last-weight semantics.
TrainingHistory's resolved plan equals the number of epochs actually allocated;
the initial proposal and safety cap are separate provenance, so a normal
budget stop is not mislabeled as an interrupted fixed schedule.

Runtime verification initially describes one calibration epoch. At completion,
workload counts are reconciled to all executed steps/validation samples. The
original limited-scope prediction is retained in workload detail. A verified
unit rate is reprojected to the executed workload, explicitly labelled as
post-execution repricing, not a claim that the whole horizon was admitted in
advance. Missing verification remains missing. Actual duration and measured
rates remain available for subsequent calibration.

## Formal recovery

The first `full_clone` Formal attempt inherits the winning Trial configuration.
A same-round time refusal or explicit guardrail refusal allows the next validated
planner's `batch_size` and `epochs` to survive inheritance; architecture, loss
and learning rate remain inherited. The cooperative policy still decides the
executed horizon from the independent Formal allowance and epoch cap, not the
initial epoch proposal. Existing OOM recovery can also adjust model capacity.
Resource recovery never raises time/VRAM limits or bypasses admission. Trial
failures, previous-round failures and missing-evidence refusals cannot unlock
this path. Unclassified legacy refusals are not guessed to be time failures.

The existing plan-resolution trace records proposed and resolved configurations.
`[FORMAL RECOVERY]` additionally identifies the reason and preserved execution
adjustments. Preflight refusal memory records `rejection_kind=time_budget` or
`evidence`, preserving the distinction through typed record serialization.
In-process admission records likewise use `reason_code`; only
`budget_exceeded` and `training_allocation_exceeded` enable this recovery.
Verification and infrastructure failures retain their own causes and do not.
