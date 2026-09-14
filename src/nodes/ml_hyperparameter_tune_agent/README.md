# Hyperparameter tuning node

Use this node when a validated model must be trained and compared in bounded
rounds. `HyperparamTuningAgent` validates run-bound input, plans attempts, applies
resource/time admission, and records trial/formal training, inference,
scoring, health and provenance. It owns the reference execution loop, not
task data, metric semantics, or model schemas.

- [Public entry and CLI](ml_hyperparameter_tune_agent.py) · [full guide](ml_hyperparameter_tune_agent.md)
  (`cli.py` is a private parser/input adapter used by that entrypoint.)
- Input/output owners: [HyperparamTuningInput/HyperparamTuningOutput](../../agent/schemas/hyperparam_tuning.py)
- Incoming [ml_model_valid_to_ml_model_tune](../../agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py); outgoing [ml_model_tune_to_ml_result_interp](../../agent/schemas/protocols/ml_model_tune_to_ml_result_interp.py)
- Planning/transport/policy coverage: [tests/unit/nodes/ml_hyperparameter_tune_agent](../../../tests/unit/nodes/ml_hyperparameter_tune_agent/)

Effects: training, inference, scoring, and Health checks run in sandbox
subprocesses and write records to the caller workspace. Start with the
[node contract](ml_hyperparameter_tune_agent.md) for exact lifecycle and
failure behavior; pseudo-sandbox tests cover call-boundary parity only.
