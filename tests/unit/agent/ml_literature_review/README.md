# Literature-review node tests

The source owner is [`ml_literature_review.py`](../../../../src/nodes/ml_literature_review/ml_literature_review.py), with schemas in [`literature_review.py`](../../../../src/agent/schemas/literature_review.py). `test_node.py` uses fake bridge/skill objects and `tmp_path` to cover full-run records, max-round termination, root-cache hit/miss, compression fallback, escalation/paywall/arXiv routing, and provenance decision logs. `test_cli.py` and card/schema tests cover the public boundary. No network or paper resolver is contacted; `goldens/` remains fixture-only.

`.venv/bin/python -m pytest tests/unit/agent/ml_literature_review/test_node.py -q`
