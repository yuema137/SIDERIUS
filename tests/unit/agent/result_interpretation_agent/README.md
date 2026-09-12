# Result-interpretation node tests

The owner is [`result_interpretation_agent.py`](../../../../src/nodes/result_interpretation_agent/result_interpretation_agent.py), with score/interpretation contracts in `agent.schemas.score_table` and `agent.schemas.interpretation`. `test_interpretation_agent.py` uses synthetic metric fixtures and mocked bridges to cover single/multi-model aggregation, knowledge-cache hit/miss, per-model routing, unknown/missing model errors, and persisted output. Sibling tests guard health feedback, ordering, compressed summaries, and prompt parity. `goldens/` and `_step09a_fixture.py` are fixtures, not executable inputs.

`.venv/bin/python -m pytest tests/unit/agent/result_interpretation_agent/test_interpretation_agent.py -q`
