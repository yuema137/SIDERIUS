# tests/unit/agent_generated

Generated-agent loader tests pin capability registration, loss loading, and
stub plugin import failures using local synthetic modules; no LLM is called.

## Source and route

`.venv/bin/python -m pytest tests/unit/agent_generated/test_capability_registry.py -q`

The historical directory name is not a production package; the tests exercise
`core.capability_registry` and temporary atomic-index writes. See the [unit map](../README.md).
