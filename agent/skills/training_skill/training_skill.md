# training_skill

Atomic tool that launches one training run for one experiment. Called by
`ml_hyperparameter_tune_agent` once per attempt, via `_run_skill`.

The skill is a thin, deliberate seam: it validates nothing and decides
nothing. It forwards an already-resolved configuration to the sandbox
executor, which owns config persistence, DataScope boundary validation,
subprocess launch, and the runtime watchdog.

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
| `sample_set` | `dict \| None` | No | `None` | `{file_index: [segment_indices]}` — the training data scope. `None` selects the legacy single-file path. |
| `train_portion` | `float \| None` | No | `None` | Per-epoch subsample fraction from the scope. |
| `train_base_seed` | `int \| None` | No | `None` | Base seed for per-epoch subsampling; epoch `n` uses `train_base_seed + n`. |
| `runtime_policy` | `dict \| None` | No | `None` | RT2-G operator runtime policy; validated against `RuntimeControlPolicy` at the executor. |
| `order_strategy` | `str` | No | `"shuffle"` | **Resolved** training sample visitation order (V19 PR 2). |
| `file_order` | `list[int] \| None` | No | `None` | **Resolved** file visitation order for `sequential`. |

## Output

Returns the sandbox executor's result dict unchanged — `status`,
`message`, `results` (loss history, model params), and
`runtime_verification` (the RT2 observation block, or `None` in pseudo
mode).

## Key behavioral notes

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

`StubSandbox.execute_training` mirrors this signature exactly, including
the ordering parameters, even though the stub trains nothing and has no
visitation order to apply. Pseudo-mode runs must not diverge from
production at the call boundary, or a pseudo test could pass against a
call shape production would reject.

## Dependencies

- `core/sandbox_executor.py` — `TidmadSandbox` / `StubSandbox`
- `execute_tools/train_engine_sandbox.py` — the training subprocess
- `skill_config.json` — the LLM-facing tool schema (legacy; the tuner
  calls `run_skill` directly rather than through tool-calling)
