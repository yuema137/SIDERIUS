# Runtime replay contract

Owner: `tools.runtime_replay`; executable boundary:
`core.runtime_control.probe_subprocess.run_worker` → `probe_worker_main`.
This tool inspects persisted forensic snapshots and optionally measures surviving
implementations. It does not reconstruct unimplemented drafts or reproduce an
old candidate from its name alone.

## Read-only modes

```bash
.venv/bin/python -m tools.runtime_replay metadata --snapshot /path/to/snapshot --json
.venv/bin/python -m tools.runtime_replay executable --snapshot /path/to/snapshot --plan --json
```

Both require only the snapshot. Omitting `--run` selects planning. `--plan` and
`--run` are mutually exclusive. Neither mode requires a task or output directory,
creates a worker, or measures runtime. Eligibility reflects the current process's
model registry; planning does not import an executable task configuration.

## Effectful mode

```bash
.venv/bin/python -m tools.runtime_replay executable \
  --snapshot /path/to/snapshot --run \
  --probe-config /path/to/replay-probe.json \
  --output-dir /path/to/caller-workspace/replay --json
```

`--probe-config` and `--output-dir` are required with `--run`. The previous
`--data-dir`, `--segmentation-size` and `--batch-size` flags cannot declare a task
and have been replaced by the explicit configuration. There is no implicit
scientific task, objective, data root or temporal geometry.

`ReplayProbeConfig` owns the JSON envelope:

| Field | Contract |
|---|---|
| `task_probe_data` | Required existing `TaskProbeDataSpec`: absolute `manifest_path`, pinned `semantic_fingerprint`, task-serialized `training_scope_payload`, `sampling` with absolute `data_dir`, and explicit `segmentation_applicability`. Optional evaluation transport is retained but this bounded probe measures one training batch for both phases. |
| `model_config_payload` | Required object, validated against each eligible candidate's registered config class inside the worker. One workload applies to all eligible candidates in this invocation. |
| `train_config` | Required `TrainConfig`, including the selected batch size and device (`cpu` or `cuda`). Its established schema defaults apply; callers should specify the workload they intend to compare. |
| `loss_config` | Optional `LossConfig`. Omission uses the manifest's objective; absence from both refuses. A supplied loss must equal a task-declared objective. |
| `caps` | `ProbeCaps`; defaults: 90 seconds, 3 warmup training steps, 7 timed training steps, 5 timed inference batches. |
| `device_vram_gb` | Optional positive threshold input for the existing contention classifier. CUDA can discover capacity if omitted. An explicit CPU probe requires this field and never reports a GPU memory measurement. |

Obtain `semantic_fingerprint` from `compose_run_task_bindings(manifest_path)`.
Build a scope with the declared task's `TaskScopeCapability.build_training_scope`
and serialize it with that capability's `serialize_scope`; do not invent a
universal scope layout. `EpochSamplingParams` owns the sampling fields. The same
carrier is used by composed resource measurement; see
[`task_data_path.py`](../../src/execute_tools/task_data_path.py).

The manifest composes its dataset profile, data adapter, model/loss plugins and
objective. Replay binds it before checking implementation eligibility. Each
worker independently composes it again and verifies its semantic fingerprint
and segmentation applicability before constructing the candidate. Missing or
changed declarations refuse. A redundant worker `data_dir` must agree with
`task_probe_data.sampling.data_dir`.

Data access uses `TaskDataPath.training_dataset` through
`load_task_probe_batch`, with the exact serialized training scope. Inputs and
supervised targets remain separate. Task-bound model construction applies the
existing class-cardinality authority, inputs use the production Model-I/O dtype
resolver, and targets use the loss-owned dtype authority. Contradictory class
counts refuse before candidate construction. The existing bound temporal adapter stays
available to existing in-process callers; standalone workers require task
transport. This change does not alter runtime decision, retention, Health,
retry, calibration-identity or certified-watchdog policy.

## Artifacts and failures

For each eligible candidate the caller's output directory receives a unique
`probe-*` directory containing `result.spec.json`, `result.worker.log`,
`result.phase`, and, if the child can report, `result.json`. The parent enforces
the configured wall cap through the existing worker process-group deadline.
The cap includes startup and the existing contention sampling window, so a
small cap can expire before a training step completes. Unique directories
prevent stale results from an earlier replay being consumed.

The snapshot remains read-only. The final replay report goes to stdout; callers
can redirect it to their own storage. Missing task/data/plugin infrastructure
aborts with a nonzero exit rather than presenting a scientific measurement.
OOM and hard-cap outcomes retain the existing measured-failure classification.
Only `cpu` and process-default `cuda` are accepted for standalone probes. Select
a physical accelerator with the deployment's `CUDA_VISIBLE_DEVICES`; indexed
strings such as `cuda:1` refuse because the existing collectors and timers use
the process-default device.
Workers retain diagnostics even when the parent cannot produce a report.

## Qualification boundary

The issue #431 regression executes the real CLI and a real worker from an
unrelated directory without inherited `PYTHONPATH`. The small Quickstart task
uses float feature vectors and distinct integer labels; actual CPU training and
inference catch dropped task transport and accidental input-as-target training.
Other worker cases reject missing transport, fingerprint drift, contradictory
data roots, objective mismatch and contradictory class counts. A separate
CPU regression supplies non-native storage dtypes and verifies that actual
model/loss execution uses the production conversion authorities. Metadata and planning remain independently
exercised. This establishes transport and task access, not CUDA timing quality,
historical paper artifact equivalence or live campaign qualification.
