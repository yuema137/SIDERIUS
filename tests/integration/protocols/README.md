# tests/integration/protocols

Protocol tests exercise typed hand-offs between agent schemas (interpret→propose,
propose→implement, implement→validate, tune→interpret). Inputs are synthetic;
the tests catch dropped fields and invalid boundary wiring without LLM/training.

## Source and route

`.venv/bin/python -m pytest tests/integration/protocols/test_implement_to_validate.py -q`

Owner: `src/agent/schemas/protocols/`. See the [integration map](../README.md).
