# tests/unit/nodes/ml_hyperparameter_tune_agent

Tuner-node tests pin composed segment-size authoring, guardrail rejection, and
VRAM probe/scope acquisition. They use synthetic configs and probe data; no
LLM or training run is authorized.

## Source and route


## Focused route

`.venv/bin/python -m pytest tests/unit/nodes/ml_hyperparameter_tune_agent/test_c12p_b11_composed_seg_size_authoring.py -q`

Owner: `src/nodes/ml_hyperparameter_tune_agent/`; see the [nodes map](../README.md).
