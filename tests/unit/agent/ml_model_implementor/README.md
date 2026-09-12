# Model-implementor node tests

The owner is [`ml_model_implementor.py`](../../../../src/nodes/ml_model_implementor/ml_model_implementor.py), validated by `agent.schemas.implementor`. `test_implementor_agent.py` uses mocked bridge calls and temporary workspaces to assert call ordering, generated plugin/test/description assembly, absolute output paths, input-derived metadata, contract echo, persistence, and config-field consistency. Sibling tests cover schema, loss helpers, registration, and baseline self-checks. `goldens/` is payload data only; no generated model is trained here.

`.venv/bin/python -m pytest tests/unit/agent/ml_model_implementor/test_implementor_agent.py -q`
