# LLM gateway tests

The single provider boundary is [`src/agent/llm_bridge.py`](../../../../src/agent/llm_bridge.py). `test_all_calls_labeled.py` statically walks node call sites to catch unlabeled gateway calls; companion tests cover marker emission, usage accounting, timeouts/bounded retry, crash propagation, key-environment refusal, and no-silent-swallow behavior. Bridges/providers are mocked or inert, so these tests do not establish credentials or live API behavior. `goldens/` contains prompt payload fixtures owned by individual tests.

`.venv/bin/python -m pytest tests/unit/agent/llm_bridge/test_all_calls_labeled.py -q`

`test_single_tool_admission.py` exercises legacy responses through the real SDK
with an offline HTTP transport. It checks complete declared calls, rejected
ambiguous or malformed results, billed usage, and deadline precedence. The
Direct API witnesses exercise the same admission rules through its adapter.

Whenever `llm_bridge.py` changes, also run
`.venv/bin/python -m pytest tests/unit/agent/test_planner_strategy.py -q`.
The native planner pins the bridge source for workspace resume, even when
planner prompt content is unchanged. A moved assembly pin needs an explicit
compatibility note and freeze-batch requalification.
