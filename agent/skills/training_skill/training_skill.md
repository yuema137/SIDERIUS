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

## Validation-only stability stop (V20 PR C2)

**Not production behaviour.** `execute_training` and every flag, config key
and default are unchanged. With no channel configured the training loop is
byte-for-byte the loop it was: no file opened, no event written, no signal
read.

When validation infrastructure sets `SIDERIUS_C2_FORMAL_STABILITY` — a
Pydantic-validated JSON channel naming an events path, a stop path, a run
id and a candidate id, never a bare boolean — the trainer:

* appends **one event per COMPLETED optimizer step** to the events path,
  after forward, backward and the optimizer update have all returned, with
  the device synchronized first so the event cannot precede the work it
  claims;
* checks the stop signal **only between completed steps**, so it never
  halts part-way through an update.

**The trainer never decides.** It cannot see its own process tree's
driver-visible memory — only the parent sampler can — so it emits evidence
and obeys a signal. The parent stops the phase when the cumulative
driver-visible peak has not increased for **500 completed steps** and at
least **3 valid readings** were taken after the last increase. Any increase
resets both counters.

**Why this exists.** A Gate's formal arm must stop when the peak has
demonstrably settled *on the machine under test*. An earlier design bounded
it at 2000 steps derived from RTX 5090 timings; those integers describe one
card, and 29 % of the inference phase they came from was filesystem. A 5090
and an H100 now each reach stability after whatever work they individually
need, and no second, step count or MiB figure travels between them.

**Backstops are not passes.** Reaching the 5000-step ceiling or the
configurable wall-clock cap yields `INCONCLUSIVE`: the peak was still moving
when measurement stopped, so no requirement is claimed and no limit is
raised mid-Gate.

**A validation stop is not a scientific training run.** It is recorded as a
validation-bounded completion — completed steps, last peak-increase step,
stable steps, readings after the last increase, stop reason, backstop state,
driver peak, allocator diagnostics — and carries no score and no convergence
evidence.

**Both engines emit.** `run_experiment_streaming` (the production path,
taken whenever a sample set is supplied — every Gate arm and every chain
round) and `run_experiment` (legacy single-file, `sample_set is None`) each
call `StepEventLog.observe_completed_step`. This is one call rather than
`record_completed_step` followed by `should_stop` because a four-line
extension point reaches one loop and not the other — which is exactly what
happened: the first wiring landed only in `run_experiment`, so no Gate arm
would have emitted a single event. A structural test now scopes to each
function by name and is parameterized over both.

**The stop ends the phase, not just the epoch.** After breaking out of the
batch loop the streaming engine leaves the epoch loop too; continuing into
epoch 1 would keep executing after the parent concluded the peak had
settled. The checkpoint and summary are still written exactly as for an
epoch that ran to its end — the formal arm's inference phase needs that
checkpoint.

**Production is untouched.** With the variable unset there is no channel,
no file is opened, no event written, no signal read, and both loops are
byte-for-byte the loops they were. There is no CLI flag and no config key:
the absence of the channel *is* the disabled state, and a bare
`SIDERIUS_C2_FORMAL_STABILITY=1` is refused because the value must be a
channel, never a switch.
