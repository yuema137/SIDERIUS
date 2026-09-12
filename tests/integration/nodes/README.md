# tests/integration/nodes

Node integration covers mock-LLM cache accumulation plus isolated node wiring.
Most modules are `real_run` and skipped unless credentials/options are supplied;
those paths may call providers, Semantic Scholar/arXiv, or CUDA. Synthetic
mock-chain tests remain local and deterministic.

## Source and route

`.venv/bin/python -m pytest tests/integration/nodes/test_interpretation_cache_accumulator.py -q`

Owner: `src/nodes/` and `src/agent/llm_bridge.py`; use `-m real_run` only for
the explicitly documented live routes. See the [integration map](../README.md).
