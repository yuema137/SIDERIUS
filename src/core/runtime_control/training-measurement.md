# Bound native training measurement

## Scope and owners

`training_measurement_binding.bind_training_measurement` binds a prepared
`GpuMeasurementSpec` to its complete request, estimator assembly, discovered
plugin sources, runtime and active code-package identity. It requires explicit
task training scope, sampling seed, physical root and existing sampling/hold
channels. Binding is optional and omitted from legacy JSON. It selects the
complete-evidence protocol; ordinary phase dispatch is not activated here.

The worker verifies the binding before device resolution and after execution.
`gpu_training_components` reuses task composition authorization, native dtype,
loss and optimizer owners. Explicit target standardization uses the same
`prepare_training_target_standardization` owner as native training: full
selected training pool (`train_portion=1.0`), original seed/max_samples, streaming
float64 moments, then the original probe sampling. It does not fit the probe
prefix. Enabled standardization is corrected for unbound measurements too;
missing authorized scope/seed refuses rather than selecting a scientific default.
Disabled standardization preserves ordinary unbound behavior.

The task binding remains active through construction and iteration of both
fitting and probe datasets. Fit datasets are released before constructing the
probe dataset. This is not a guarantee about plugin caches or constant host RAM.
The existing worker deadline is checked around setup and between fit batches;
the parent owns process deadlines and RSS observation. Blocking parent driver
queries/IO can delay its next check; no hard physical partition is provided.

## Evidence and decision

`TrainingDataCoverage` distinguishes configured batch size from actual selected
dataset and tensor rows. `drop_last=False` retains a real tail; no padding or
repetition manufactures a full batch. Fitting sampling and the existing transform
receipt record the separate fitted population. Incomplete forwards retain an
absent output shape, which cannot satisfy positive assessment.

`TrainingStepEvidence` records optimizer/model parameter identity and the number
of backward calls that produced at least one model parameter gradient after a
fresh reset. Zero gradients and unused parameters are legitimate. It requires
neither all parameters to participate nor any parameter to move. The old
`parameter_update_verified` field remains a diagnostic of one watched parameter.
Current native `TrainConfig` learning-rate validation remains unchanged.

Bound setup and training reuse existing reservation holds and driver ACKs.
Each completed optimizer step has one hold. A peak no longer resident during an
observed hold cannot become an authoritative requirement. The parent uses
`observe_tree_rss`; incomplete/unavailable observations produce
`training_host_monitoring_unavailable`. It finalizes only its owned process group
through the existing termination owner, preserving signals and unknown cleanup.
No new worker may rely on a measurement that required descendant cleanup, even
if cleanup subsequently succeeded. Legacy omitted process observations retain
their existing behavior; they are not upgraded to strict evidence.

`assess_training_measurement(spec, run, cap_mib=...)` verifies complete request,
device, lifecycle, host observation, raw classification, setup/work sampling,
holds, completed connected steps, geometry and preprocessing. Only complete
positive evidence returns `max(setup_peak, training_peak)` as worker demand.
Above-ceiling complete measurements are capacity refusals. Other outcomes are
unavailable; the input retains raw CUDA OOM, timeout, RSS and journal evidence.
This assessment does not alter candidate-blame, retries or scientific Health.

## Integration boundary

This is a bounded empirical measurement of one loaded training batch, potentially
repeated for observation. Unseen values and later epochs can peak higher. The
source closure changes honestly and external estimator profiles require renewed
qualification. Existing inference request/assessment behavior is preserved.

Per-attempt shared measurement allowance, trial/native-inference phase dispatch,
checkpoint authorization handoff and production protected-observer/record wiring
remain separate integration work. This module alone does not make isolated GPU
onboarding ready. No real GPU or scientific training qualification is implied by
CPU tensor, mock-optimizer and harmless child-process tests.
