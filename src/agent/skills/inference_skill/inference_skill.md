# inference_skill

Runs denoising inference for one attempt via
`sandbox.execute_inference` (isolated subprocess,
`execute_tools/inference_single.py`), and hosts the inference-phase
planning estimators used by the pre-flight gates.

## Files

Declared task-code integrity refusals propagate to the workflow's named chain
halt, rather than becoming ordinary retryable inference errors. Other failures
and batch/runtime policies are unchanged; see
[package transport and limits](../../../core/local_code/README.md).

| File | Role |
|---|---|
| `wrapper.py` | `run_skill(sandbox, **kwargs)` — forwards `model_type`, configs, sample sets and `inference_batch` to `sandbox.execute_inference`. |
| `estimator.py` | Planning-time VRAM (`estimate_peak_bytes`) and wall-time (`estimate_wall_time_seconds`) estimators (K.2.5). |

## Batch resolution (V21 PR G)

`resolve_forecast_batch(explicit, model_type)` is the single rule for
the batch the wall-time forecast prices at:

- `explicit` (the probe-derived batch from
  `active_params["inference_batch"]`, supplied by the
  `evaluate_time_skill` wrapper on the live agent path) → used verbatim.
  Must be a positive `int`; `bool`/non-int/`<= 0` raises `ValueError`
  (fail-closed, never a silent clamp).
- `None` (baselines, legacy scripts, proposer advisory preflight) →
  `core.inference_defaults.inference_batch_for` — the calibrated name
  table with its silent fallback to 25 for unregistered types
  (K.2.5-8). This mirrors the runtime rule in
  `core/sandbox_executor.py::execute_inference` (`:1543`), which treats
  a non-None `inference_batch` as authoritative and falls back to the
  same function.

`estimate_wall_time_seconds(..., inference_batch=None)` threads the
explicit value into the step count (`ceil(total_ml / B)`); it changes
the VALUE of the existing `breakdown.inference_batch` key and adds no
new key. `inference_batch_uncalibrated` keeps its registration meaning
("is this model_type in the table"), independent of whether a hint was
supplied — it is observability-only and never a predicate (C3b pin).

`estimate_peak_bytes` deliberately takes NO explicit-batch override: it
is production-dead on the forecast path — the live VRAM gate probes the
batch structurally (`evaluate_vram_skill/batch_resolver.py`) instead of
pricing this formula.

## Wall-time estimator inputs

| Arg | Type | Default | Description |
|---|---|---|---|
| `model_type` | `str` | — | Architecture key. |
| `model_config` | `dict` | — | Needs `segmentation_size`. |
| `sample_set` | `dict` | — | Eval scope `{file_index: [segments]}`. |
| `inference_ms_per_step` | `float \| None` | `None` | Measured ms/step; `None` → static formula (instantiates the model to count params unless `num_params` given). |
| `num_params` | `int \| None` | `None` | Skips CPU instantiation on the static path. |
| `inference_batch` | `int \| None` | `None` | V21 PR G explicit batch (see above). |

---

## Dataset Profile dependency (PR 02a, 2026-08)

`_total_inference_steps` resolves the decomposition length from the
**Dataset Profile** (`resolve_dataset_profile().dataset.psd_segment_length`)
instead of importing `SEGMENT_LENGTH`. It also accepts an optional
`profile` argument for explicit injection.

**No CLI argument, default value or observable behaviour changed** — under
TIDMAD the resolved value is the same 10,000,000.
