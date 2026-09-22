# training_skill

Atomic tool that launches one training run for one experiment. Called by
`ml_hyperparameter_tune_agent` once per attempt, via `_run_skill`.

The skill is a thin, deliberate seam: it validates nothing and decides
nothing. It forwards an already-resolved configuration to the sandbox
executor, which owns config persistence, DataScope boundary validation,
subprocess launch, and the runtime watchdog.

The skill groups resolved task scopes and the expected custom-loss snapshot
into one internal `TrainingExecutionBindings` value at the sandbox boundary.
This keeps the executor signature bounded while preserving the two independent
caller-facing keys below; the carrier adds no authority or fallback.

## Position in the pipeline

```text
ml_hyperparameter_tune_agent
  -> training_skill.run_skill(sandbox, **active_params)
     -> TidmadSandbox.execute_training(...)        [production]
        -> subprocess: execute_tools/train_engine_sandbox.py
     -> StubSandbox.execute_training(...)          [pseudo mode]
```

## Input

`run_skill(sandbox, **kwargs)` — keys read from `kwargs`:

| Key | Type | Required | Default | Description |
|---|---|---|---|---|
| `exp_id` | `str` | Yes | — | Unique experiment identifier; names every artifact of this attempt. |
| `run_name` | `str` | Yes | — | Run name (output directory grouping). |
| `model_type` | `str` | Yes | — | Architecture key, built-in or plugin. |
| `model_config` | `dict` | Yes | — | Architecture hyperparameters. |
| `train_config` | `dict` | Yes | — | Training hyperparameters (`lr`, `epochs`, `batch_size`, `device`). |
| `loss_config` | `dict` | Yes | — | Loss specification. |
| `expected_custom_loss_snapshot` | `CapabilityContractSnapshot \| None` | No | `None` | Transient task-resolved contract for a custom loss. The executor serializes it to a child-only JSON file; both training paths refuse a missing/mismatched plugin contract before loss construction. `None` preserves builtin and uncomposed behavior. |
| `sample_set` | `dict \| None` | No | `None` | `{file_index: [segment_indices]}` — the training data scope. `None` selects the legacy single-file path. |
| `eval_sample_set` | `dict \| None` | No | `None` | **Step 07a** — the tuner's EXISTING run-bound eval SampleSet `{file_index: [segment_indices]}` (VALIDATION file family). Forwarded to `execute_training(eval_sample_set=…)`; in streaming mode (with `sample_set`) the executor validates it by the same DataScope rule as the train set, writes `configs/<run>/eval_sample_set_<exp_id>.json` and passes `--eval_sample_set_json` — the trainer's per-epoch R3 validation pass. Before 07a this kwarg was enumerated away here (the OD-S7-1 transport drop). The tuner decides `expected_validation` from the same value, so a re-dropped eval set now yields an `error_training` record, never a quiet success. |
| `train_portion` | `float \| None` | No | `None` | Per-epoch subsample fraction from the scope. |
| `train_base_seed` | `int \| None` | No | `None` | Base seed for per-epoch subsampling; epoch `n` uses `train_base_seed + n`. |
| `runtime_policy` | `dict \| None` | No | `None` | RT2-G operator runtime policy; validated against `RuntimeControlPolicy` at the executor. |
| `order_strategy` | `str` | No | `"shuffle"` | **Resolved** training sample visitation order (V19 PR 2). |
| `file_order` | `list[int] \| None` | No | `None` | **Resolved** file visitation order for `sequential`. |

## Output

Returns the sandbox executor's result dict unchanged — `status`,
`message`, `results` (`final_loss` / `loss_history` / `model_params` +,
from Step 07a, the additive `training_history` payload: R2 == `loss_history`,
R3 = the per-epoch validation objective on the eval SampleSet, objective
identity, comparability stamp, materialized validation counts, per-epoch
`validation_seconds`), and `runtime_verification` (the RT2 observation
block, or `None` in pseudo mode). The tuner validates `results` through
`execute_tools/training_history.py::interpret_training_results` — the ONE
validation site; this skill still validates nothing.

## Key behavioral notes

Declared task-code integrity refusals propagate to the workflow's named chain
halt, rather than becoming ordinary retryable training errors. This does not
change candidate/provider failures, resource budgets or training semantics;
see [package transport and limits](../../../core/local_code/README.md).

### Ordering values here are already RESOLVED (V19 PR 2)

`order_strategy` / `file_order` carry the values the tuner's resolver
produced by combining the agent's proposal with any operator override.
**This skill never sees a proposal or an override, and never re-derives
precedence** — the whole point of the single-resolver design is that only
one place decides, and everything downstream consumes the decision. The
same holds for the subprocess: `execute_training` emits
`--order_strategy` / `--file_order_json` only, and only when non-default,
so a run that does not use ordering produces argv identical to pre-V19.

Provenance (what the agent proposed, what the operator forced, whether a
proposal was rejected) is recorded by the tuner on the `ExperimentRecord`
— not here. See
`docs/design/v19_priorities/pr2_data_ordering.md` §3.3.

### Signature parity with the stub

`StubSandbox.execute_training` mirrors the production executor signature
exactly, including the grouped execution bindings and
the ordering parameters and (Step 07a) `eval_sample_set` — scope-validated
like production, and answered with a plausible multi-epoch train +
validation `training_history` (R3 only when an eval set was supplied) —
even though the stub trains nothing and has no visitation order to apply. Pseudo-mode runs must not diverge from
production at the call boundary, or a pseudo test could pass against a
call shape production would reject.

## Dependencies

- `core/sandbox_executor.py` — `TidmadSandbox` / `StubSandbox`
- `execute_tools/train_engine_sandbox.py` — the training subprocess
- `skill_config.json` — the LLM-facing tool schema (legacy; the tuner
  calls `run_skill` directly rather than through tool-calling)

## Partial training batches

`train_config.drop_last` defaults to `true`. When false, training retains
the final partial batch and step estimates use ceiling rather than floor.
See [training batch policy](../../../../docs/reference/training-batches.md)
for measured row-count receipts and model compatibility requirements.
