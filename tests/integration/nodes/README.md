# tests/integration/nodes

Node integration covers deterministic cache accumulation and isolated node
wiring. Provider construction belongs to the single LLM gateway and live task
workflows belong to external consumers; this directory is not a hidden
provider/GPU qualification suite.

## Source and route

`.venv/bin/python -m pytest tests/integration/nodes/test_interpretation_cache_accumulator.py -q`

The composed tuner boundary is exercised by:

```bash
.venv/bin/python -m pytest \
  tests/integration/workflows/test_data_scope_tuner_pseudo.py \
  tests/integration/workflows/test_healthgate_ten_collapse_continuation.py -q
```

Owner: `src/nodes/` and `src/agent/llm_bridge.py`. See the
[integration map](../README.md).
