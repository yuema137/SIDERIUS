# Judge call/evidence tests

These tests check the LLM judge core in [`src/agent/judge`](../../../../src/agent/judge/judge-contract.md): the judge prompt bytes stay fixed, a recorded call can be replayed from its evidence file without contacting a provider, and tampered, foreign or reordered evidence is refused. No real provider is called; each test uses a stub bridge or a real `LLMBridge` with a mocked client, so no API key is needed.

Prerequisite: in this checkout, install the locked development environment once.

```bash
uv sync --group dev --frozen
```

Run the suite:

```bash
.venv/bin/python -m pytest tests/unit/agent/judge -q
```

Success looks like a single summary line such as `24 passed`, with no failures or errors. A failing pin test means the judge prompt, request or response schema changed; that needs a new template version, not an updated digest.
