# ML-code validator node tests

The node owner is [`ml_code_validator_agent.py`](../../../../src/nodes/ml_code_validator_agent/ml_code_validator_agent.py); its input/output contract is in the adjacent node manual and `agent.schemas.validator`. `test_inheritance_check.py` uses tiny synthetic PyTorch classes to verify claimed capability/vocabulary matching, case handling, and missing-component failures; other tests cover mocked validation, schemas, prompt goldens, and realized parameter counts. No generated plugin is run.

`.venv/bin/python -m pytest tests/unit/agent/ml_code_validator_agent/test_inheritance_check.py -q`
