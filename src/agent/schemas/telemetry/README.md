# `src/agent/schemas/telemetry/`

[`token_usage.py`](token_usage.py) owns the Pydantic rows written by the LLM
bridge to `token_usage.jsonl`: provider counts, local prompt character counts,
call labels, run identity, and iteration markers. It is observational
provenance, not a scientific metric or optimization signal.

The bridge is the producer and report/roll-up readers are consumers; neither
belongs in this schema package. JSONL roll-up behavior is checked by
[`test_token_log_iter_rollup.py`](../../../../tests/integration/runner/test_token_log_iter_rollup.py).
