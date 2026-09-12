# Agent schema contract tests

The authority is [`src/agent/schemas`](../../../../src/agent/schemas/), with each Pydantic model owning its local shape. `test_cross_schema_invariants.py` tests concepts spanning layers: legal trial portions, nonzero attempt budgets, dataset-bounded file indexes, seed alignment, and one admission vocabulary; these are deliberately not per-field round-trip tests. Other modules cover health feedback, model I/O, ordering and reachability. Construction is synthetic and deterministic; no execution, storage recovery, or LLM is used.

`.venv/bin/python -m pytest tests/unit/agent/schemas/test_cross_schema_invariants.py -q`
