# LLM gateway tests

The single provider boundary is [`src/agent/llm_bridge.py`](../../../../src/agent/llm_bridge.py). `test_all_calls_labeled.py` statically walks node call sites to catch unlabeled gateway calls; companion tests cover marker emission, usage accounting, timeouts/bounded retry, crash propagation, key-environment refusal, and no-silent-swallow behavior. Bridges/providers are mocked or inert, so these tests do not establish credentials or live API behavior. `goldens/` contains prompt payload fixtures owned by individual tests.

`.venv/bin/python -m pytest tests/unit/agent/llm_bridge/test_all_calls_labeled.py -q`
