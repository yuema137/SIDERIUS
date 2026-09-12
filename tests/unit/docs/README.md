# tests/unit/docs

Documentation contracts resolve protocol tokens, CLI declarations, and node
reference links; failures identify stale public docs rather than runtime code.

## Source and route

`.venv/bin/python -m pytest tests/unit/docs/test_node_docs_contract.py -q`

Owner: node markdown and `docs/agent-reference/README.md`; no provider/runtime effects.
