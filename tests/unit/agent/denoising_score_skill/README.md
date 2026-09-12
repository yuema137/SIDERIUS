# Denoising-score estimator tests

The source owner is [`estimator.py`](../../../../src/agent/skills/denoising_score_skill/estimator.py). `test_estimator.py` is pure arithmetic: peak-byte shape, worker flooring, segment/worker wall-time scaling, measured Li-group constant, and unknown-host fallback are checked with monkeypatches. It uses no model, GPU, disk, or API; the tests catch formula and fallback regressions beyond typing. Focused route:

`.venv/bin/python -m pytest tests/unit/agent/denoising_score_skill/test_estimator.py -q`
