# Judge call/evidence tests

The authority is [`src/agent/judge`](../../../../src/agent/judge/judge-contract.md). The suite pins judge prompt bytes, proves replay from recorded evidence without a provider, and refuses tampered, foreign or reordered evidence. Provider access is a stub or a real `LLMBridge` with a mocked client; no provider is called.

`.venv/bin/python -m pytest tests/unit/agent/judge -q`
