# `denoising_score_skill` agent contract

## Boundary

This wrapper is the current TIDMAD legacy scoring seam. It is not the generic
scientific-scoring contract: the task-owned sandbox supplies scoring and owns
the scientific meaning of its result.

## Invocation

```python
run_skill(sandbox: TidmadSandbox, **kwargs) -> Any
```

The wrapper reads `exp_id`, `run_name`, `model_type`, `model_config`,
`train_config`, `loss_config`, and optional `task_scopes`. The first six are
forwarded as `exp_id`, `run_name`, `model_type`, `m_cfg`, `t_cfg`, and `l_cfg`
to `sandbox.execute_scoring`; `task_scopes` is forwarded unchanged when
present. Although `skill_config.json` currently omits `run_name`, the wrapper
indexes it directly, so a direct caller must provide it. Missing indexed keys
raise `KeyError`; the sandbox must provide `execute_scoring`.

## Output and effects

The return value is exactly whatever `execute_scoring` returns. The production
path is effectful: it can read task data and inference outputs, launch the
scoring subprocess, and write/return experiment score artifacts. This wrapper
does not compute a metric or validate configs. Existing run-bound
`task_scopes` are forwarded rather than acquired again.

## Estimator surface

`estimator.py` is separate from execution. `estimate_peak_bytes()` reports zero
scoring VRAM because this scoring path is CPU/NumPy/FFT based.
`estimate_wall_time_seconds(sample_set, num_workers=8, hostname=None)` totals
PSD segments and divides by at least one worker using the selected server's
measured per-segment constant. Estimates are planning evidence, not scores.

## Evidence

`tests/unit/agent/denoising_score_skill/test_estimator.py` covers estimator
shape, arithmetic, worker flooring, measured host constants, and unknown-host
fallback. Wrapper call-shape and executor behavior belong to focused unit or
integration tests; stubs are appropriate offline, not scientific evidence.
