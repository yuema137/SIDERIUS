# src/core/runtime_control

Runtime measurement/admission/observation/record/watchdog modules. Start at
[`bootstrap.py`](bootstrap.py), [`admission.py`](admission.py), and the
current admission boundary. The [runtime estimation guide](../../../docs/design/runtime_estimation_and_calibration.md)
is historical design context, not a second execution authority.
Focused admission tests are in [`test_admission.py`](../../../tests/unit/core/test_admission.py);
forecasts and blocking measurements are distinct authorities.

See [the parent guide](../README.md) for child ownership and the focused validation route.

## Measurement dimensions

Measurement identity records whether temporal segmentation is applicable. The
ordinary temporal path carries a positive `seg_size` and preserves the
existing calibration hash. A task-owned fixed-shape probe carries
`segmentation_applicability="not_applicable"` and `seg_size=None`; it may
measure bounded resource use, but the calibration derivation quarantines it
from temporal throughput evidence. No caller may replace the absent dimension
with a framework default. `TaskProbeDataSpec` carries this typed fact
explicitly; merely supplying task probe data does not decide applicability.

### First-epoch training allocation

An explicit `training_budget` is checked before optimizer and validation batch
dispatch, using its continuing monotonic clock and downstream reserve. Once
validation calibration completes, its verified full-pass cost is checked against
remaining training time, and normal runtime admission is refreshed immediately.
A refusal unwinds the attempt, persists its reason in the runtime sidecar, and
produces no completed epoch, checkpoint or score from partial validation. The
validation scope is never shortened to fit. A running batch is not killed and
may finish late; this is cooperative allocation, not a prediction watchdog.
Unbudgeted runs keep their existing behavior. Batch size, epoch limits and
scientific stopping/checkpoint selection are unchanged.

### Fast-phase calibration

`AdaptiveVerificationConfig.max_steps` bounds acquisition of stability and the
minimum observation count. Existing rolling-median detection remains the primary
path. When the measured median predicts that observations cannot reach `min_timed_ms` inside
`max_steps`, a 100-observation suffix may establish fast-phase evidence if the
normalized-rate medians of its first and second halves agree within the existing
relative stability tolerance. This distribution check tolerates heterogeneous
batch costs without treating a trend as steady. Reachability accounts for the
observations consumed before the earliest possible steady-state declaration; at
the defaults the fallback is unreachable around 2.7 ms and above, so those phases
retain the existing time requirement and detector behavior. Re-arming still
discards the old plateau's evidence. The wall bound also includes local verifier
processing.
Exhausted or unstable traces never become verified by relaxing evidence floors.
Relative slow observations are recorded in measurement details. A consecutive
streak of `steady.stable_windows` above `pathological_factor` times the prior
plateau fails verification; an isolated spike does not. Explicit `max_unit_ms`
still fails immediately after stabilization. These rules do not change data
selection, model size, resource budgets or prediction-watchdog enablement.

### Calibration across separate passes

Validation may need several epochs to gather enough timing evidence. Its
verification window counts active validation intervals, including dataset
construction, loading, transfers and computation. Training between those
intervals does not consume the validation window. Observations and stability
requirements survive between passes; an exception also closes the active
interval. Continuous callers keep the original uninterrupted wall clock.

Measurement receipts report `verification_active_wall_ms` and
`verification_excluded_inactive_seconds` to distinguish a real phase stall from
time spent elsewhere. The enclosing training allocation and campaign deadline
continue running throughout; pausing calibration does not extend either budget.
