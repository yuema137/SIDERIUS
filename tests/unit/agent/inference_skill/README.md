# Inference estimator tests

The source owner is [`inference_skill/estimator.py`](../../../../src/agent/skills/inference_skill/estimator.py), with calibration/forecast contracts in its wrapper and skill manual. `test_estimator.py` checks byte terms for weights, RNN/transformer attention and batch scaling, wall-time monotonicity, registered versus runtime fallbacks, and explicit forecast-batch precedence/validation. Two-family profiles are synthetic and monkeypatched; no inference or GPU is performed. The calibration-pin test is a separate dated authority regression.

`.venv/bin/python -m pytest tests/unit/agent/inference_skill/test_estimator.py -q`
