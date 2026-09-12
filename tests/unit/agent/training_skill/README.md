# Training estimator tests

The source owner is [`training_skill/estimator.py`](../../../../src/agent/skills/training_skill/estimator.py). `test_estimator.py` checks model-family memory terms (focal one-hot, RNN, transformer attention, FC activations), parameter/batch/segment scaling, static and measured wall-time paths, GPU-name calibration refusal, epoch scaling, and trial-portion effects. Synthetic two-family profiles and monkeypatches keep the route CPU-only; it does not train or probe a device.

`.venv/bin/python -m pytest tests/unit/agent/training_skill/test_estimator.py -q`
