# Protocol transport tests

Protocol owners are the typed modules in [`src/agent/schemas/protocols`](../../../../src/agent/schemas/protocols/) and their upstream/downstream schemas. `test_ml_model_propose_to_ml_model_impl.py` checks local-storage path mapping, baseline/custom-loss forwarding, explicit output-contract transport, and the deliberate database `NotImplementedError`; other routes cover every reference edge and candidate-ID/model-I/O transport. Inputs are Pydantic objects and temporary configs, not files read from upstream storage; no node or provider runs.

`.venv/bin/python -m pytest tests/unit/agent/protocols/test_ml_model_propose_to_ml_model_impl.py -q`
