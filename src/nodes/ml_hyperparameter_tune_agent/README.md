# Hyperparameter tuning node

Use this node when a validated model must be trained and compared in bounded
rounds. `HyperparamTuningAgent` validates run-bound input, plans attempts, applies
resource/time admission, and records trial/formal training, inference,
scoring, health and provenance. It owns the reference execution loop, not
task data, metric semantics, or model schemas.

Runs use trial/formal tuning by default: Trial rounds explore configurations,
and the final tuning round is Formal under the default schedule. In the node
CLI, passing `--is_trial` explicitly also pins the trial sampling portions.
Use `--no-is_trial` only for legacy single-file execution on a task with TIDMAD
topology. See the [full guide](ml_hyperparameter_tune_agent.md) for these controls.

Before each attempt runs, the console shows effective configuration changes
and their override authority, followed by the planner's original proposal.
For example, if `full_clone` inherits batch size 4 after the planner proposed 8,
the log shows `8 -> effective 4` and labels the proposal as superseded. The
preceding inheritance line identifies the winning trial. These are prepared
request values; training results are reported separately after execution.

Operator `plan_overrides` replace complete plan fields. For example,
`{"train_config": {"lr": 0.002}}` replaces the whole training dictionary;
include `epochs` too if you want to retain an explicit epoch count. The
provenance labels omitted keys as not supplied by the replacement. Later
resolution and trainer defaults can still apply; omission does not mean zero.

The next planner sees the same distinction in its experiment history. Each
record whose proposal was changed keeps the planner's original hypothesis,
plus a `resolution_events` list (for example `train_cfg.lr` proposed `0.0001`,
executed `0.002`) and a label saying the hypothesis was superseded. Formal
attempts usually carry this label, because the framework routinely resolves
their mode (`is_trial`) and data portions, not only when an operator overrides
a value. The list is kept even after older records are shortened to a summary;
there, very long values such as file lists are cut to a short head and tail.
This shortens each value, not the whole entry: all changed fields and their
names remain, so many changes or long field names can still make a large summary.
The record's `status` still says whether the attempt actually ran. A record
whose plan ran exactly as proposed looks the same as before.

- [Public entry and CLI](ml_hyperparameter_tune_agent.py) · [full guide](ml_hyperparameter_tune_agent.md)
  (`cli.py` is a private parser/input adapter used by that entrypoint.)
- Input/output owners: [HyperparamTuningInput/HyperparamTuningOutput](../../agent/schemas/hyperparam_tuning.py)
- Incoming [ml_model_valid_to_ml_model_tune](../../agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py); outgoing [ml_model_tune_to_ml_result_interp](../../agent/schemas/protocols/ml_model_tune_to_ml_result_interp.py)
- Planning/transport/policy coverage: [tests/unit/nodes/ml_hyperparameter_tune_agent](../../../tests/unit/nodes/ml_hyperparameter_tune_agent/)

Effects: training, inference, scoring, and Health checks run in sandbox
subprocesses and write records to the caller workspace. Start with the
[node contract](ml_hyperparameter_tune_agent.md) for exact lifecycle and
failure behavior; pseudo-sandbox tests cover call-boundary parity only.
