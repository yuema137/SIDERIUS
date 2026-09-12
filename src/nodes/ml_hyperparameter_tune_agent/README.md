# Hyperparameter tuning node

`HyperparamTuningAgent` validates run-bound input, plans attempts, applies
resource/time admission, and records trial/formal training, inference,
scoring, health and provenance. It owns the reference execution loop, not
task data, metric semantics, or model schemas.

- [Public entry and CLI](ml_hyperparameter_tune_agent.py) · [full guide](ml_hyperparameter_tune_agent.md)
  (`cli.py` is a private parser/input adapter used by that entrypoint.)
- Input/output owners: [HyperparamTuningInput/HyperparamTuningOutput](../../agent/schemas/hyperparam_tuning.py)
- Incoming [ml_model_valid_to_ml_model_tune](../../agent/schemas/protocols/ml_model_valid_to_ml_model_tune.py); outgoing [ml_model_tune_to_ml_result_interp](../../agent/schemas/protocols/ml_model_tune_to_ml_result_interp.py)
- Planning/transport/policy coverage: [tests/unit/nodes/ml_hyperparameter_tune_agent](../../../tests/unit/nodes/ml_hyperparameter_tune_agent/)

Training/inference/scoring are effectful sandbox subprocesses; pseudo-sandbox
tests cover only call-boundary parity, not scientific results.
