# Hyperparameter-tuner node tests

The node is owned by [`src/nodes/ml_hyperparameter_tune_agent`](../../../../src/nodes/ml_hyperparameter_tune_agent/); phase helpers/contracts remain beside its implementation. The focused `test_control_boundary.py` checks extracted-helper ownership, patch substitutability, cleanup of seven transient resources, failure/skip record shape, admission refusal vocabulary and approved reachability. Other tests cover retries, budgets, data scope, degeneracy, attribution and time gates. Fixtures/goldens remain data-only; unit tests mock execution and never train.

`.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent/test_control_boundary.py -q`
